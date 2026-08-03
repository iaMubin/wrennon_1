"""Add author_username to messages

Revision ID: 6d7c2d9e4f31
Revises: c030af5dab25
Create Date: 2026-07-16 16:25:30.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6d7c2d9e4f31'
down_revision: Union[str, Sequence[str], None] = 'c030af5dab25'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('messages', sa.Column('author_username', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('messages', 'author_username')
