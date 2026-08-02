"""add token_version to agent

Revision ID: a1c9f3e7d2b4
Revises: b4e7940a93ff
Create Date: 2026-07-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c9f3e7d2b4'
down_revision: Union[str, Sequence[str], None] = 'b4e7940a93ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    token_version replaces the old approach of embedding a fragment of
    the agent's password hash directly into the JWT payload to detect
    "was this token issued before the last password change". JWTs are
    signed but not encrypted, so any part of a password hash placed in
    one is readable by whoever holds the token — a plain counter avoids
    leaking anything about the password while doing the same job.
    Existing rows are backfilled to 1 so already-issued tokens (which
    predate this column and therefore have no "tv" claim) don't need to
    be force-invalidated by this migration itself.
    """
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns_agents = [c['name'] for c in inspector.get_columns('agents')]
    if 'token_version' not in columns_agents:
        op.add_column('agents', sa.Column('token_version', sa.Integer(), nullable=False, server_default='1'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('agents', 'token_version')
