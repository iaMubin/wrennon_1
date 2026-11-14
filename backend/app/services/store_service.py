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
    "cancelled": "Cancelled", "refunded": "Refunded", "partially_refunded": "Partially Refunded",
}
STATUSES = ("processing", "shipped", "delivered", "cancelled")


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
def order_to_dict(o: StoreOrder, include_email: bool = False) -> Dict[str, Any]:
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
               eta: Optional[datetime.date] = None) -> StoreOrder:
    """Move an order through its lifecycle (what a warehouse/carrier webhook would do)."""
    if status not in STATUSES:
        raise StoreError("invalid_status", f"Status must be one of: {', '.join(STATUSES)}.")
    order = get_order(db, order_id)
    if not order:
        raise StoreError("not_found", "Order not found.")
    order.status = status
    if status == "shipped":
        order.carrier = carrier or order.carrier or "FedEx"
        order.tracking_number = tracking_number or order.tracking_number or f"NB{uuid.uuid4().hex[:10].upper()}"
        order.tracking_url = tracking_url or order.tracking_url or f"https://example.com/track/{order.tracking_number}"
        order.eta = eta or order.eta or (_now() + datetime.timedelta(days=4)).date()
    if status == "delivered":
        order.eta = None
    if status == "cancelled":
        order.payment_status = "voided"
    add_event(order, status)
    db.commit()
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
