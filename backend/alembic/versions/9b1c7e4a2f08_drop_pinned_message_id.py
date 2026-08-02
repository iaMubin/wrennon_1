"""Drop dead pinned_message_id column from Conversation

pinned_message_id was an earlier single-pin-per-conversation design that
was superseded by Message.is_pinned (per-message, multiple pins) in
f3b12c285d84. It was left behind, unused by any application code —
this migration removes it so the schema has one source of truth for
pin state instead of two.

Revision ID: 9b1c7e4a2f08
Revises: 7a2d4e91c3f6
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b1c7e4a2f08'
down_revision: Union[str, Sequence[str], None] = '7a2d4e91c3f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.drop_column('pinned_message_id')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pinned_message_id', sa.String(), nullable=True))
