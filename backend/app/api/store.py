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
from app.services import store_actions as actions_svc
from app.services import store_context as ctx_svc
from app.services import store_demo as demo
from app.services import store_proactive as proactive
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
    return {"customer": svc.customer_profile(db, c), "orders": [svc.order_to_dict(o, include_address=True) for o in svc.orders_for_email(db, c.email)]}


# --------------------------------------------------------- chatbot page context
class ContextLine(BaseModel):
    product_id: str = Field(max_length=32)
    size: str = Field(max_length=16)
    quantity: int = Field(ge=1, le=svc.MAX_QTY)


class ContextIn(BaseModel):
    session_id: str = Field(min_length=8, max_length=64)
    page: str = Field(max_length=16)
    category: Optional[str] = Field(default=None, max_length=32)
    product_id: Optional[str] = Field(default=None, max_length=32)
    size: Optional[str] = Field(default=None, max_length=16)
    cart: List[ContextLine] = Field(default_factory=list, max_length=svc.MAX_LINES)


@router.post("/context")
@limiter.limit("120/minute")
def set_context(request: Request, payload: ContextIn, db: Session = Depends(get_db),
                x_chat_token: Optional[str] = Header(default=None)):
    """The storefront tells the chatbot what the visitor is looking at. Only the owner of the chat session (proved by its
    signed session token) can set it, and only identifiers are accepted (see services/store_context.py)."""
    from app.auth.security import decode_session_token
    if not x_chat_token or decode_session_token(x_chat_token) != payload.session_id:
        raise HTTPException(status_code=401, detail="Invalid chat session")
    ctx_svc.save_context(db, payload.session_id, payload.model_dump())
    return {"ok": True}


@router.get("/actions")
@limiter.limit("180/minute")
async def pending_actions(request: Request, session_id: str = Query(min_length=8, max_length=64), db: Session = Depends(get_db),
                    x_chat_token: Optional[str] = Header(default=None)):
    """Things the chatbot asked this page to do (add to bag, open a page). Delivered once, to the session's owner only."""
    from app.auth.security import decode_session_token
    if not x_chat_token or decode_session_token(x_chat_token) != session_id:
        raise HTTPException(status_code=401, detail="Invalid chat session")
    try:
        await proactive.deliver_pending(session_id)   # order updates the assistant wants to tell this customer
    except Exception:  # a failed courtesy message must never break the page's polling
        pass
    return {"actions": actions_svc.pop_actions(db, session_id)}


class NudgeIn(BaseModel):
    session_id: str = Field(min_length=8, max_length=64)
    kind: str = Field(max_length=24)


@router.post("/nudge")
@limiter.limit("30/minute")
async def nudge(request: Request, payload: NudgeIn, x_chat_token: Optional[str] = Header(default=None)):
    """The page noticed the visitor hesitating; ask the assistant to speak first. Only the chat's owner can ask, the message is
    written server-side from the database, and it is rate-limited (see services/store_proactive.py)."""
    from app.auth.security import decode_session_token
    if not x_chat_token or decode_session_token(x_chat_token) != payload.session_id:
        raise HTTPException(status_code=401, detail="Invalid chat session")
    return await proactive.send_nudge(payload.session_id, payload.kind)


@router.post("/orders/{order_id}/cancel")
@limiter.limit("10/minute")
async def cancel_my_order(request: Request, order_id: str, db: Session = Depends(get_db), authorization: Optional[str] = Header(default=None)):
    """A signed-in customer cancels their own order (only while it is still 'processing')."""
    email = auth.customer_email_from_header(authorization)
    if not email:
        raise HTTPException(status_code=401, detail="Please sign in.")
    try:
        order = svc.cancel_order(db, order_id, email=email)
    except svc.StoreError as e:
        raise HTTPException(status_code=404 if e.code == "not_found" else 409, detail={"code": e.code, "message": str(e)})
    result = svc.order_to_dict(order, include_email=True)
    try:   # an open chat (and the agent looking at it) hears about it straight away
        await proactive.announce_to_customer(email, f"I can see you just cancelled order #{order.order_id} from your account. It's done: the payment is voided and the items are back in stock. Anything else I can help with?")
    except Exception:
        pass
    return result


class LinkIn(BaseModel):
    session_id: str = Field(min_length=8, max_length=64)


@router.post("/chat/link")
@limiter.limit("30/minute")
async def link_chat(request: Request, payload: LinkIn, authorization: Optional[str] = Header(default=None),
                    x_chat_token: Optional[str] = Header(default=None)):
    """A customer signs in while a chat is already running: attach the account to THAT conversation instead of starting a new one.
    Needs both proofs: the customer's login token and the chat's own session token."""
    from app.auth.security import decode_session_token
    email = auth.customer_email_from_header(authorization)
    if not email:
        raise HTTPException(status_code=401, detail="Please sign in.")
    if not x_chat_token or decode_session_token(x_chat_token) != payload.session_id:
        raise HTTPException(status_code=401, detail="Invalid chat session")
    result = await proactive.link_session(payload.session_id, email)
    if result == "conflict":   # this conversation already belongs to somebody else: the page starts a fresh one
        raise HTTPException(status_code=409, detail={"code": "chat_belongs_to_another_customer", "message": "This chat belongs to another account."})
    return {"linked": True, "first_time": result == "linked"}


# ------------------------------------------------------------- presenter controls (only with STORE_DEMO_MODE=1)
def _demo_only():
    if not demo.enabled():
        raise HTTPException(status_code=404, detail="Not found")


class DemoLoginIn(BaseModel):
    email: str = Field(pattern=_EMAIL, max_length=254)


class DemoOrderIn(BaseModel):
    action: str = Field(max_length=16)


class DemoStockIn(BaseModel):
    preset: str = Field(max_length=32)


@router.get("/demo/status")
def demo_status():
    return {"enabled": True, "customers": demo.customers()} if demo.enabled() else {"enabled": False}


@router.post("/demo/login")
@limiter.limit("30/minute")
def demo_login(request: Request, payload: DemoLoginIn, db: Session = Depends(get_db)):
    _demo_only()
    c = svc.customer_by_email(db, payload.email) if payload.email.lower() in demo.DEMO_EMAILS else None
    if not c:
        raise HTTPException(status_code=404, detail="Not found")
    svc.mark_login(db, c)
    return _session_payload(c)


@router.post("/demo/order")
@limiter.limit("60/minute")
def demo_order(request: Request, payload: DemoOrderIn, db: Session = Depends(get_db), authorization: Optional[str] = Header(default=None)):
    _demo_only()
    email = auth.customer_email_from_header(authorization)
    if not email:
        raise HTTPException(status_code=401, detail="Sign in first.")
    try:
        return demo.new_test_order(db, email) if payload.action == "new" else demo.order_action(db, email, payload.action)
    except svc.StoreError as e:
        raise HTTPException(status_code=409, detail={"code": e.code, "message": str(e)})


@router.post("/demo/stock")
@limiter.limit("60/minute")
def demo_stock(request: Request, payload: DemoStockIn, db: Session = Depends(get_db)):
    _demo_only()
    try:
        return {"message": demo.stock_preset(db, payload.preset)}
    except svc.StoreError as e:
        raise HTTPException(status_code=422, detail={"code": e.code, "message": str(e)})


@router.post("/demo/reset")
@limiter.limit("10/minute")
def demo_reset(request: Request, db: Session = Depends(get_db)):
    _demo_only()
    return demo.reset(db, chats=False)
