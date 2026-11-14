"""
Storefront data model — the "system of record" the chatbot reads from.

This is what Shopify (or any commerce backend) provides in production. Keeping it
in our own database lets the demo storefront, the REST API and the chatbot's
tools all work from ONE source of truth:

- StoreProduct / StoreInventory : catalog and per-size stock
- StoreCustomer                 : who buys (email is the identity key)
- StoreOrder / StoreOrderItem   : what was bought, price snapshots at purchase time
- StoreOrderEvent               : the order timeline (placed -> processing -> shipped -> delivered)
- StoreRefund                   : money returned against an order

Money is Numeric(10, 2) (never float). Timestamps are naive UTC, matching the rest of the app.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models import Base


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class StoreProduct(Base):
    __tablename__ = "store_products"

    product_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # SKU, e.g. WRN-JKT-201
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(32), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    keywords: Mapped[list] = mapped_column(JSON, default=list)  # drives recommend_product
    details: Mapped[list] = mapped_column(JSON, default=list)   # bullet points on the product page
    sizes: Mapped[list] = mapped_column(JSON, default=list)
    featured: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    inventory: Mapped[list["StoreInventory"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", order_by="StoreInventory.id"
    )


class StoreInventory(Base):
    __tablename__ = "store_inventory"
    __table_args__ = (UniqueConstraint("product_id", "size", name="uq_store_inventory_product_size"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("store_products.product_id", ondelete="CASCADE"), index=True
    )
    size: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[int] = mapped_column(Integer, default=0)

    product: Mapped[StoreProduct] = relationship(back_populates="inventory")


class StoreCustomer(Base):
    __tablename__ = "store_customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)  # stored lower-case
    name: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(100), nullable=True)  # None = guest (never registered)
    last_login_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)


class StoreOrder(Base):
    __tablename__ = "store_orders"

    order_id: Mapped[str] = mapped_column(String(16), primary_key=True)  # numeric string, shown as #1011
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("store_customers.id"), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    customer_name: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)

    ship_address: Mapped[str] = mapped_column(String(300), default="")
    ship_city: Mapped[str] = mapped_column(String(120), default="")
    ship_zip: Mapped[str] = mapped_column(String(32), default="")
    ship_country: Mapped[str | None] = mapped_column(String(80), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="processing", index=True)
    payment_status: Mapped[str] = mapped_column(String(20), default="paid")
    payment_method: Mapped[str | None] = mapped_column(String(80), nullable=True)
    shipping_method: Mapped[str | None] = mapped_column(String(80), nullable=True)
    carrier: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tracking_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tracking_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    eta: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)

    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    shipping_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    tax: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now, index=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    items: Mapped[list["StoreOrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="StoreOrderItem.id"
    )
    events: Mapped[list["StoreOrderEvent"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="StoreOrderEvent.occurred_at, StoreOrderEvent.id"
    )
    refunds: Mapped[list["StoreRefund"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="StoreRefund.created_at"
    )


class StoreOrderItem(Base):
    __tablename__ = "store_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("store_orders.order_id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(200))  # snapshot: survives later renames
    size: Mapped[str] = mapped_column(String(16), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # snapshot of the price paid

    order: Mapped[StoreOrder] = relationship(back_populates="items")


class StoreOrderEvent(Base):
    __tablename__ = "store_order_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("store_orders.order_id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(24))
    label: Mapped[str] = mapped_column(String(80))
    occurred_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)

    order: Mapped[StoreOrder] = relationship(back_populates="events")


class StoreRefund(Base):
    __tablename__ = "store_refunds"

    refund_id: Mapped[str] = mapped_column(String(24), primary_key=True)  # REF-AB12CD
    order_id: Mapped[str] = mapped_column(ForeignKey("store_orders.order_id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="approved")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)

    order: Mapped[StoreOrder] = relationship(back_populates="refunds")
