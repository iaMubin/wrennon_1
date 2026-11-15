"""add storefront ui actions

Revision ID: a2d9e5c1b7f4
Revises: f1c7d2b8a9e3
Create Date: 2026-11-14 23:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a2d9e5c1b7f4'
down_revision: Union[str, Sequence[str], None] = 'f1c7d2b8a9e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'store_ui_actions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('session_id', sa.String(64), nullable=False),
        sa.Column('type', sa.String(24), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('delivered', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_store_ui_actions_session_id', 'store_ui_actions', ['session_id'])


def downgrade() -> None:
    op.drop_table('store_ui_actions')
