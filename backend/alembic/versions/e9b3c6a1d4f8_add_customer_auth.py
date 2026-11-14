"""add customer login columns

Revision ID: e9b3c6a1d4f8
Revises: d4e8a1c7b2f6
Create Date: 2026-11-14 18:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e9b3c6a1d4f8'
down_revision: Union[str, Sequence[str], None] = 'd4e8a1c7b2f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('store_customers', sa.Column('password_hash', sa.String(100), nullable=True))
    op.add_column('store_customers', sa.Column('last_login_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('store_customers', 'last_login_at')
    op.drop_column('store_customers', 'password_hash')
