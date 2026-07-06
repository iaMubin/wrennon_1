"""add missing conversation columns

Revision ID: f4aa25bd0490
Revises: 20b98c7f601b
Create Date: 2026-07-06 18:31:49.368592

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4aa25bd0490'
down_revision: Union[str, Sequence[str], None] = '20b98c7f601b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = [c['name'] for c in insp.get_columns('conversations')]
    
    if 'short_id' not in columns:
        op.add_column('conversations', sa.Column('short_id', sa.String(), nullable=True))
    if 'resolved_at' not in columns:
        op.add_column('conversations', sa.Column('resolved_at', sa.DateTime(), nullable=True))
    if 'reopen_count' not in columns:
        op.add_column('conversations', sa.Column('reopen_count', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('conversations', 'reopen_count')
    op.drop_column('conversations', 'resolved_at')
    op.drop_column('conversations', 'short_id')
