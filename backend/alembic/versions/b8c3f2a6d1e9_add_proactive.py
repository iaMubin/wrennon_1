"""add proactive messaging tables

Revision ID: b8c3f2a6d1e9
Revises: a2d9e5c1b7f4
Create Date: 2026-11-15 10:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b8c3f2a6d1e9'
down_revision: Union[str, Sequence[str], None] = 'a2d9e5c1b7f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'store_pending_messages',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('customer_email', sa.String(254), nullable=False),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('delivered', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_store_pending_messages_customer_email', 'store_pending_messages', ['customer_email'])
    op.create_table(
        'store_nudge_log',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('session_id', sa.String(64), nullable=False),
        sa.Column('kind', sa.String(24), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_store_nudge_log_session_id', 'store_nudge_log', ['session_id'])


def downgrade() -> None:
    op.drop_table('store_nudge_log')
    op.drop_table('store_pending_messages')
