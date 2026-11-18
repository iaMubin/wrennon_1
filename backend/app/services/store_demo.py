"""
Presenter controls for live demos (never active unless you switch them on).

Set STORE_DEMO_MODE=1 (in backend/.env or the environment) and open the storefront with ?demo=1: a small "Demo" tab appears with
buttons that stage the story - switch customer, ship / delay / deliver an order, make a size run low, reset everything - so
nobody has to type commands in front of a client. With the setting off, every /api/store/demo/* URL answers 404.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db import store_models as m
from app.db.models import Conversation, Message, SystemSetting
from app.services import store_service as svc
from app.services.store_seed import DEMO_PEOPLE, seed_store

STORE_TABLES = (m.StorePendingMessage, m.StoreNudgeLog, m.StoreSessionContext, m.StoreUiAction, m.StoreRefund, m.StoreOrderEvent,
                m.StoreOrderItem, m.StoreOrder, m.StoreCustomer, m.StoreInventory, m.StoreProduct)
DEMO_EMAILS = {p.email for p in DEMO_PEOPLE}


def enabled() -> bool:
    from app.services.integrations import env_value
    return env_value("STORE_DEMO_MODE").strip().lower() in ("1", "true", "yes", "on")


def customers() -> List[Dict[str, str]]:
    return [{"name": p.name, "email": p.email, "city": p.city} for p in DEMO_PEOPLE]


def latest_order(db: Session, email: str, statuses: tuple) -> Optional[m.StoreOrder]:
    return next((o for o in svc.orders_for_email(db, email) if o.status in statuses), None)


def order_action(db: Session, email: str, action: str) -> Dict[str, Any]:
    """ship / delay / deliver the customer's most recent suitable order; the assistant announces it in their open chat."""
    rules = {"ship": (("processing",), "shipped"), "delay": (("processing", "shipped"), "delayed"), "deliver": (("shipped", "delayed"), "delivered")}
    if action not in rules:
        raise svc.StoreError("bad_action", "Unknown action.")
    statuses, target = rules[action]
    order = latest_order(db, email, statuses)
    if not order:
        raise svc.StoreError("no_order", f"No {' or '.join(statuses)} order to {action}. Create a test order first.")
    kw = {"delay_days": 4, "reason": "weather at the carrier hub"} if target == "delayed" else {}
    return svc.order_to_dict(svc.set_status(db, order.order_id, target, **kw), include_address=True)


def new_test_order(db: Session, email: str) -> Dict[str, Any]:
    c = svc.customer_by_email(db, email)
    order = svc.create_order(db, email=email, name=c.name if c else "Demo", address=(c and "") or "1 Demo St", city="Demo City", zip_code="00000",
                             items=[{"product_id": "WRN-TSH-301", "size": "M", "quantity": 1}, {"product_id": "WRN-ACC-501", "size": "One size", "quantity": 1}])
    return svc.order_to_dict(order, include_address=True)


def stock_preset(db: Session, preset: str) -> str:
    rows = lambda pid: db.query(m.StoreInventory).filter_by(product_id=pid).all()
    if preset == "low_parka_xl":
        for r in rows("WRN-JKT-201"):
            if r.size == "XL":
                r.quantity = 2
        msg = "Summit Parka XL: 2 left"
    elif preset == "sold_out_boots_12":
        for r in rows("WRN-BOOT-102"):
            if r.size == "12":
                r.quantity = 0
        msg = "Highland Boots size 12: sold out"
    elif preset == "restock":
        for r in db.query(m.StoreInventory).all():
            r.quantity = 15
        msg = "Everything restocked (15 each)"
    else:
        raise svc.StoreError("bad_preset", "Unknown stock preset.")
    db.commit()
    return msg


def reset(db: Session, chats: bool = False) -> Dict[str, Any]:
    removed = 0
    if chats:
        sessions = [r[0] for r in db.query(m.StoreSessionContext.session_id).all()]
        for c in db.query(Conversation).filter((Conversation.customer_email.in_(DEMO_EMAILS)) | (Conversation.session_id.in_(sessions))).all():
            try:
                db.query(Message).filter_by(conversation_id=c.id).delete()
                db.delete(c)
                db.commit()
                removed += 1
            except Exception:
                db.rollback()
    for table in STORE_TABLES:
        db.execute(delete(table))
    db.query(SystemSetting).filter(SystemSetting.key.in_(["store_history_seeded", "store_mock_dates_shifted"])).delete(synchronize_session=False)
    db.commit()
    return {"chats_removed": removed, **seed_store(db)}
