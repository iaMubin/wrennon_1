"""
Chatbot actions on the storefront ("add this to my bag", "show me the boots").

The bot never touches the browser directly. A tool validates the request against the database and queues an action for
that chat session; the storefront page polls for its own session's actions (proved by the signed chat-session token) and
performs them. The bot can add to the bag and open pages. It cannot check out or take payment: that stays with the customer.
"""

from __future__ import annotations

import asyncio
import datetime
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.db.store_models import StoreProduct, StoreUiAction
from app.services import store_context as ctx_svc
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


# ------------------------------------------------------------- bag and cancellation
def _get_my_bag(args: Dict[str, Any]) -> str:
    """What is in the visitor's bag right now (as last reported by their storefront page, prices from the database)."""
    sid = args.get("_session_id")
    if not sid:
        return "This chat is not connected to the storefront, so you cannot see the customer's bag. Ask them what they have in it."
    from app.db.store_models import StoreSessionContext
    with SessionLocal() as db:
        row = db.get(StoreSessionContext, sid)
        if (not row or _now() - row.updated_at > ctx_svc.FRESH_FOR) and args.get("_customer_email"):
            from app.db.models import Conversation   # a signed-in customer's bag follows them across their chats
            row = db.execute(select(StoreSessionContext).join(Conversation, Conversation.session_id == StoreSessionContext.session_id)
                             .where(Conversation.customer_email == str(args["_customer_email"]).lower())
                             .order_by(StoreSessionContext.updated_at.desc()).limit(1)).scalars().first()
        if not row or _now() - row.updated_at > ctx_svc.FRESH_FOR:
            return "The storefront has not reported this customer's bag recently. Ask them what they have in it."
        cart = (row.context or {}).get("cart") or []
        if not cart:
            return "The customer's shopping bag is empty."
        lines, total = [], 0
        for l in cart:
            p = db.get(StoreProduct, l["product_id"])
            if p:
                lines.append(f"{p.name} (size {l['size']}) x{l['quantity']} at {svc.money(p.price)} each")
                total += p.price * l["quantity"]
        return "The customer's bag: " + "; ".join(lines) + f". Subtotal {svc.money(total)}."


def _cancel_order(args: Dict[str, Any]):
    """Returns (text_for_the_bot, cancelled_order_id_or_None). Two steps: first call asks the bot to get the customer's
    confirmation; only a second call with confirmed=true cancels."""
    oid = svc.clean_order_id(args.get("order_id"))
    if not oid:
        return "Ask the customer which order number they want to cancel.", None
    trusted = {str(e).lower() for e in ([args.get("_customer_email")] + list(args.get("_claimed_emails") or [])) if e}
    with SessionLocal() as db:
        order = svc.get_order(db, oid)
        if not order or order.email.lower() not in trusted:
            return "No order found matching that order number and email. Do not reveal whether the order number exists.", None
        if order.status == "cancelled":
            return f"Order #{oid} is already cancelled.", None
        if order.status != "processing":
            return (f"Order #{oid} is {order.status}, so it can no longer be cancelled. Tell the customer, and offer a return once it arrives "
                    "(30-day return window)."), None
        confirmed = args.get("confirmed")
        if not (confirmed is True or str(confirmed).lower() == "true"):
            what = ", ".join(f"{i.name} ({i.size}) x{i.quantity}" for i in order.items)
            return (f"NOT cancelled yet. First ask the customer to confirm: cancel order #{oid} ({what}; total {svc.money(order.total)})? "
                    "Only after they clearly say yes, call cancel_order again with confirmed=true."), None
        svc.cancel_order(db, oid, email=order.email)
        return (f"Order #{oid} has been cancelled: the payment is voided and the items are back in stock. "
                "Tell the customer it is done and mention the order number."), oid


def _queue_refresh(session_id: str) -> None:
    """Tell the customer's open page that one of their orders just changed (the account page re-reads it)."""
    with SessionLocal() as db:
        queue_action(db, session_id, "refresh", {"what": "orders"})


