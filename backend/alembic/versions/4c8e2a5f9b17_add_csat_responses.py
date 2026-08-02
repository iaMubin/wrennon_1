"""Add csat_responses table

Revision ID: 4c8e2a5f9b17
Revises: 9b1c7e4a2f08
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4c8e2a5f9b17'
down_revision: Union[str, Sequence[str], None] = '9b1c7e4a2f08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'csat_responses',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('conversation_id', sa.String(), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('conversation_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('csat_responses')
