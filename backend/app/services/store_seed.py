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

from app.db.store_models import StoreCustomer, StoreInventory, StoreOrder, StoreOrderEvent, StoreOrderItem, StoreProduct
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


def seed_store(db: Session, with_orders: bool = True) -> dict:
    products = seed_products(db)
    orders = seed_orders(db) if with_orders else 0
    return {"products_created": products, "orders_created": orders}
