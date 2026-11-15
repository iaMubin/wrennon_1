"""api_keys: scopes, expiry, revocation record

Existing keys keep working (legacy parity: read, resolve, notes:write, messages:send)
but gain scopes so they can be narrowed; rotate them and prefer an expiry.

Revision ID: f3d9b1c7a8e2
Revises: e7c3a9b5d2f1
"""
import json

from alembic import op
import sqlalchemy as sa

revision = "f3d9b1c7a8e2"
down_revision = "e7c3a9b5d2f1"
branch_labels = None
depends_on = None

LEGACY = ["conversations:read", "conversations:resolve", "notes:write", "messages:send"]


def upgrade() -> None:
    with op.batch_alter_table("api_keys") as b:
        b.add_column(sa.Column("scopes", sa.Text(), nullable=False, server_default=json.dumps(["conversations:read"])))
        b.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("revoked_by", sa.String(), nullable=True))
    op.get_bind().execute(sa.text("UPDATE api_keys SET scopes = :s"), {"s": json.dumps(LEGACY)})


def downgrade() -> None:
    with op.batch_alter_table("api_keys") as b:
        b.drop_column("revoked_by")
        b.drop_column("revoked_at")
        b.drop_column("expires_at")
        b.drop_column("scopes")
