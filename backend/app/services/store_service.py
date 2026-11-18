"""
Business logic for the storefront database. The REST API (app/api/store.py) and the
chatbot's EcommerceProvider (integrations/store_db.py) both go through here, so the
website and the bot can never disagree about a price, a stock level or an order.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import Integer, cast, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.store_models import (
    StoreCustomer, StoreInventory, StoreOrder, StoreOrderEvent, StoreOrderItem, StoreProduct, StoreRefund,
)

# --- Store policy knobs. Set these to match your knowledge-base policy. ---
SHIPPING_FLAT = Decimal("0.00")   # shipping charged on every new order
TAX_RATE = Decimal("0")           # e.g. Decimal("0.08") for 8%
LOW_STOCK_AT = 3                  # "only N left" threshold shown on the website
MAX_LINES, MAX_QTY = 20, 10

LABELS = {
    "placed": "Order Placed", "processing": "Processing", "shipped": "Shipped", "delivered": "Delivered",
    "cancelled": "Cancelled", "delayed": "Delayed", "refunded": "Refunded", "partially_refunded": "Partially Refunded",
}
STATUSES = ("processing", "shipped", "delivered", "delayed", "cancelled")


_TRACK_URL = {
    "FedEx": "https://www.fedex.com/fedextrack/?trknbr={n}",
    "UPS": "https://www.ups.com/track?tracknum={n}",
    "USPS": "https://tools.usps.com/go/TrackConfirmAction?tLabels={n}",
    "DHL": "https://www.dhl.com/us-en/home/tracking/tracking-express.html?submit=1&tracking-id={n}",
}


def make_tracking(carrier: str, rng=None):
    """(tracking_number, tracking_url) in the carrier's real format."""
    import random
    r = rng or random
    if carrier == "UPS":
        n = "1Z" + "".join(r.choices("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789", k=6)) + f"{r.randint(0, 99):02d}{r.randint(0, 10**8 - 1):08d}"
    elif carrier == "USPS":
        n = "9400" + f"{r.randint(0, 10**18 - 1):018d}"
    elif carrier == "DHL":
        n = str(r.randint(10**9, 10**10 - 1))
    else:
        n = str(r.randint(10**11, 10**12 - 1))
    return n, _TRACK_URL.get(carrier, _TRACK_URL["FedEx"]).format(n=n)