async def execute_get_my_bag(args: Dict[str, Any]) -> str:
    return await asyncio.to_thread(_get_my_bag, args)


async def execute_cancel_order(args: Dict[str, Any]) -> str:
    text, cancelled = await asyncio.to_thread(_cancel_order, args)
    text = _flag(text, bool(cancelled))
    if cancelled and args.get("_session_id"):
        from app.services import store_proactive
        await store_proactive.note_to_agents(args["_session_id"], f"Order #{cancelled} was cancelled by the customer through the AI assistant.")
        await asyncio.to_thread(_queue_refresh, args["_session_id"])
    return text


# --------------------------------------------------- changing address / size (same safeguards as cancelling)
def _trusted(args: Dict[str, Any]) -> set:
    return {str(e).lower() for e in ([args.get("_customer_email")] + list(args.get("_claimed_emails") or [])) if e}


def _is_yes(v: Any) -> bool:
    return v is True or str(v).lower() == "true"


def split_address(address: str, city: str = "", zip_code: str = "") -> tuple:
    """The model sometimes puts the whole address in one field ("77 Elm Ave, Seattle WA 98103"). Pull the ZIP and city back out."""
    address, city, zip_code = (address or "").strip(), (city or "").strip(), (zip_code or "").strip()
    if address and not zip_code:
        m = re.search(r"\b\d{5}(?:-\d{4})?\b", address)
        if m:
            zip_code, address = m.group(0), (address[:m.start()] + address[m.end():]).strip(" ,")
    if address and not city:
        parts = [x.strip() for x in address.split(",") if x.strip()]
        if len(parts) >= 2:
            address, city = parts[0], ", ".join(parts[1:])
    return address, city, zip_code


def _change_address(args: Dict[str, Any]):
    """(text_for_the_bot, changed_order_id_or_None). First call asks for confirmation; only confirmed=true changes anything."""
    oid = svc.clean_order_id(args.get("order_id"))
    address, city, zip_code = split_address(str(args.get("address") or args.get("new_address") or ""), str(args.get("city") or ""),
                                            str(args.get("zip") or args.get("zip_code") or args.get("postal_code") or ""))
    if not oid:
        return "Ask the customer which order number they want to change.", None
    if not (address and city and zip_code):
        return "Ask the customer for the complete new delivery address: street address, city and ZIP/postal code.", None
    if not re.search(r"\d", address):
        return "That does not look like a street address (it needs a number and a street name). Ask the customer for it.", None
    with SessionLocal() as db:
        order = svc.get_order(db, oid)
        if not order or order.email.lower() not in _trusted(args):
            return "No order found matching that order number and email. Do not reveal whether the order number exists.", None
        if order.status != "processing":
            return (f"Order #{oid} is {order.status}, so its address can no longer be changed here. Explain that, and offer to bring in a human "
                    "agent who can ask the carrier to re-route it."), None
        if not _is_yes(args.get("confirmed")):
            return (f"NOT changed yet. Read the new address back and ask the customer to confirm: send order #{oid} to {address}, {city} {zip_code}? "
                    "Only after a clear yes, call change_order_address again with confirmed=true and the same address."), None
        try:
            svc.update_order_address(db, oid, email=order.email, address=address, city=city, zip_code=zip_code)
        except svc.StoreError as e:
            return str(e), None
        return f"Order #{oid} will now be delivered to {address}, {city} {zip_code}. Tell the customer it is done.", f"Order #{oid} delivery address changed to {address}, {city} {zip_code}"


