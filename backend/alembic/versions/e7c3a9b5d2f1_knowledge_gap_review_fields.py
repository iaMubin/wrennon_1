"""knowledge_gaps: reviewer + published text

Revision ID: e7c3a9b5d2f1
Revises: d2b8f4a6c1e9
"""
from alembic import op
import sqlalchemy as sa

revision = "e7c3a9b5d2f1"
down_revision = "d2b8f4a6c1e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_gaps") as b:
        b.add_column(sa.Column("reviewed_by", sa.String(), nullable=True))
        b.add_column(sa.Column("reviewed_at", sa.DateTime(), nullable=True))
        b.add_column(sa.Column("published_text", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("knowledge_gaps") as b:
        b.drop_column("published_text")
        b.drop_column("reviewed_at")
        b.drop_column("reviewed_by")