class StoreError(Exception):
    """Business-rule failure. `code` is machine-readable; str(e) is safe to show a customer."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def money(value: Any, currency: str = "USD") -> str:
    symbol = "$" if currency == "USD" else f"{currency} "
    return f"{symbol}{Decimal(value):,.2f}"


def clean_order_id(value: Any) -> str:
    return str(value or "").strip().lstrip("#").strip()


def _iso(dt: Optional[datetime.datetime]) -> Optional[str]:
    return dt.replace(microsecond=0).isoformat() + "Z" if dt else None


# ---------------------------------------------------------------- catalog
def product_to_dict(p: StoreProduct) -> Dict[str, Any]:
    stock = {row.size: row.quantity for row in p.inventory}
    total = sum(stock.values())
    return {
        "product_id": p.product_id, "name": p.name, "category": p.category, "description": p.description,
        "price": float(p.price), "currency": p.currency, "sizes": list(p.sizes or []), "details": list(p.details or []),
        "featured": bool(p.featured), "stock": stock, "in_stock": total > 0,
        "low_stock": 0 < total <= LOW_STOCK_AT,
    }


def list_products(db: Session, category: Optional[str] = None) -> List[Dict[str, Any]]:
    q = select(StoreProduct).where(StoreProduct.active.is_(True))
    if category:
        q = q.where(StoreProduct.category == category)
    rows = db.execute(q.order_by(StoreProduct.featured.desc(), StoreProduct.name)).scalars().all()
    return [product_to_dict(p) for p in rows]


def get_product(db: Session, product_id: str) -> Optional[Dict[str, Any]]:
    p = db.get(StoreProduct, product_id)
    return product_to_dict(p) if p and p.active else None


# ----------------------------------------------------------------- orders
def order_to_dict(o: StoreOrder, include_email: bool = False, include_address: bool = False) -> Dict[str, Any]:
    refunded = sum((r.amount for r in o.refunds if r.status == "approved"), Decimal("0"))
    d: Dict[str, Any] = {
        "order_id": o.order_id,
        "status": o.status,
        "order_date": o.created_at.date().isoformat() if o.created_at else None,
        "total_amount": money(o.total, o.currency),
        "subtotal": money(o.subtotal, o.currency),
        "shipping_cost": money(o.shipping_cost, o.currency),
        "payment_method": o.payment_method,
        "payment_status": o.payment_status,
        "shipping_method": o.shipping_method,
        "carrier": o.carrier,
        "tracking_number": o.tracking_number,
        "tracking_url": o.tracking_url,
        "eta": o.eta.isoformat() if o.eta else None,
        "items_count": sum(i.quantity for i in o.items),
        "items": [
            {"product_id": i.product_id, "name": i.name, "size": i.size, "quantity": i.quantity,
             "unit_price": money(i.unit_price, o.currency)} for i in o.items
        ],
        "timeline": [{"status": e.status, "time": _iso(e.occurred_at), "label": e.label} for e in o.events],
    }
    if refunded > 0:
        d["refunded_amount"] = money(refunded, o.currency)
    if include_address:
        d["ship_to"] = ", ".join(x for x in (o.ship_address, f"{o.ship_city} {o.ship_zip}".strip()) if x)
    if include_email:
        d["email"] = o.email
        d["customer_name"] = o.customer_name
    return d


def get_order(db: Session, order_id: Any, email: Optional[str] = None) -> Optional[StoreOrder]:
    """Fetch an order. If `email` is given it must match, otherwise None — identical to 'not found'
    so callers cannot probe which order numbers exist."""
    order = db.get(StoreOrder, clean_order_id(order_id))
    if not order:
        return None
    if email is not None and order.email.lower() != email.strip().lower():
        return None
    return order


def latest_order_for_email(db: Session, email: str) -> Optional[StoreOrder]:
    return db.execute(
        select(StoreOrder).where(StoreOrder.email == (email or "").strip().lower())
        .order_by(StoreOrder.created_at.desc(), StoreOrder.order_id.desc()).limit(1)
    ).scalars().first()


def add_event(order: StoreOrder, status: str, when: Optional[datetime.datetime] = None) -> None:
    order.events.append(StoreOrderEvent(status=status, label=LABELS.get(status, status.title()), occurred_at=when or _now()))


def _next_order_id(db: Session) -> str:
    current = db.execute(select(func.max(cast(StoreOrder.order_id, Integer)))).scalar()
    return str(max(int(current or 0), 1000) + 1)


def create_order(db: Session, *, email: str, name: str, address: str, city: str, zip_code: str,
                 items: List[Dict[str, Any]], phone: Optional[str] = None, country: Optional[str] = None) -> StoreOrder:
    """Create an order atomically. Prices always come from the database (never from the client),
    and stock is decremented with a conditional UPDATE so two buyers can't take the last unit."""
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise StoreError("invalid_email", "A valid email address is required.")
    if not items or len(items) > MAX_LINES:
        raise StoreError("invalid_items", "Your bag is empty or has too many lines.")

    merged: Dict[tuple, int] = {}
    for it in items:
        qty = int(it.get("quantity") or 0)
        if qty < 1 or qty > MAX_QTY:
            raise StoreError("invalid_quantity", f"Quantity must be between 1 and {MAX_QTY}.")
        key = (str(it.get("product_id") or ""), str(it.get("size") or ""))
        merged[key] = merged.get(key, 0) + qty

    for _attempt in range(5):
        try:
            subtotal = Decimal("0")
            lines: List[StoreOrderItem] = []
            for (pid, size), qty in merged.items():
                product = db.get(StoreProduct, pid)
                if not product or not product.active:
                    raise StoreError("unknown_product", "One of the items is no longer available.")
                if size not in (product.sizes or []):
                    raise StoreError("invalid_size", f"{product.name}: please choose a valid size.")
                res = db.execute(
                    update(StoreInventory)
                    .where(StoreInventory.product_id == pid, StoreInventory.size == size, StoreInventory.quantity >= qty)
                    .values(quantity=StoreInventory.quantity - qty)
                )
                if res.rowcount != 1:
                    raise StoreError("out_of_stock", f"Sorry, {product.name} in size {size} doesn't have enough stock left.")
                subtotal += product.price * qty
                lines.append(StoreOrderItem(product_id=pid, name=product.name, size=size, quantity=qty, unit_price=product.price))

            shipping = SHIPPING_FLAT
            tax = (subtotal * TAX_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            customer = db.execute(select(StoreCustomer).where(StoreCustomer.email == email)).scalars().first()
            if not customer:
                customer = StoreCustomer(email=email, name=name.strip(), phone=(phone or None))
                db.add(customer)
                db.flush()
            order = StoreOrder(
                order_id=_next_order_id(db), customer_id=customer.id, email=email, customer_name=name.strip(),
                phone=phone or None, ship_address=address.strip(), ship_city=city.strip(), ship_zip=zip_code.strip(),
                ship_country=country, status="processing", payment_status="paid", payment_method="Demo checkout",
                shipping_method="Standard Delivery", subtotal=subtotal, shipping_cost=shipping, tax=tax,
                total=subtotal + shipping + tax, currency="USD", items=lines,
            )
            add_event(order, "placed")
            db.add(order)
            db.commit()
            return order
        except IntegrityError:  # two orders picked the same number at once: retry with the next one
            db.rollback()
        except StoreError:
            db.rollback()
            raise
    raise StoreError("busy", "We couldn't place the order right now. Please try again.")


def set_status(db: Session, order_id: Any, status: str, *, carrier: Optional[str] = None,
               tracking_number: Optional[str] = None, tracking_url: Optional[str] = None,
               eta: Optional[datetime.date] = None, delay_days: int = 3, reason: Optional[str] = None) -> StoreOrder:
    """Move an order through its lifecycle (what a warehouse/carrier webhook would do)."""
    if status not in STATUSES:
        raise StoreError("invalid_status", f"Status must be one of: {', '.join(STATUSES)}.")
    order = get_order(db, order_id)
    if not order:
        raise StoreError("not_found", "Order not found.")
    order.status = status
    if status == "shipped":
        order.carrier = carrier or order.carrier or "FedEx"
        auto_no, auto_url = make_tracking(order.carrier)
        order.tracking_number = tracking_number or order.tracking_number or auto_no
        order.tracking_url = tracking_url or order.tracking_url or (_TRACK_URL.get(order.carrier, _TRACK_URL["FedEx"]).format(n=order.tracking_number) if tracking_number or order.tracking_number else auto_url)
        order.eta = eta or order.eta or (_now() + datetime.timedelta(days=4)).date()
    if status == "delayed":
        order.eta = eta or ((order.eta or _now().date()) + datetime.timedelta(days=delay_days))
    if status == "delivered":
        order.eta = None
    if status == "cancelled":
        order.payment_status = "voided"
    add_event(order, status)
    db.commit()
    if status in ("shipped", "delivered", "delayed", "cancelled"):   # the assistant tells the customer in their chat
        from app.services import store_proactive
        text = store_proactive.order_event_text(db, order, status, reason)
        if text:
            store_proactive.queue_message(db, order.email, f"order_{status}", text)
    return order


def refund(db: Session, order_id: Any, amount: float, reason: Optional[str] = None) -> StoreRefund:
    order = get_order(db, order_id)
    if not order:
        raise StoreError("not_found", "Order not found.")
    amt = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    already = sum((r.amount for r in order.refunds if r.status == "approved"), Decimal("0"))
    if amt <= 0 or amt > order.total - already:
        raise StoreError("invalid_amount", f"Refund must be more than 0 and at most {money(order.total - already, order.currency)}.")
    ref = StoreRefund(refund_id=f"REF-{uuid.uuid4().hex[:6].upper()}", order_id=order.order_id, amount=amt, reason=reason, status="approved")
    order.refunds.append(ref)
    full = already + amt >= order.total
    order.payment_status = "refunded" if full else "partially_refunded"
    add_event(order, "refunded" if full else "partially_refunded")
    db.commit()
    return ref


# -------------------------------------------------------------- customers
TIERS = ((Decimal("1200"), "Platinum"), (Decimal("600"), "Gold"), (Decimal("200"), "Silver"), (Decimal("0"), "Bronze"))


def customer_by_email(db: Session, email: str) -> Optional[StoreCustomer]:
    return db.execute(select(StoreCustomer).where(StoreCustomer.email == (email or "").strip().lower())).scalars().first()


def orders_for_email(db: Session, email: str) -> List[StoreOrder]:
    return list(db.execute(
        select(StoreOrder).where(StoreOrder.email == (email or "").strip().lower())
        .order_by(StoreOrder.created_at.desc(), StoreOrder.order_id.desc())
    ).scalars().all())


def customer_profile(db: Session, c: StoreCustomer) -> Dict[str, Any]:
    """What an agent (or the account page) wants to know about a customer at a glance."""
    orders = orders_for_email(db, c.email)
    spent = Decimal("0")
    for o in orders:
        if o.status == "cancelled":
            continue
        spent += o.total - sum((r.amount for r in o.refunds if r.status == "approved"), Decimal("0"))
    tier = next(name for floor, name in TIERS if spent >= floor)
    return {
        "id": f"CUST-{1000 + c.id}", "name": c.name, "email": c.email, "phone": c.phone,
        "member_since": c.created_at.date().isoformat() if c.created_at else None,
        "total_orders": len(orders), "lifetime_value": money(spent), "loyalty_tier": tier,
        "tags": ["VIP"] if tier == "Platinum" else [], "recent_order": orders[0].order_id if orders else None,
        "has_account": bool(c.password_hash),
    }


def register_customer(db: Session, *, name: str, email: str, password_hash: str) -> StoreCustomer:
    email = email.strip().lower()
    if customer_by_email(db, email):
        # Never claim an existing record (it may hold someone's order history); this also hides which emails shop here.
        raise StoreError("account_exists", "We couldn't create that account. If you already have one, please sign in.")
    c = StoreCustomer(email=email, name=name.strip(), password_hash=password_hash, last_login_at=_now())
    db.add(c)
    db.commit()
    return c


def mark_login(db: Session, c: StoreCustomer) -> None:
    c.last_login_at = _now()
    db.commit()


def cancel_order(db: Session, order_id: Any, email: Optional[str] = None) -> StoreOrder:
    """Cancel an order that has not shipped. Puts the stock back, voids the payment and records the event.
    If `email` is given it must be the order's owner (same answer as 'not found' otherwise)."""
    order = get_order(db, order_id, email=email)
    if not order:
        raise StoreError("not_found", "Order not found.")
    if order.status == "cancelled":
        raise StoreError("already_cancelled", f"Order #{order.order_id} is already cancelled.")
    if order.status != "processing":
        raise StoreError("not_cancellable", f"Order #{order.order_id} is {order.status}, so it can no longer be cancelled. "
                         "You can return it once it arrives (30-day return window).")
    for item in order.items:   # put the stock back
        row = db.execute(select(StoreInventory).where(StoreInventory.product_id == item.product_id, StoreInventory.size == item.size)).scalars().first()
        if row:
            row.quantity += item.quantity
    order.status = "cancelled"
    order.payment_status = "voided"
    order.eta = None
    add_event(order, "cancelled")
    db.commit()
    return order


# ------------------------------------------------ changing an order that has not shipped
def _edit_event(order: StoreOrder, label: str) -> None:
    order.events.append(StoreOrderEvent(status="updated", label=label[:80], occurred_at=_now()))


def _editable(db: Session, order_id: Any, email: Optional[str]) -> StoreOrder:
    order = get_order(db, order_id, email=email)
    if not order:
        raise StoreError("not_found", "Order not found.")
    if order.status != "processing":
        raise StoreError("not_editable", f"Order #{order.order_id} is {order.status}, so it can no longer be changed here.")
    return order


def update_order_address(db: Session, order_id: Any, *, email: Optional[str], address: str, city: str, zip_code: str,
                         country: Optional[str] = None) -> StoreOrder:
    order = _editable(db, order_id, email)
    address, city, zip_code = (address or "").strip(), (city or "").strip(), (zip_code or "").strip()
    if not (address and city and zip_code) or len(address) > 300 or len(city) > 120 or len(zip_code) > 32:
        raise StoreError("invalid_address", "A delivery address needs a street address, a city and a ZIP/postal code.")
    order.ship_address, order.ship_city, order.ship_zip = address, city, zip_code
    if country:
        order.ship_country = country.strip()[:80]
    _edit_event(order, "Delivery address updated")
    db.commit()
    return order


def change_order_size(db: Session, order_id: Any, *, email: Optional[str], new_size: str, product: Optional[str] = None) -> StoreOrder:
    """Swap one item's size. The new size must be in stock; the old size goes back on the shelf."""
    order = _editable(db, order_id, email)
    items = list(order.items)
    if product:
        low = str(product).strip().lower()
        items = [i for i in items if (i.product_id or "").lower() == low or low in i.name.lower()]
    if len(items) != 1:
        raise StoreError("which_item", "Which item should change size? " + ", ".join(i.name for i in order.items))
    item = items[0]
    prod = db.get(StoreProduct, item.product_id) if item.product_id else None
    if not prod:
        raise StoreError("unknown_product", "That item can no longer be changed.")
    size = next((s_ for s_ in (prod.sizes or []) if s_.lower() == str(new_size or "").strip().lower()), None)
    if not size:
        raise StoreError("invalid_size", f"{prod.name} comes in sizes {', '.join(prod.sizes or [])}.")
    if size == item.size:
        raise StoreError("same_size", f"That item is already size {size}.")
    taken = db.execute(update(StoreInventory).where(StoreInventory.product_id == prod.product_id, StoreInventory.size == size,
                                                    StoreInventory.quantity >= item.quantity).values(quantity=StoreInventory.quantity - item.quantity))
    if taken.rowcount != 1:
        db.rollback()
        raise StoreError("out_of_stock", f"Sorry, {prod.name} in size {size} doesn't have enough stock left.")
    old = db.execute(select(StoreInventory).where(StoreInventory.product_id == prod.product_id, StoreInventory.size == item.size)).scalars().first()
    if old:
        old.quantity += item.quantity
    old_size, item.size = item.size, size
    _edit_event(order, f"Size changed: {item.name} {old_size} to {size}")
    db.commit()
    return order


def add_order_item(db: Session, order_id: Any, *, email: Optional[str], product_id: str, size: str, quantity: int = 1) -> StoreOrder:
    """Add an item to an order that has not shipped. Stock is taken atomically; the order's totals are recalculated."""
    order = _editable(db, order_id, email)
    product = db.get(StoreProduct, product_id)
    if not product or not product.active:
        raise StoreError("unknown_product", "That product is no longer available.")
    size_ok = next((x for x in (product.sizes or []) if x.lower() == str(size or "").strip().lower()), None)
    if not size_ok:
        raise StoreError("invalid_size", f"{product.name} comes in sizes {', '.join(product.sizes or [])}.")
    qty = int(quantity or 1)
    if qty < 1 or qty > MAX_QTY:
        raise StoreError("invalid_quantity", f"Quantity must be between 1 and {MAX_QTY}.")
    taken = db.execute(update(StoreInventory).where(StoreInventory.product_id == product_id, StoreInventory.size == size_ok,
                                                    StoreInventory.quantity >= qty).values(quantity=StoreInventory.quantity - qty))
    if taken.rowcount != 1:
        db.rollback()
        raise StoreError("out_of_stock", f"Sorry, {product.name} in size {size_ok} doesn't have enough stock left.")
    line = next((i for i in order.items if i.product_id == product_id and i.size == size_ok), None)
    if line:
        line.quantity += qty
    else:
        order.items.append(StoreOrderItem(product_id=product_id, name=product.name, size=size_ok, quantity=qty, unit_price=product.price))
    order.subtotal = sum((i.unit_price * i.quantity for i in order.items), Decimal("0"))
    order.tax = (order.subtotal * TAX_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    order.total = order.subtotal + order.shipping_cost + order.tax
    _edit_event(order, f"Item added: {product.name} ({size_ok}) x{qty}")
    db.commit()
    return order
