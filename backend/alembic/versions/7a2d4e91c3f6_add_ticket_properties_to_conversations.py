"""Add ticket properties (priority, tags, assigned_agent) to Conversation

Revision ID: 7a2d4e91c3f6
Revises: f3b12c285d84
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a2d4e91c3f6'
down_revision: Union[str, Sequence[str], None] = 'f3b12c285d84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('priority', sa.String(), nullable=False, server_default='normal'))
        batch_op.add_column(sa.Column('tags', sa.Text(), nullable=False, server_default='[]'))
        batch_op.add_column(sa.Column('assigned_agent', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.drop_column('assigned_agent')
        batch_op.drop_column('tags')
        batch_op.drop_column('priority')
