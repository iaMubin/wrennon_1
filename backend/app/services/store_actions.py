"""
Chatbot actions on the storefront ("add this to my bag", "show me the boots").

The bot never touches the browser directly. A tool validates the request against the database and queues an action for
that chat session; the storefront page polls for its own session's actions (proved by the signed chat-session token) and
performs them. The bot can add to the bag and open pages. It cannot check out or take payment: that stays with the customer.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.db.store_models import StoreProduct, StoreUiAction
from app.services import store_service as svc

CATEGORIES = ("outerwear", "footwear", "essentials", "accessories")
_PAGES = {"bag": "cart.html", "cart": "cart.html", "checkout": "checkout.html", "account": "account.html",
          "orders": "track.html", "tracking": "track.html", "home": "index.html", "shop": "shop.html"}
MAX_PENDING = 20
EXPIRES = datetime.timedelta(minutes=10)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def resolve_product(db: Session, ref: str) -> Tuple[Optional[StoreProduct], List[StoreProduct]]:
    """Find a product by id or by (part of) its name. Returns (match, candidates) - candidates only when ambiguous."""
    ref = (ref or "").strip()
    if not ref:
        return None, []
    products = db.execute(select(StoreProduct).where(StoreProduct.active.is_(True))).scalars().all()
    low = ref.lower()
    for p in products:
        if p.product_id.lower() == low or p.name.lower() == low:
            return p, []
    words = [w for w in low.replace("-", " ").split() if len(w) > 2]
    hits = [p for p in products if low in p.name.lower() or (words and all(w in p.name.lower() for w in words))]
    if len(hits) == 1:
        return hits[0], []
    return None, hits


def queue_action(db: Session, session_id: str, type_: str, payload: Dict[str, Any]) -> StoreUiAction:
    pending = db.query(StoreUiAction).filter_by(session_id=session_id, delivered=False).count()
    if pending >= MAX_PENDING:
        raise svc.StoreError("too_many", "Too many pending actions for this chat.")
    row = StoreUiAction(session_id=session_id, type=type_, payload=payload)
    db.add(row)
    db.commit()
    return row


def pop_actions(db: Session, session_id: str) -> List[Dict[str, Any]]:
    """Actions waiting for this session, oldest first. Marked delivered as they are handed over."""
    cutoff = _now() - EXPIRES
    rows = db.execute(select(StoreUiAction).where(StoreUiAction.session_id == session_id, StoreUiAction.delivered.is_(False))
                      .order_by(StoreUiAction.id)).scalars().all()
    out = []
    for r in rows:
        r.delivered = True
        if r.created_at >= cutoff:
            out.append({"id": r.id, "type": r.type, "payload": r.payload})
    db.commit()
    return out


# ------------------------------------------------------------------ bot tools
def _add_to_bag(args: Dict[str, Any]) -> str:
    sid = args.get("_session_id")
    if not sid:
        return "This chat is not connected to the storefront, so you cannot change the customer's bag. Tell them how to add it themselves."
    with SessionLocal() as db:
        product, candidates = resolve_product(db, str(args.get("product") or args.get("product_id") or ""))
        if not product:
            if candidates:
                return "That matches several products: " + ", ".join(f"{p.name} ({p.product_id})" for p in candidates[:5]) + ". Ask the customer which one."
            return "No product matches that. Use recommend_product or ask the customer what they mean."
        sizes = list(product.sizes or [])
        size = str(args.get("size") or "").strip()
        if not size and len(sizes) == 1:
            size = sizes[0]
        size = next((s for s in sizes if s.lower() == size.lower()), None) if size else None
        if not size:
            return f"{product.name} comes in sizes {', '.join(sizes)}. Ask the customer which size they want before adding it."
        try:
            qty = max(1, min(5, int(args.get("quantity") or 1)))
        except (TypeError, ValueError):
            qty = 1
        have = next((i.quantity for i in product.inventory if i.size == size), 0)
        if have <= 0:
            others = [i.size for i in product.inventory if i.quantity > 0]
            return f"{product.name} in size {size} is sold out." + (f" Sizes still in stock: {', '.join(others)}." if others else " It is sold out in every size.")
        if have < qty:
            return f"Only {have} of {product.name} in size {size} are left, so {qty} cannot be added."
        queue_action(db, sid, "add_to_bag", {"product_id": product.product_id, "name": product.name, "size": size, "quantity": qty})
        return (f"Done: {qty} x {product.name} (size {size}, {svc.money(product.price)} each) was added to the customer's shopping bag on the website. "
                "They still have to check out themselves; you cannot complete a purchase or take payment.")


def _show_page(args: Dict[str, Any]) -> str:
    sid = args.get("_session_id")
    if not sid:
        return "This chat is not connected to the storefront, so you cannot open pages for the customer."
    dest = str(args.get("destination") or "").strip().lower()
    with SessionLocal() as db:
        if dest.startswith("product:"):
            product, candidates = resolve_product(db, dest.split(":", 1)[1])
            if not product:
                return ("That matches several products: " + ", ".join(p.name for p in candidates[:5]) + ". Ask which one.") if candidates else "No product matches that."
            url, label = f"product.html?id={product.product_id}", f"the {product.name} page"
        elif dest.startswith("category:") and dest.split(":", 1)[1].strip() in CATEGORIES:
            cat = dest.split(":", 1)[1].strip()
            url, label = f"shop.html?c={cat}", f"the {cat.title()} collection"
        elif dest in _PAGES:
            url, label = _PAGES[dest], f"the {dest} page"
        else:
            return "Unknown destination. Use product:<name>, category:<outerwear|footwear|essentials|accessories>, bag, checkout, account, orders or home."
        queue_action(db, sid, "navigate", {"url": url, "label": label})
    return f"Opened {label} for the customer on the website."


async def execute_add_to_bag(args: Dict[str, Any]) -> str:
    return await asyncio.to_thread(_add_to_bag, args)


async def execute_show_page(args: Dict[str, Any]) -> str:
    return await asyncio.to_thread(_show_page, args)
