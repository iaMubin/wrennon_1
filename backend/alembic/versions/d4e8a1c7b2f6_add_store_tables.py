"""add storefront tables

Revision ID: d4e8a1c7b2f6
Revises: c2d3e4f5a6b7
Create Date: 2026-11-14 12:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd4e8a1c7b2f6'
down_revision: Union[str, Sequence[str], None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'store_products',
        sa.Column('product_id', sa.String(32), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('category', sa.String(32), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('price', sa.Numeric(10, 2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('keywords', sa.JSON(), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('sizes', sa.JSON(), nullable=False),
        sa.Column('featured', sa.Boolean(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_store_products_category', 'store_products', ['category'])
    op.create_table(
        'store_inventory',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('product_id', sa.String(32), sa.ForeignKey('store_products.product_id', ondelete='CASCADE'), nullable=False),
        sa.Column('size', sa.String(16), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.UniqueConstraint('product_id', 'size', name='uq_store_inventory_product_size'),
    )
    op.create_index('ix_store_inventory_product_id', 'store_inventory', ['product_id'])
    op.create_table(
        'store_customers',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('email', sa.String(254), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('phone', sa.String(40), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_store_customers_email', 'store_customers', ['email'], unique=True)
    op.create_table(
        'store_orders',
        sa.Column('order_id', sa.String(16), primary_key=True),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('store_customers.id'), nullable=True),
        sa.Column('email', sa.String(254), nullable=False),
        sa.Column('customer_name', sa.String(200), nullable=False),
        sa.Column('phone', sa.String(40), nullable=True),
        sa.Column('ship_address', sa.String(300), nullable=False),
        sa.Column('ship_city', sa.String(120), nullable=False),
        sa.Column('ship_zip', sa.String(32), nullable=False),
        sa.Column('ship_country', sa.String(80), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('payment_status', sa.String(20), nullable=False),
        sa.Column('payment_method', sa.String(80), nullable=True),
        sa.Column('shipping_method', sa.String(80), nullable=True),
        sa.Column('carrier', sa.String(80), nullable=True),
        sa.Column('tracking_number', sa.String(80), nullable=True),
        sa.Column('tracking_url', sa.String(300), nullable=True),
        sa.Column('eta', sa.Date(), nullable=True),
        sa.Column('subtotal', sa.Numeric(10, 2), nullable=False),
        sa.Column('shipping_cost', sa.Numeric(10, 2), nullable=False),
        sa.Column('tax', sa.Numeric(10, 2), nullable=False),
        sa.Column('total', sa.Numeric(10, 2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    for col in ('customer_id', 'email', 'status', 'created_at'):
        op.create_index(f'ix_store_orders_{col}', 'store_orders', [col])
    op.create_table(
        'store_order_items',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('order_id', sa.String(16), sa.ForeignKey('store_orders.order_id', ondelete='CASCADE'), nullable=False),
        sa.Column('product_id', sa.String(32), nullable=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('size', sa.String(16), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_price', sa.Numeric(10, 2), nullable=False),
    )
    op.create_index('ix_store_order_items_order_id', 'store_order_items', ['order_id'])
    op.create_table(
        'store_order_events',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('order_id', sa.String(16), sa.ForeignKey('store_orders.order_id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('label', sa.String(80), nullable=False),
        sa.Column('occurred_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_store_order_events_order_id', 'store_order_events', ['order_id'])
    op.create_table(
        'store_refunds',
        sa.Column('refund_id', sa.String(24), primary_key=True),
        sa.Column('order_id', sa.String(16), sa.ForeignKey('store_orders.order_id', ondelete='CASCADE'), nullable=False),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_store_refunds_order_id', 'store_refunds', ['order_id'])


def downgrade() -> None:
    for table in ('store_refunds', 'store_order_events', 'store_order_items', 'store_orders',
                  'store_customers', 'store_inventory', 'store_products'):
        op.drop_table(table)
