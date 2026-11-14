"""
Seeds the storefront database. Safe to run repeatedly: products/inventory are upserted by id
(your edits to *stock* are kept), demo orders are only inserted when their number is missing.

    python -m scripts.seed_store
"""

from __future__ import annotations

import datetime
import itertools
from decimal import Decimal
from typing import Dict

from sqlalchemy.orm import Session

import random
from app.db.models import SystemSetting
from app.db.store_models import StoreCustomer, StoreInventory, StoreOrder, StoreOrderEvent, StoreOrderItem, StoreProduct, StoreRefund
from app.services.customer_auth import hash_pw
from app.services import store_service as svc
from app.services.integrations.mock_provider import PRODUCT_CATALOG
from app.services.mock_apis import MOCK_CUSTOMERS, MOCK_ORDERS

# Presentation/merchandising data the old mock catalog didn't have.
_EXTRA: Dict[str, dict] = {
    "WRN-JKT-201": dict(category="outerwear", featured=True, sizes=["S", "M", "L", "XL"], details=["Insulated", "Waterproof", "Rated for sub-zero temperatures"]),
    "WRN-JKT-202": dict(category="outerwear", sizes=["S", "M", "L", "XL"], details=["Classic denim", "Layers over everyday outfits"]),
    "WRN-BOOT-102": dict(category="footwear", featured=True, sizes=["7", "8", "9", "10", "11", "12"], details=["Weatherproof leather", "Warm shearling lining", "Built for cold, wet days"]),
    "WRN-SHO-101": dict(category="footwear", sizes=["7", "8", "9", "10", "11", "12"], details=["Breathable mesh upper", "Cushioned sole", "City streets or light trails"]),
    "WRN-HOD-302": dict(category="essentials", featured=True, sizes=["S", "M", "L", "XL"], details=["Heavyweight fleece", "Warm without the bulk"]),
    "WRN-TSH-301": dict(category="essentials", sizes=["S", "M", "L", "XL"], details=["100% cotton", "Soft and breathable", "Relaxed fit"]),
    "WRN-PNT-401": dict(category="essentials", sizes=["28", "30", "32", "34", "36"], details=["Stretch fabric", "Smart enough for the office", "Comfortable for everything else"]),
    "WRN-ACC-501": dict(category="accessories", sizes=["One size"], details=["Soft wool", "Pairs well with the Summit Parka"]),
    "WRN-ACC-502": dict(category="accessories", featured=True, sizes=["One size"], details=["Durable canvas", "Leather trim", "Weekend trip or the gym"]),
}
_DEFAULT_STOCK = 15
_STOCK_OVERRIDES = {("WRN-BOOT-102", "12"): 0, ("WRN-JKT-201", "XL"): 2}  # a sold-out size and a low-stock size, handy for demos


def _money(text: str) -> Decimal:
    return Decimal(str(text).replace("$", "").replace(",", "").strip() or "0")


def _parse_dt(text: str | None) -> datetime.datetime | None:
    if not text:
        return None
    return datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)


def seed_products(db: Session) -> int:
    created = 0
    for item in PRODUCT_CATALOG:
        extra = _EXTRA.get(item["product_id"])
        if not extra:
            continue
        product = db.get(StoreProduct, item["product_id"])
        if not product:
            product = StoreProduct(product_id=item["product_id"])
            db.add(product)
            created += 1
        product.name, product.description, product.price = item["name"], item["description"], Decimal(str(item["price"]))
        product.keywords, product.category = item.get("keywords", []), extra["category"]
        product.sizes, product.details, product.featured = extra["sizes"], extra["details"], extra.get("featured", False)
        existing = {row.size for row in product.inventory}
        for size in extra["sizes"]:
            if size not in existing:
                product.inventory.append(StoreInventory(size=size, quantity=_STOCK_OVERRIDES.get((product.product_id, size), _DEFAULT_STOCK)))
    db.commit()
    return created


def _pick_items(total: Decimal, count: int):
    """Choose catalog items whose prices sum as close to (but not over) the mock order total as possible."""
    catalog = [(i["product_id"], Decimal(str(i["price"]))) for i in PRODUCT_CATALOG if i["product_id"] in _EXTRA]
    best, best_gap = None, None
    for combo in itertools.combinations_with_replacement(catalog, max(1, count)):
        s = sum(p for _, p in combo)
        if s <= total and (best_gap is None or total - s < best_gap):
            best, best_gap = combo, total - s
    return best or (catalog[0],)


