"""
EcommerceProvider backed by the storefront database (app/db/store_models.py).

Select it with the environment variable  ECOMMERCE_PROVIDER=store_db.  It answers the bot's
tool calls (order status, order by email, refunds, recommendations, purchase tracking) from the
same tables the website writes to, so an order placed on the storefront is immediately visible
to the chatbot, with real stock levels and real prices.
"""

from __future__ import annotations

import datetime
import os
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.db.store_models import StoreCustomer, StoreOrder, StoreProduct
from app.services import store_service as svc

from .base import EcommerceProvider

# Where product pages live (used for the links the bot sends). Set STORE_PUBLIC_URL in production.
_DEFAULT_RECOMMENDATIONS = ["WRN-TSH-301", "WRN-SHO-101"]


def _store_url() -> str:
    return (os.environ.get("STORE_PUBLIC_URL") or "http://127.0.0.1:8000").rstrip("/")


class StoreDBProvider(EcommerceProvider):
    # Same posture as the Shopify provider: the bot must see the order's email before revealing it.
    requires_verification = True

    def __init__(self, session_factory: Optional[Callable[[], Session]] = None):
        self._session = session_factory or SessionLocal

    # ---- orders --------------------------------------------------------
    def get_order_status(self, order_id: str, verify_email: Optional[str] = None,
                         include_email: bool = False) -> Optional[Dict[str, Any]]:
        with self._session() as db:
            order = svc.get_order(db, order_id, email=verify_email)
            return svc.order_to_dict(order, include_email) if order else None

    def get_order_by_email(self, email: str, include_email: bool = False) -> Optional[Dict[str, Any]]:
        if not email:
            return None
        with self._session() as db:
            order = svc.latest_order_for_email(db, email)
            return svc.order_to_dict(order, include_email) if order else None

    def get_customer_info(self, email: Optional[str] = None, phone: Optional[str] = None,
                          customer_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._session() as db:
            q = select(StoreCustomer)
            if email:
                q = q.where(StoreCustomer.email == email.strip().lower())
            elif phone:
                q = q.where(StoreCustomer.phone == phone.strip())
            elif customer_id and str(customer_id).isdigit():
                q = q.where(StoreCustomer.id == int(customer_id))
            else:
                return None
            c = db.execute(q).scalars().first()
            if not c:
                return None
            orders = db.execute(select(StoreOrder).where(StoreOrder.customer_id == c.id)
                                .order_by(StoreOrder.created_at.desc())).scalars().all()
            spent = sum((o.total for o in orders if o.status != "cancelled"), start=0)
            return {
                "name": c.name, "email": c.email, "phone": c.phone, "total_orders": len(orders),
                "lifetime_value": svc.money(spent), "recent_order": orders[0].order_id if orders else None,
            }

    def process_refund(self, order_id: str, amount: float) -> Dict[str, Any]:
        with self._session() as db:
            try:
                ref = svc.refund(db, order_id, amount)
            except svc.StoreError as e:
                return {"order_id": str(order_id), "status": "failed", "error": str(e)}
            return {
                "refund_id": ref.refund_id, "order_id": ref.order_id, "amount_refunded": float(ref.amount),
                "status": ref.status,
                "processed_at": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat(),
            }

    def update_subscription(self, customer_email: str, action: str) -> Dict[str, Any]:
        return {"email": customer_email, "subscription_status": "unsupported",
                "error": "This store has no subscription products."}

    # ---- catalog -------------------------------------------------------
    def _product_for_bot(self, p: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "product_id": p["product_id"], "name": p["name"], "price": p["price"], "description": p["description"],
            "category": p["category"], "in_stock": p["in_stock"],
            "sizes_in_stock": [s for s, q in p["stock"].items() if q > 0],
            "link": f"{_store_url()}/product.html?id={p['product_id']}",
        }

    def recommend_product(self, context_keywords: str) -> List[Dict[str, Any]]:
        """Up to 2 in-stock products whose keywords overlap the conversation; falls back to a couple of
        general picks so the assistant always has something useful to suggest."""
        text = (context_keywords or "").lower()
        with self._session() as db:
            rows = db.execute(select(StoreProduct).where(StoreProduct.active.is_(True))).scalars().all()
            catalog = [(p, svc.product_to_dict(p)) for p in rows]
        available = [(p, d) for p, d in catalog if d["in_stock"]]
        scored = sorted(
            ((sum(1 for kw in (p.keywords or []) if kw in text), d) for p, d in available if any(kw in text for kw in (p.keywords or []))),
            key=lambda pair: pair[0], reverse=True,
        )
        picks = [d for _, d in scored[:2]]
        if not picks:
            by_id = {d["product_id"]: d for _, d in available}
            picks = [by_id[i] for i in _DEFAULT_RECOMMENDATIONS if i in by_id] or [d for _, d in available[:2]]
        return [self._product_for_bot(d) for d in picks]

    def get_product(self, product_id: str) -> Optional[Dict[str, Any]]:
        with self._session() as db:
            d = svc.get_product(db, product_id)
        return self._product_for_bot(d) if d else None

    def check_stock(self, product_id: str, size: Optional[str] = None) -> Dict[str, Any]:
        with self._session() as db:
            d = svc.get_product(db, product_id)
        if not d:
            return {"product_id": product_id, "found": False}
        if size:
            qty = d["stock"].get(size)
            return {"product_id": product_id, "found": True, "size": size, "available": bool(qty), "quantity": qty or 0}
        return {"product_id": product_id, "found": True, "stock": d["stock"], "in_stock": d["in_stock"]}

    def track_purchase(self, product_id: str) -> Dict[str, Any]:
        with self._session() as db:
            p = db.get(StoreProduct, product_id)
            price = float(p.price) if p else None
        if price is None:
            return {"success": False, "product_id": product_id, "revenue_generated": 0.00,
                    "error": "Unknown product_id — nothing was tracked."}
        return {"success": True, "product_id": product_id, "revenue_generated": price}
