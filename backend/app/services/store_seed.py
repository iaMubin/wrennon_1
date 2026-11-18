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
from typing import NamedTuple
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
    n = max(1, count)
    combos = itertools.combinations(catalog, n) if n <= len(catalog) else itertools.combinations_with_replacement(catalog, n)   # distinct items: no "Parka x1, Parka x1"
    for combo in combos:
        s = sum(p for _, p in combo)
        if s <= total and (best_gap is None or total - s < best_gap):
            best, best_gap = combo, total - s
    return best or (catalog[0],)


def seed_orders(db: Session) -> int:
    created = 0
    for order_id, o in sorted(MOCK_ORDERS.items()):
        if db.get(StoreOrder, order_id):
            continue
        person = person_for(o["email"])
        email = person.email if person else o["email"].lower()
        customer = db.query(StoreCustomer).filter_by(email=email).first()
        if not customer:
            customer = StoreCustomer(email=email, name=person.name if person else email.split("@")[0].replace(".", " ").title(), phone=person.phone if person else None)
            db.add(customer)
            db.flush()
        trk_no, trk_url = svc.make_tracking(o["carrier"], random.Random(int(order_id))) if o.get("carrier") else (None, None)
        total = _money(o["total_amount"])
        combo = _pick_items(total, int(o.get("items_count") or 1))
        subtotal = sum(p for _, p in combo)
        timeline = o.get("timeline") or []
        created_at = _parse_dt(timeline[0]["time"]) if timeline else datetime.datetime.fromisoformat(o["order_date"])
        status = "processing" if o["status"] == "placed" else o["status"]
        order = StoreOrder(
            order_id=order_id, customer_id=customer.id, email=email, customer_name=customer.name, phone=customer.phone,
            ship_address=person.street if person else "123 Demo Street", ship_city=person.city if person else "Springfield", ship_zip=person.zip if person else "10001", ship_country="US",
            status=status, payment_status={"cancelled": "voided"}.get(status, "paid"), payment_method=o.get("payment_method"),
            shipping_method=o.get("shipping_method"), carrier=o.get("carrier"), tracking_url=trk_url, tracking_number=trk_no,
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
_HISTORY_FLAG = "store_history_seeded"


class Person(NamedTuple):
    name: str
    email: str
    phone: str
    street: str
    city: str     # "City, ST"
    zip: str
    old: str      # placeholder identity this person replaces (earlier seeds used example.com addresses)


# Fictional people with realistic details. Phone numbers use the 555-01xx range that is reserved for fiction,
# so none of them can ring a real person. The streets and ZIPs are plausible for each city, not real homes.
DEMO_PEOPLE = [
    Person("Emma Richardson", "emma.richardson@gmail.com", "+1 503-555-0147", "2418 NW Lovejoy St, Apt 3", "Portland, OR", "97209", "eleanor.v@example.com"),
    Person("Marcus Johnson", "marcus.t.johnson@outlook.com", "+1 404-555-0132", "815 Peachtree St NE, Unit 12", "Atlanta, GA", "30308", "mchang.tech@example.com"),
    Person("Priya Raman", "priya.raman@gmail.com", "+1 206-555-0175", "1627 N 45th St", "Seattle, WA", "98103", "sjenkins88@example.com"),
    Person("Daniel Kowalski", "dkowalski84@yahoo.com", "+1 312-555-0164", "2203 N Clark St, Apt 2R", "Chicago, IL", "60614", "drodriguez@example.com"),
    Person("Sofia Hernandez", "sofia.hdz@icloud.com", "+1 512-555-0128", "1104 S 1st St", "Austin, TX", "78704", "emily.c@example.com"),
    Person("Jamal Washington", "jwash.designs@gmail.com", "+1 718-555-0191", "342 7th Ave, Apt 4B", "Brooklyn, NY", "11215", "jwilson@example.com"),
    Person("Hannah Lindqvist", "hannah.lindqvist@proton.me", "+1 612-555-0143", "3809 Grand Ave S", "Minneapolis, MN", "55409", "omartinez99@example.com"),
    Person("Ethan Brooks", "ethanbrooks22@gmail.com", "+1 303-555-0186", "1560 Pearl St, Unit 5", "Denver, CO", "80203", "wtaylor.biz@example.com"),
    Person("Olivia Chen", "olivia.chen.sf@gmail.com", "+1 415-555-0159", "917 Valencia St", "San Francisco, CA", "94110", "sanderson@example.com"),
    Person("Liam O'Connor", "liam.oconnor@outlook.com", "+1 617-555-0173", "48 Tremont St, Apt 6", "Boston, MA", "02108", "athomas.design@example.com"),
    Person("Aisha Khan", "aisha.khan91@gmail.com", "+1 713-555-0138", "2710 Westheimer Rd, Apt 118", "Houston, TX", "77098", "priya.nair@example.com"),
    Person("Mateo Alvarez", "mateo.alvarez@yahoo.com", "+1 602-555-0126", "4412 N 7th Ave", "Phoenix, AZ", "85013", "d.okafor@example.com"),
    Person("Grace Thompson", "gracethompson@icloud.com", "+1 615-555-0152", "1803 Church St", "Nashville, TN", "37203", "sofia.r@example.com"),
    Person("Noah Fischer", "noah.fischer@gmail.com", "+1 614-555-0167", "987 N High St", "Columbus, OH", "43201", "hannah.berg@example.com"),
    Person("Chloe Dubois", "chloe.dubois@outlook.com", "+1 215-555-0114", "1305 S 9th St", "Philadelphia, PA", "19147", "tomas.silva@example.com"),
]
_BY_OLD = {p.old: p for p in DEMO_PEOPLE}
_BY_EMAIL = {p.email: p for p in DEMO_PEOPLE}


def person_for(email: str) -> Person | None:
    e = (email or "").lower()
    return _BY_EMAIL.get(e) or _BY_OLD.get(e)


def demo_customers() -> list:
    return [(p.name, p.email, p.phone) for p in DEMO_PEOPLE]


def upgrade_demo_identities(db: Session) -> int:
    """Databases seeded earlier hold placeholder customers (example.com). Give them their realistic identity in place,
    so their orders, logins and chat conversations carry over. Idempotent."""
    from sqlalchemy import func
    from app.db.models import Conversation
    changed = 0
    for p in DEMO_PEOPLE:
        old = svc.customer_by_email(db, p.old)
        if not old:
            continue
        orders = db.query(StoreOrder).filter(StoreOrder.email == p.old).all()
        new = svc.customer_by_email(db, p.email)
        if new and new.id != old.id:      # the new identity already exists: move everything onto it
            if not new.password_hash:
                new.password_hash = old.password_hash
            for o in orders:
                o.customer_id = new.id
            db.flush()
            db.delete(old)
        else:
            old.email = p.email
            new = old
        new.name, new.phone = p.name, p.phone
        for o in orders:
            o.email, o.customer_name, o.phone = p.email, p.name, p.phone
            o.ship_address, o.ship_city, o.ship_zip, o.ship_country, o.customer_id = p.street, p.city, p.zip, "US", new.id
        db.query(Conversation).filter(func.lower(Conversation.customer_email) == p.old).update({"customer_email": p.email}, synchronize_session=False)
        changed += 1
    db.commit()
    return changed


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
        person = person_for(email)
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
            carrier = rng.choice(["FedEx", "UPS", "USPS"])
            tracking, track_url = svc.make_tracking(carrier, rng)
            order = StoreOrder(
                order_id=str(nxt), customer_id=c.id, email=email, customer_name=name, phone=phone, ship_address=person.street,
                ship_city=person.city, ship_zip=person.zip, ship_country="US", status=status, payment_status="voided" if status == "cancelled" else "paid",
                payment_method=rng.choice(["Credit Card (Visa)", "Credit Card (Mastercard)", "PayPal"]), shipping_method="Standard Delivery",
                carrier=carrier if status in ("shipped", "delivered") else None, tracking_number=tracking if status in ("shipped", "delivered") else None,
                tracking_url=track_url if status in ("shipped", "delivered") else None,
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


def refresh_tracking(db: Session) -> int:
    """Earlier seeds used placeholder tracking links; give those orders real-format numbers and carrier links."""
    n = 0
    for o in db.query(StoreOrder).filter(StoreOrder.tracking_url.isnot(None)).all():
        if "example.com" in o.tracking_url or "fedex.com/track/" in o.tracking_url or "wrennon" in o.tracking_url:
            o.tracking_number, o.tracking_url = svc.make_tracking(o.carrier or "FedEx", random.Random(int(o.order_id) if o.order_id.isdigit() else 7))
            n += 1
    db.commit()
    return n


def merge_duplicate_lines(db: Session) -> int:
    """Earlier seeds could list the same product twice in one order ("Parka x1" twice). Merge them into one line with a quantity."""
    merged = 0
    for o in db.query(StoreOrder).all():
        seen = {}
        for it in list(o.items):
            key = (it.product_id, it.size)
            if key in seen:
                seen[key].quantity += it.quantity
                o.items.remove(it)
                merged += 1
            else:
                seen[key] = it
    db.commit()
    return merged


_SHIFT_FLAG = "store_mock_dates_shifted"


def refresh_mock_dates(db: Session, today: datetime.date | None = None) -> int:
    """The ten original demo orders carry dates from when the mock data was written. Slide them forward (once) so the newest is
    yesterday - otherwise a 'processing' order from months ago and an ETA in the past look wrong."""
    if db.query(SystemSetting).filter_by(key=_SHIFT_FLAG).first():
        return 0
    orders = [o for o in (db.get(StoreOrder, i) for i in MOCK_ORDERS) if o]
    if not orders:
        return 0
    today = today or datetime.date.today()
    gap = (today - max(o.created_at for o in orders).date()).days - 1
    if gap > 14:
        shift = datetime.timedelta(days=gap)
        for o in orders:
            o.created_at += shift
            if o.eta:
                o.eta += shift
            for e in o.events:
                e.occurred_at += shift
    db.add(SystemSetting(key=_SHIFT_FLAG, value=str(max(gap, 0))))
    db.commit()
    return len(orders) if gap > 14 else 0


def seed_store(db: Session, with_orders: bool = True, with_history: bool = True) -> dict:
    products = seed_products(db)
    renamed = upgrade_demo_identities(db)
    customers = seed_customers(db)
    orders = seed_orders(db) if with_orders else 0
    refresh_tracking(db)
    merge_duplicate_lines(db)
    refresh_mock_dates(db)
    history = seed_history(db) if (with_orders and with_history) else 0
    return {"products_created": products, "customers_renamed": renamed, "customers_created": customers, "orders_created": orders, "history_orders_created": history}