def _change_size(args: Dict[str, Any]):
    oid = svc.clean_order_id(args.get("order_id"))
    new_size = str(args.get("new_size") or args.get("size") or "").strip()
    if not oid:
        return "Ask the customer which order number they want to change.", None
    with SessionLocal() as db:
        order = svc.get_order(db, oid)
        if not order or order.email.lower() not in _trusted(args):
            return "No order found matching that order number and email. Do not reveal whether the order number exists.", None
        if order.status != "processing":
            return f"Order #{oid} is {order.status}, so items can no longer be swapped. Offer a return once it arrives (30-day window).", None
        if not new_size:
            return "Ask the customer which size they want instead.", None
        product = str(args.get("product") or "").strip() or None
        if not _is_yes(args.get("confirmed")):
            try:   # a dry run of the same rules, so the bot only asks for confirmation of something that can really happen
                items = [i for i in order.items if not product or product.lower() in i.name.lower() or product.lower() == (i.product_id or "").lower()]
                if len(items) != 1:
                    return "Which item should change size? " + ", ".join(i.name for i in order.items) + ". Ask the customer.", None
                it = items[0]
                prod = db.get(StoreProduct, it.product_id)
                size = next((x for x in (prod.sizes if prod else []) if x.lower() == new_size.lower()), None)
                if not size:
                    return f"{it.name} comes in sizes {', '.join(prod.sizes) if prod else 'n/a'}. Ask the customer to pick one of those.", None
                if size == it.size:
                    return f"{it.name} is already size {size}.", None
                have = next((r.quantity for r in prod.inventory if r.size == size), 0)
                if have < it.quantity:
                    return f"{it.name} in size {size} is sold out or too low in stock. Tell the customer and offer another size.", None
                return (f"NOT changed yet. Ask the customer to confirm: change {it.name} in order #{oid} from size {it.size} to {size}? Only after a clear yes, "
                        "call change_order_size again with confirmed=true."), None
            except Exception:
                return "That change can't be made. Ask the customer to double-check the order and item.", None
        try:
            changed = svc.change_order_size(db, oid, email=order.email, new_size=new_size, product=product)
        except svc.StoreError as e:
            return str(e) + " Tell the customer plainly that nothing was changed.", None
        last = changed.events[-1].label
        return f"Done. {last} on order #{oid}. Tell the customer it is changed.", f"Order #{oid}: {last}"


def _flag(text: str, done: bool) -> str:
    """A result that changed nothing must say so, in words the model cannot misread as success."""
    return text if done or text.startswith("NOT") else "NOT DONE: " + text


async def execute_change_order_address(args: Dict[str, Any]) -> str:
    text, note = await asyncio.to_thread(_change_address, args)
    text = _flag(text, bool(note))
    if note and args.get("_session_id"):
        from app.services import store_proactive
        await store_proactive.note_to_agents(args["_session_id"], note + " (by the customer, through the AI assistant).")
        await asyncio.to_thread(_queue_refresh, args["_session_id"])
    return text


async def execute_change_order_size(args: Dict[str, Any]) -> str:
    text, note = await asyncio.to_thread(_change_size, args)
    text = _flag(text, bool(note))
    if note and args.get("_session_id"):
        from app.services import store_proactive
        await store_proactive.note_to_agents(args["_session_id"], note + " (by the customer, through the AI assistant).")
        await asyncio.to_thread(_queue_refresh, args["_session_id"])
    return text


