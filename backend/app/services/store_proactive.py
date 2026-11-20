"""
The assistant speaking first.

1. Order events (shipped, delivered, delayed, cancelled) become messages queued for the customer. They are delivered into the
   customer's chat as soon as that chat is open - so a delay is announced by the assistant, not discovered by the customer.
2. Storefront nudges: when a visitor hesitates (a bag left sitting, the last units of a size, a sold-out product) the page
   asks the server to start the conversation. The message is written from the database, never from anything the browser sends.

Nothing here nags: one nudge per kind per session, three at most, at least 90 seconds apart, and never while a human agent
has taken over the conversation.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Conversation, Message
from app.db.session import SessionLocal
from app.db.store_models import StoreNudgeLog, StorePendingMessage, StoreProduct, StoreSessionContext
from app.services import store_service as svc

NUDGE_KINDS = ("bag_idle", "low_stock", "sold_out")
MAX_NUDGES, MIN_GAP = 3, datetime.timedelta(seconds=90)
PENDING_MAX_AGE = datetime.timedelta(days=7)
FRESH = datetime.timedelta(minutes=30)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _hi(db: Session, email: Optional[str]) -> str:
    c = svc.customer_by_email(db, email) if email else None
    return f"Hi {c.name.split()[0]}, " if c and c.name else ""


# ------------------------------------------------------------ order events
def order_event_text(db: Session, order, event: str, reason: Optional[str] = None) -> Optional[str]:
    hi, oid = _hi(db, order.email), order.order_id
    if event == "shipped":
        eta = f", estimated delivery {order.eta.strftime('%b %d')}" if order.eta else ""
        return f"{hi}good news: your order #{oid} has shipped with {order.carrier}. Tracking number {order.tracking_number}{eta}. I'm here if you need anything."
    if event == "delivered":
        return f"{hi}your order #{oid} was delivered. I hope you love it! If anything isn't right, I can help you start a return within our 30-day window."
    if event == "delayed":
        why = f" ({reason})" if reason else ""
        eta = f" The new estimated delivery is {order.eta.strftime('%b %d')}." if order.eta else ""
        return f"{hi}a quick update on order #{oid}: it's running late{why}.{eta} I'm sorry about the wait. Would you like me to flag it for the team?"
    if event == "cancelled":
        return f"{hi}your order #{oid} has been cancelled. If that wasn't expected, tell me and I'll bring in the team right away."
    return None


def queue_message(db: Session, email: str, kind: str, text: str) -> bool:
    email = (email or "").strip().lower()
    if not email or not text:
        return False
    dup = db.query(StorePendingMessage).filter_by(customer_email=email, kind=kind, text=text, delivered=False).first()
    if dup:
        return False
    db.add(StorePendingMessage(customer_email=email, kind=kind, text=text))
    db.commit()
    return True


# ---------------------------------------------------------------- delivery
async def push_ai_message(session_id: str, text: str) -> bool:
    """Save `text` as an AI message in the session's conversation, show it to the agents, and push it to the customer.
    Returns False (and does nothing) when the customer's chat is not connected or a human has taken over."""
    from app.realtime.connection_manager import manager
    if manager.get_customer_websocket(session_id) is None:
        return False

    def _save() -> Optional[str]:
        with SessionLocal() as db:
            conv = db.query(Conversation).filter_by(session_id=session_id).first()
            if not conv or conv.handoff_active:
                return None
            msg = Message(conversation_id=conv.id, sender="ai", content=text)
            db.add(msg)
            conv.updated_at = _now()
            db.commit()
            return msg.id

    mid = await asyncio.to_thread(_save)
    if mid is None:
        return False
    await manager.broadcast_to_agents({"type": "new_message", "session_id": session_id, "sender": "ai", "content": text, "is_resolved": False, "message_id": mid})
    await manager.send_to_customer(session_id, {"type": "new_message", "sender": "bot", "reply": text})
    return True


async def deliver_pending(session_id: str) -> int:
    """Hand any queued order messages to this chat session's customer (if they are signed in and connected)."""
    def _fetch():
        with SessionLocal() as db:
            conv = db.query(Conversation).filter_by(session_id=session_id).first()
            if not conv or not conv.customer_email or conv.handoff_active:
                return []
            rows = db.execute(select(StorePendingMessage).where(
                StorePendingMessage.customer_email == conv.customer_email.lower(), StorePendingMessage.delivered.is_(False),
                StorePendingMessage.created_at >= _now() - PENDING_MAX_AGE).order_by(StorePendingMessage.id).limit(3)).scalars().all()
            return [(r.id, r.text) for r in rows]

    sent = 0
    for rid, text in await asyncio.to_thread(_fetch):
        if not await push_ai_message(session_id, text):
            break
        def _mark(i=rid):
            with SessionLocal() as db:
                row = db.get(StorePendingMessage, i)
                if row:
                    row.delivered = True
                    db.commit()
        await asyncio.to_thread(_mark)
        sent += 1
    return sent