def seed_orders(db: Session) -> int:
    names = {c["email"].lower(): c for c in MOCK_CUSTOMERS}
    created = 0
    for order_id, o in sorted(MOCK_ORDERS.items()):
        if db.get(StoreOrder, order_id):
            continue
        email = o["email"].lower()
        cust_src = names.get(email, {})
        customer = db.query(StoreCustomer).filter_by(email=email).first()
        if not customer:
            customer = StoreCustomer(email=email, name=cust_src.get("name") or email.split("@")[0].replace(".", " ").title(), phone=cust_src.get("phone"))
            db.add(customer)
            db.flush()
        total = _money(o["total_amount"])
        combo = _pick_items(total, int(o.get("items_count") or 1))
        subtotal = sum(p for _, p in combo)
        timeline = o.get("timeline") or []
        created_at = _parse_dt(timeline[0]["time"]) if timeline else datetime.datetime.fromisoformat(o["order_date"])
        status = "processing" if o["status"] == "placed" else o["status"]
        order = StoreOrder(
            order_id=order_id, customer_id=customer.id, email=email, customer_name=customer.name, phone=customer.phone,
            ship_address="123 Demo Street", ship_city="Springfield", ship_zip="10001", ship_country="US",
            status=status, payment_status={"cancelled": "voided"}.get(status, "paid"), payment_method=o.get("payment_method"),
            shipping_method=o.get("shipping_method"), carrier=o.get("carrier"), tracking_url=o.get("tracking_url"),
            tracking_number=(o.get("tracking_url") or "").rsplit("/", 1)[-1] or None,
            eta=datetime.date.fromisoformat(o["eta"]) if o.get("eta") else None,
            subtotal=subtotal, shipping_cost=total - subtotal, tax=Decimal("0"), total=total, currency="USD", created_at=created_at,
        )
        for pid, price in combo:
            product = db.get(StoreProduct, pid)
            order.items.append(StoreOrderItem(product_id=pid, name=product.name if product else pid, size=(product.sizes[len(product.sizes) // 2] if product and product.sizes else ""), quantity=1, unit_price=price))
        for e in timeline:
            order.events.append(StoreOrderEvent(status=e["status"], label=e.get("label") or e["status"].title(), occurred_at=_parse_dt(e["time"]) or created_at))
        db.add(order)
        created += 1
    db.commit()
    return created


DEMO_PASSWORD = "northbound123"   # every seeded demo customer signs in with this
_EXTRA_CUSTOMERS = [
    ("Priya Nair", "priya.nair@example.com", "+1-555-0311"), ("Daniel Okafor", "d.okafor@example.com", "+1-555-0327"),
    ("Sofia Ramirez", "sofia.r@example.com", "+1-555-0342"), ("Hannah Berg", "hannah.berg@example.com", "+1-555-0368"),
    ("Tomas Silva", "tomas.silva@example.com", "+1-555-0379"),
]
_CITIES = [("Springfield", "10001"), ("Portland", "97201"), ("Austin", "73301"), ("Denver", "80202"), ("Seattle", "98101"), ("Boston", "02108")]
_HISTORY_FLAG = "store_history_seeded"


def demo_customers() -> list:
    base = [(c["name"], c["email"].lower(), c.get("phone")) for c in MOCK_CUSTOMERS]
    return base + [(n, e, p) for n, e, p in _EXTRA_CUSTOMERS]


def seed_customers(db: Session) -> int:
    """15 demo customers. Each can sign in on the storefront with DEMO_PASSWORD."""
    pw = None
    created = 0
    for name, email, phone in demo_customers():
        c = svc.customer_by_email(db, email)
        if not c:
            c = StoreCustomer(email=email, name=name, phone=phone)
            db.add(c)
            created += 1
        if not c.password_hash:
            pw = pw or hash_pw(DEMO_PASSWORD)
            c.password_hash = pw
    db.commit()
    return created


def seed_history(db: Session, today: datetime.date | None = None) -> int:
    """Realistic past orders for the demo customers (1-6 each, spread over the last year). Runs once."""
    if db.query(SystemSetting).filter_by(key=_HISTORY_FLAG).first():
        return 0
    rng = random.Random(2026)
    today = today or datetime.date.today()
    products = db.query(StoreProduct).order_by(StoreProduct.product_id).all()
    if not products:
        return 0
    nxt = int(svc._next_order_id(db))
    created = 0
    for name, email, phone in demo_customers():
        c = svc.customer_by_email(db, email)
        want = rng.randint(2, 6) if rng.random() > .15 else 1
        city, zip_code = rng.choice(_CITIES)
        for _ in range(max(0, want - db.query(StoreOrder).filter_by(email=email).count())):
            placed = datetime.datetime.combine(today - datetime.timedelta(days=rng.randint(3, 400)), datetime.time(rng.randint(8, 21), rng.randint(0, 59)))
            age = (datetime.datetime.combine(today, datetime.time(12)) - placed).days
            lines = []
            for p in rng.sample(products, rng.choice([1, 1, 2, 3])):
                lines.append(StoreOrderItem(product_id=p.product_id, name=p.name, size=rng.choice(p.sizes), quantity=1 if rng.random() > .12 else 2, unit_price=p.price))
            subtotal = sum(l.unit_price * l.quantity for l in lines)
            roll = rng.random()
            if age < 3:
                status = "processing"
            elif age < 6:
                status = "shipped"
            else:
                status = "cancelled" if roll < .05 else "delivered"
            carrier = rng.choice(["FedEx", "UPS", "DHL"])
            tracking = f"{carrier[:2].upper()}{rng.randint(10**9, 10**10 - 1)}"
            order = StoreOrder(
                order_id=str(nxt), customer_id=c.id, email=email, customer_name=name, phone=phone, ship_address=f"{rng.randint(10, 990)} {rng.choice(['Maple', 'Oak', 'Cedar', 'Pine', 'Elm'])} Street",
                ship_city=city, ship_zip=zip_code, ship_country="US", status=status, payment_status="voided" if status == "cancelled" else "paid",
                payment_method=rng.choice(["Credit Card (Visa)", "Credit Card (Mastercard)", "PayPal"]), shipping_method="Standard Delivery",
                carrier=carrier if status in ("shipped", "delivered") else None, tracking_number=tracking if status in ("shipped", "delivered") else None,
                tracking_url=f"https://example.com/track/{tracking}" if status in ("shipped", "delivered") else None,
                eta=(placed + datetime.timedelta(days=5)).date() if status == "shipped" else None,
                subtotal=subtotal, shipping_cost=Decimal("0"), tax=Decimal("0"), total=subtotal, currency="USD", created_at=placed, items=lines,
            )
            steps = [("placed", 0), ("processing", 5)] + ([("shipped", 30)] if status in ("shipped", "delivered") else []) + ([("delivered", 72)] if status == "delivered" else []) + ([("cancelled", 8)] if status == "cancelled" else [])
            for st, hours in steps:
                order.events.append(StoreOrderEvent(status=st, label=svc.LABELS[st], occurred_at=placed + datetime.timedelta(hours=hours)))
            if status == "delivered" and roll > .93:  # a few partial refunds so refund history exists
                amt = (subtotal * Decimal("0.3")).quantize(Decimal("0.01"))
                order.refunds.append(StoreRefund(refund_id=f"REF-{rng.randint(0, 16**6 - 1):06X}", amount=amt, reason="Return: wrong size", status="approved", created_at=placed + datetime.timedelta(days=9)))
                order.payment_status = "partially_refunded"
                order.events.append(StoreOrderEvent(status="partially_refunded", label=svc.LABELS["partially_refunded"], occurred_at=placed + datetime.timedelta(days=9)))
            db.add(order)
            nxt += 1
            created += 1
    db.flush()
    for name, email, phone in demo_customers():   # a customer can't have joined after their first order
        c = svc.customer_by_email(db, email)
        first = db.query(StoreOrder).filter_by(email=email).order_by(StoreOrder.created_at).first()
        if c and first and first.created_at - datetime.timedelta(days=3) < c.created_at:
            c.created_at = first.created_at - datetime.timedelta(days=3)
    db.add(SystemSetting(key=_HISTORY_FLAG, value="1"))
    db.commit()
    return created


def seed_store(db: Session, with_orders: bool = True, with_history: bool = True) -> dict:
    products = seed_products(db)
    customers = seed_customers(db)
    orders = seed_orders(db) if with_orders else 0
    history = seed_history(db) if (with_orders and with_history) else 0
    return {"products_created": products, "customers_created": customers, "orders_created": orders, "history_orders_created": history}