def _add_item_to_order(args: Dict[str, Any]):
    oid = svc.clean_order_id(args.get("order_id"))
    if not oid:
        return "Ask the customer which order number they want to add an item to.", None
    with SessionLocal() as db:
        order = svc.get_order(db, oid)
        if not order or order.email.lower() not in _trusted(args):
            return "No order found matching that order number and email. Do not reveal whether the order number exists.", None
        if order.status != "processing":
            return f"Order #{oid} is {order.status}, so items can no longer be added to it. Offer to put the item in a new order (add it to their bag).", None
        product, candidates = resolve_product(db, str(args.get("product") or ""))
        if not product:
            return ("That matches several products: " + ", ".join(p.name for p in candidates[:5]) + ". Ask which one.") if candidates else "No product matches that. Ask the customer what they want to add.", None
        sizes = list(product.sizes or [])
        size = str(args.get("size") or "").strip() or (sizes[0] if len(sizes) == 1 else "")
        size = next((x for x in sizes if x.lower() == size.lower()), None) if size else None
        if not size:
            return f"{product.name} comes in sizes {', '.join(sizes)}. Ask the customer which size.", None
        try:
            qty = max(1, min(5, int(args.get("quantity") or 1)))
        except (TypeError, ValueError):
            qty = 1
        have = next((r.quantity for r in product.inventory if r.size == size), 0)
        if have < qty:
            return f"{product.name} in size {size} " + ("is sold out." if have <= 0 else f"only has {have} left.") + " Tell the customer and offer another size.", None
        if not _is_yes(args.get("confirmed")):
            new_total = order.subtotal + product.price * qty + order.shipping_cost
            return (f"NOT added yet. Ask the customer to confirm: add {qty} x {product.name} (size {size}, {svc.money(product.price)} each) to order #{oid}? "
                    f"The order total would change from {svc.money(order.total)} to about {svc.money(new_total)}. Only after a clear yes, call add_item_to_order again with confirmed=true."), None
        try:
            changed = svc.add_order_item(db, oid, email=order.email, product_id=product.product_id, size=size, quantity=qty)
        except svc.StoreError as e:
            return str(e) + " Tell the customer plainly that nothing was changed.", None
        return (f"Done. Added {qty} x {product.name} (size {size}) to order #{oid}; the new total is {svc.money(changed.total)}. Tell the customer it is done."), \
            f"Order #{oid}: {changed.events[-1].label}"


def _reorder(args: Dict[str, Any]):
    """Put the items of a past order back into the signed-in customer's bag (stock permitting)."""
    sid, email = args.get("_session_id"), args.get("_customer_email")
    if not email:
        return "The customer is not signed in, so you cannot reorder for them. Ask them to sign in first.", 0
    if not sid:
        return "This chat is not connected to the storefront, so you cannot change the customer's bag.", 0
    with SessionLocal() as db:
        oid = svc.clean_order_id(args.get("order_id"))
        order = svc.get_order(db, oid, email=email) if oid else next((o for o in svc.orders_for_email(db, email) if o.status != "cancelled"), None)
        if not order:
            return "No matching order found for this customer." if oid else "This customer has no past orders to reorder.", 0
        added, missing = [], []
        for it in order.items:
            product = db.get(StoreProduct, it.product_id) if it.product_id else None
            have = next((r.quantity for r in product.inventory if r.size == it.size), 0) if product and product.active else 0
            if have >= it.quantity:
                queue_action(db, sid, "add_to_bag", {"product_id": product.product_id, "name": product.name, "size": it.size, "quantity": it.quantity})
                added.append(f"{it.quantity} x {product.name} (size {it.size})")
            else:
                alt = [r.size for r in product.inventory if r.quantity >= it.quantity] if product and product.active else []
                missing.append(f"{it.name} (size {it.size})" + (f" is not available; sizes in stock: {', '.join(alt)}" if alt else " is sold out"))
        parts = []
        if added:
            parts.append(f"Added to the customer's bag from order #{order.order_id}: " + "; ".join(added) + ".")
        if missing:
            parts.append("Could not add: " + "; ".join(missing) + ". Offer alternatives.")
        parts.append("They still have to check out themselves; you cannot take payment.")
        return " ".join(parts), len(added)


async def execute_add_item_to_order(args: Dict[str, Any]) -> str:
    text, note = await asyncio.to_thread(_add_item_to_order, args)
    text = _flag(text, bool(note))
    if note and args.get("_session_id"):
        from app.services import store_proactive
        await store_proactive.note_to_agents(args["_session_id"], note + " (by the customer, through the AI assistant).")
        await asyncio.to_thread(_queue_refresh, args["_session_id"])
    return text


async def execute_reorder(args: Dict[str, Any]) -> str:
    return (await asyncio.to_thread(_reorder, args))[0]


