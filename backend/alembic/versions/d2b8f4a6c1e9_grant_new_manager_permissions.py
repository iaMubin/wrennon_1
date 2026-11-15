"""grant view_all_conversations / view_customers to managers with explicit permission lists

Managers with an EMPTY list already get them through Agent.has_permission's
fallback. Managers whose list was customised would otherwise lose visibility
the moment conversation-level authorization is enforced.

Revision ID: d2b8f4a6c1e9
Revises: c5a1d7e2f9b3
"""
import json

from alembic import op
import sqlalchemy as sa

revision = "d2b8f4a6c1e9"
down_revision = "c5a1d7e2f9b3"
branch_labels = None
depends_on = None

NEW = ["view_all_conversations", "view_customers"]


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, permissions FROM agents WHERE role = 'manager'")).fetchall()
    for agent_id, raw in rows:
        try:
            perms = json.loads(raw or "[]")
        except ValueError:
            continue
        if not perms:
            continue
        merged = perms + [p for p in NEW if p not in perms]
        conn.execute(sa.text("UPDATE agents SET permissions = :p WHERE id = :i"), {"p": json.dumps(merged), "i": agent_id})


def downgrade() -> None:
    pass
