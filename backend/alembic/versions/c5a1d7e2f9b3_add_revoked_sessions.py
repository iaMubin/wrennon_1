"""add revoked_sessions deny-list for customer session tokens

Revision ID: c5a1d7e2f9b3
Revises: e9b3c6a1d4f8
"""
from alembic import op
import sqlalchemy as sa

revision = "c5a1d7e2f9b3"
down_revision = "e9b3c6a1d4f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "revoked_sessions",
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("revoked_by", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index(op.f("ix_revoked_sessions_revoked_at"), "revoked_sessions", ["revoked_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_revoked_sessions_revoked_at"), table_name="revoked_sessions")
    op.drop_table("revoked_sessions")