# ----------------------------------------------------------------- "complete the look"
# Hand-picked outfit pairings (product id -> pieces that go with it, with the reason shown to the customer).
LOOKS: Dict[str, List[tuple]] = {
    "WRN-JKT-201": [("WRN-ACC-501", "warm hat for the same cold days"), ("WRN-BOOT-102", "weatherproof boots to match"), ("WRN-HOD-302", "a warm layer underneath")],
    "WRN-JKT-202": [("WRN-TSH-301", "a clean tee underneath"), ("WRN-PNT-401", "chinos that dress it up"), ("WRN-SHO-101", "everyday sneakers")],
    "WRN-BOOT-102": [("WRN-JKT-201", "the parka built for the same weather"), ("WRN-PNT-401", "chinos that sit well over boots"), ("WRN-ACC-501", "a wool beanie")],
    "WRN-SHO-101": [("WRN-TSH-301", "an easy tee"), ("WRN-PNT-401", "chinos for city days"), ("WRN-ACC-502", "a weekender for the trip")],
    "WRN-HOD-302": [("WRN-JKT-201", "a shell for the cold"), ("WRN-PNT-401", "chinos"), ("WRN-SHO-101", "sneakers")],
    "WRN-TSH-301": [("WRN-JKT-202", "a jacket to layer over it"), ("WRN-PNT-401", "chinos"), ("WRN-SHO-101", "sneakers")],
    "WRN-PNT-401": [("WRN-TSH-301", "a simple tee"), ("WRN-JKT-202", "a denim jacket"), ("WRN-BOOT-102", "boots")],
    "WRN-ACC-501": [("WRN-JKT-201", "the parka it was made to go with"), ("WRN-HOD-302", "a cosy hoodie"), ("WRN-BOOT-102", "boots")],
    "WRN-ACC-502": [("WRN-SHO-101", "sneakers for the trip"), ("WRN-HOD-302", "a hoodie for the journey"), ("WRN-JKT-202", "a light jacket")],
}


def _complete_the_look(args: Dict[str, Any]):
    """(text_for_the_bot, ids_shown). Also puts a card with the pieces on the customer's screen."""
    sid = args.get("_session_id")
    with SessionLocal() as db:
        anchor = None
        ref = str(args.get("product") or "").strip()
        if ref:
            anchor, candidates = resolve_product(db, ref)
            if not anchor:
                return (("That matches several products: " + ", ".join(p.name for p in candidates[:5]) + ". Ask which one.") if candidates else "No product matches that."), []
        elif sid:
            from app.db.store_models import StoreSessionContext
            row = db.get(StoreSessionContext, sid)
            ctx = (row.context or {}) if row and _now() - row.updated_at <= ctx_svc.FRESH_FOR else {}
            pid = ctx.get("product_id") or (ctx.get("cart") or [{}])[0].get("product_id")
            anchor = db.get(StoreProduct, pid) if pid else None
        if not anchor:
            return "Ask the customer which item they want an outfit built around.", []
        picks = []
        for pid, why in LOOKS.get(anchor.product_id, []):
            p = db.get(StoreProduct, pid)
            if p and p.active:
                sizes = [r.size for r in p.inventory if r.quantity > 0]
                if sizes:
                    picks.append((p, sizes, why))
        if not picks:
            return f"No in-stock pieces to pair with {anchor.name} right now.", []
        total = sum(p.price for p, _, _ in picks)
        lines = [f"{p.name} ({svc.money(p.price)}; {'one size' if len(sz) == 1 and sz[0].lower() == 'one size' else 'sizes in stock: ' + ', '.join(sz)}) - {why}" for p, sz, why in picks]
        if sid:
            queue_action(db, sid, "look", {"anchor": anchor.name, "items": [p.product_id for p, _, _ in picks]})
        text = (f"Pieces that go with {anchor.name}: " + "; ".join(lines) + f". All together: {svc.money(total)}. "
                "A card showing the look is now on the customer's screen where they pick sizes and add everything in one tap; "
                "tell them that, and offer to add pieces by name if they give you their sizes.")
        return text, [p.product_id for p, _, _ in picks]


async def execute_complete_the_look(args: Dict[str, Any]) -> str:
    return (await asyncio.to_thread(_complete_the_look, args))[0]
