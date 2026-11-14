"""
Public storefront API (mounted at /api/store).

- GET  /api/store/products[?category=]      catalog with live per-size stock
- GET  /api/store/products/{product_id}
- POST /api/store/orders                    checkout (server-side prices, atomic stock)
- GET  /api/store/orders/{order_id}?email=  order tracking (email must match)
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.limiter import limiter
from app.services import customer_auth as auth
from app.services import store_service as svc

router = APIRouter(tags=["store"])

_EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class OrderItemIn(BaseModel):
    product_id: str = Field(min_length=1, max_length=32)
    size: str = Field(min_length=1, max_length=16)
    quantity: int = Field(ge=1, le=svc.MAX_QTY)


class OrderIn(BaseModel):
    email: str = Field(pattern=_EMAIL, max_length=254)
    name: str = Field(min_length=1, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=40)
    address: str = Field(min_length=1, max_length=300)
    city: str = Field(min_length=1, max_length=120)
    zip: str = Field(min_length=1, max_length=32)
    country: Optional[str] = Field(default=None, max_length=80)
    items: List[OrderItemIn] = Field(min_length=1, max_length=svc.MAX_LINES)


@router.get("/products")
def list_products(category: Optional[str] = Query(default=None, max_length=32), db: Session = Depends(get_db)):
    return {"products": svc.list_products(db, category)}


@router.get("/products/{product_id}")
def get_product(product_id: str, db: Session = Depends(get_db)):
    product = svc.get_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.post("/orders", status_code=201)
@limiter.limit("10/minute")
def create_order(request: Request, payload: OrderIn, db: Session = Depends(get_db), authorization: Optional[str] = Header(default=None)):
    signed_in = auth.customer_email_from_header(authorization)  # a signed-in customer always orders as themselves
    try:
        order = svc.create_order(
            db, email=signed_in or payload.email, name=payload.name, address=payload.address, city=payload.city,
            zip_code=payload.zip, phone=payload.phone, country=payload.country,
            items=[i.model_dump() for i in payload.items],
        )
    except svc.StoreError as e:
        status = 409 if e.code in ("out_of_stock", "busy") else 422
        raise HTTPException(status_code=status, detail={"code": e.code, "message": str(e)})
    return svc.order_to_dict(order, include_email=True)


@router.get("/orders/{order_id}")
@limiter.limit("30/minute")
def track_order(request: Request, order_id: str, email: str = Query(min_length=3, max_length=254),
                db: Session = Depends(get_db)):
    order = svc.get_order(db, order_id, email=email)
    if not order:  # same answer for "no such order" and "wrong email"
        raise HTTPException(status_code=404, detail="Order not found")
    return svc.order_to_dict(order, include_email=True)


# ----------------------------------------------------------- customer accounts
class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(pattern=_EMAIL, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: str = Field(pattern=_EMAIL, max_length=254)
    password: str = Field(min_length=1, max_length=128)


def _session_payload(c) -> dict:
    return {"token": auth.issue_customer_token(c.email, c.name), "customer": {"name": c.name, "email": c.email}}


@router.post("/auth/register", status_code=201)
@limiter.limit("5/minute")
def register(request: Request, payload: RegisterIn, db: Session = Depends(get_db)):
    try:
        c = svc.register_customer(db, name=payload.name, email=payload.email, password_hash=auth.hash_pw(payload.password))
    except svc.StoreError as e:
        raise HTTPException(status_code=409, detail={"code": e.code, "message": str(e)})
    return _session_payload(c)


@router.post("/auth/login")
@limiter.limit("10/minute")
def login(request: Request, payload: LoginIn, db: Session = Depends(get_db)):
    c = svc.customer_by_email(db, payload.email)
    if not auth.check_pw(payload.password, c.password_hash if c else None):  # same answer for "no account" and "wrong password"
        raise HTTPException(status_code=401, detail={"code": "bad_credentials", "message": "Incorrect email or password."})
    svc.mark_login(db, c)
    return _session_payload(c)


@router.get("/auth/me")
@limiter.limit("60/minute")
def me(request: Request, db: Session = Depends(get_db), authorization: Optional[str] = Header(default=None)):
    email = auth.customer_email_from_header(authorization)
    c = svc.customer_by_email(db, email) if email else None
    if not c:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return {"customer": svc.customer_profile(db, c), "orders": [svc.order_to_dict(o) for o in svc.orders_for_email(db, c.email)]}
