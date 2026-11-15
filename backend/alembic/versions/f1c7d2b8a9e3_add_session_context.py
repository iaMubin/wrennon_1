"""add storefront session context

Revision ID: f1c7d2b8a9e3
Revises: a9e2c6d1b4f7
Create Date: 2026-11-14 21:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f1c7d2b8a9e3'
down_revision: Union[str, Sequence[str], None] = 'a9e2c6d1b4f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'store_session_context',
        sa.Column('session_id', sa.String(64), primary_key=True),
        sa.Column('context', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('store_session_context')
