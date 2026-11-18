"""
Live storefront context for the chatbot: which page the visitor is on, which product (and size) they are looking at,
and what is in their bag.

The browser only sends *identifiers* (page, product id, size, quantities). Names, prices and stock levels are always read
from the database here, and anything unknown is dropped, so a visitor cannot put free text (or instructions) in front of
the model through this channel.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.db.store_models import StoreProduct, StoreSessionContext
from app.services import store_service as svc

PAGES = {"home", "shop", "product", "cart", "checkout", "account", "order", "track"}
CATEGORIES = {"outerwear", "footwear", "essentials", "accessories"}
FRESH_FOR = datetime.timedelta(minutes=30)
_WHERE = {
    "home": "the home page", "cart": "their shopping bag page", "checkout": "the checkout page",
    "account": "their account page", "order": "an order confirmation page", "track": "the order-tracking page",
}


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def normalize(db: Session, raw: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"page": raw.get("page") if raw.get("page") in PAGES else "other"}
    if raw.get("category") in CATEGORIES:
        out["category"] = raw["category"]
    product = db.get(StoreProduct, raw["product_id"]) if isinstance(raw.get("product_id"), str) and len(raw["product_id"]) <= 32 else None
    if product and product.active:
        out["product_id"] = product.product_id
        if isinstance(raw.get("size"), str) and raw["size"] in (product.sizes or []):
            out["size"] = raw["size"]
    merged: Dict[tuple, int] = {}
    for line in (raw.get("cart") or [])[: svc.MAX_LINES]:
        try:
            pid, size, qty = str(line["product_id"]), str(line["size"]), int(line["quantity"])
        except (KeyError, TypeError, ValueError):
            continue
        p = db.get(StoreProduct, pid)
        if p and p.active and size in (p.sizes or []) and 1 <= qty <= svc.MAX_QTY:
            merged[(pid, size)] = min(svc.MAX_QTY, merged.get((pid, size), 0) + qty)
    out["cart"] = [{"product_id": k[0], "size": k[1], "quantity": q} for k, q in merged.items()]
    return out


def save_context(db: Session, session_id: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    ctx = normalize(db, raw)
    row = db.get(StoreSessionContext, session_id)
    if row:
        row.context, row.updated_at = ctx, _now()
    else:
        db.add(StoreSessionContext(session_id=session_id, context=ctx, updated_at=_now()))
    db.commit()
    return ctx


def render(db: Session, ctx: Dict[str, Any]) -> Optional[str]:
    lines: List[str] = []
    page = ctx.get("page", "other")
    product = svc.get_product(db, ctx["product_id"]) if ctx.get("product_id") else None
    if product and page == "product":
        stock = product["stock"]
        sizes = ", ".join(f"{s} ({q} left)" if 0 < q <= svc.LOW_STOCK_AT else (s if q > 0 else f"{s} (sold out)") for s, q in stock.items())
        sel = ctx.get("size")
        chosen = f" Selected size: {sel} ({stock.get(sel, 0)} in stock)." if sel else " No size selected yet."
        lines.append(f"- Page: the product page for {product['name']} ({product['product_id']}), {svc.money(product['price'])}.{chosen} Sizes: {sizes}.")
    elif page == "shop":
        lines.append(f"- Page: browsing {ctx['category'].title() if ctx.get('category') else 'all products'}.")
    elif page in _WHERE:
        lines.append(f"- Page: {_WHERE[page]}.")
    cart = []
    total = 0
    for line in ctx.get("cart", []):
        p = db.get(StoreProduct, line["product_id"])
        if p:
            cart.append(f"{p.name} ({line['size']}) x{line['quantity']} at {svc.money(p.price)}")
            total += p.price * line["quantity"]
    lines.append("- Bag: " + ("; ".join(cart) + f". Subtotal {svc.money(total)}." if cart else "empty."))
    if not lines:
        return None
    return ("Live storefront context (from the website; prices and stock from the database). Use it for 'this', 'it', 'my bag'; don't recite it.\n"
            + "\n".join(lines))


def page_context_for(session_id: str) -> Optional[str]:
    """Text for the planner/reply nodes, or None when there is no fresh context for this chat session."""
    with SessionLocal() as db:
        row = db.get(StoreSessionContext, session_id)
        if not row or _now() - row.updated_at > FRESH_FOR:
            return None
        return render(db, row.context or {})