# ----------------------------------------------------------------- nudges
def build_nudge(db: Session, session_id: str, kind: str) -> Optional[str]:
    row = db.get(StoreSessionContext, session_id)
    if kind not in NUDGE_KINDS or not row or _now() - row.updated_at > FRESH:
        return None
    ctx = row.context or {}
    conv = db.query(Conversation).filter_by(session_id=session_id).first()
    hi = _hi(db, conv.customer_email if conv else None)
    product = db.get(StoreProduct, ctx["product_id"]) if ctx.get("product_id") else None
    if kind == "bag_idle" and ctx.get("cart"):
        first = db.get(StoreProduct, ctx["cart"][0]["product_id"])
        more = f" and {len(ctx['cart']) - 1} more" if len(ctx["cart"]) > 1 else ""
        if first:
            return (f"{hi}your bag is waiting: {first.name} ({ctx['cart'][0]['size']}){more}. Want help with sizing, delivery or returns before you check out? "
                    "I can also open checkout for you.")
    if kind == "low_stock" and product and ctx.get("size"):
        left = next((i.quantity for i in product.inventory if i.size == ctx["size"]), None)
        if left is not None and 0 < left <= svc.LOW_STOCK_AT:
            return f"{hi}quick heads-up: only {left} {product.name} left in size {ctx['size']}. Want me to add it to your bag so you don't lose it?"
    if kind == "sold_out" and product:
        d = svc.get_product(db, product.product_id)
        if d and not d["in_stock"]:
            alts = [p for p in svc.list_products(db, product.category) if p["in_stock"] and p["product_id"] != product.product_id][:2]
            tail = " Similar pieces in stock: " + ", ".join(a["name"] for a in alts) + ". Want me to show you?" if alts else ""
            return f"{hi}{product.name} is sold out in every size right now.{tail}"
    return None


async def send_nudge(session_id: str, kind: str) -> Dict[str, Any]:
    def _prepare() -> Optional[str]:
        with SessionLocal() as db:
            logs = db.query(StoreNudgeLog).filter_by(session_id=session_id).order_by(StoreNudgeLog.id).all()
            if len(logs) >= MAX_NUDGES or any(l.kind == kind for l in logs) or (logs and _now() - logs[-1].created_at < MIN_GAP):
                return None
            return build_nudge(db, session_id, kind)

    text = await asyncio.to_thread(_prepare)
    if not text:
        return {"sent": False, "reason": "not_applicable_or_limited"}
    if not await push_ai_message(session_id, text):
        return {"sent": False, "reason": "chat_closed"}

    def _log():
        with SessionLocal() as db:
            db.add(StoreNudgeLog(session_id=session_id, kind=kind))
            db.commit()
    await asyncio.to_thread(_log)
    return {"sent": True}


async def note_to_agents(session_id: str, text: str) -> None:
    """An internal note in the agent dashboard (also makes the dashboard re-read the order panel for that conversation)."""
    from app.realtime.connection_manager import manager
    await manager.broadcast_to_agents({"type": "new_message", "session_id": session_id, "sender": "agent_internal", "content": text,
                                       "is_resolved": False, "message_id": None})


async def announce_to_customer(email: str, text: str) -> int:
    """Tell a customer something in each of their recent chats that is open right now; agents see it as an AI message."""
    def _sessions():
        with SessionLocal() as db:
            rows = db.query(Conversation).filter(Conversation.customer_email == email.lower()).order_by(Conversation.updated_at.desc()).limit(5).all()
            return [c.session_id for c in rows]
    sent = 0
    for sid in await asyncio.to_thread(_sessions):
        if await push_ai_message(sid, text):
            await note_to_agents(sid, text)
            sent += 1
    return sent


async def link_session(session_id: str, email: str) -> str:
    """Stamp the customer's email on an existing chat session. Returns 'linked' (new), 'same' (already theirs) or 'conflict'."""
    email = email.lower()

    def _link() -> str:
        from app.realtime.websocket_routes import _sync_setup_conversation
        with SessionLocal() as db:
            conv = db.query(Conversation).filter_by(session_id=session_id).first()
            if conv and conv.customer_email:
                return "same" if conv.customer_email.lower() == email else "conflict"
            if conv:
                conv.customer_email = email
                db.commit()
                return "linked"
        _sync_setup_conversation(session_id, email)   # the chat has not written anything yet: create the conversation already linked
        return "linked"

    result = await asyncio.to_thread(_link)
    if result == "linked":
        def _name():
            with SessionLocal() as db:
                c = svc.customer_by_email(db, email)
                return c.name if c else email
        name = await asyncio.to_thread(_name)
        await note_to_agents(session_id, f"The customer signed in as {name} ({email}) during this chat.")
        hello = f"Thanks for signing in, {name.split()[0]}. I can see your account and orders now, so just tell me what you need."
        if not await push_ai_message(session_id, hello):   # chat window is closed right now: it is waiting when they open it
            def _queue():
                with SessionLocal() as db:
                    queue_message(db, email, "signed_in", hello)
            await asyncio.to_thread(_queue)
    try:
        from app.realtime.connection_manager import manager
        if manager.get_customer_websocket(session_id) is not None:
            manager._customer_emails[session_id] = email
            await manager.broadcast_to_agents({
                "type": "customer_presence",
                "session_id": session_id,
                "tenant_id": "default",
                "is_online": True,
                "email": email,
            })
    except Exception:
        pass

    return result
