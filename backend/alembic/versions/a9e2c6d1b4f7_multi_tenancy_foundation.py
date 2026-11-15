"""multi-tenancy foundation: tenants table + tenant_id on every tenant-owned table

All existing rows are assigned to the built-in tenant "default", so a
single-merchant deployment keeps working unchanged (its Pinecone vectors stay in
the default namespace, its Shopify credentials stay in the environment).

Revision ID: a9e2c6d1b4f7
Revises: f3d9b1c7a8e2
"""
import secrets
import datetime

from alembic import op
import sqlalchemy as sa

revision = "a9e2c6d1b4f7"
down_revision = "f3d9b1c7a8e2"
branch_labels = None
depends_on = None

TABLES = ["conversations", "agents", "audit_logs", "knowledge_gaps", "system_settings",
          "canned_responses", "saved_views", "api_keys"]


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("public_key", sa.String(), nullable=False),
        sa.Column("shopify_store_url", sa.String(), nullable=True),
        sa.Column("shopify_token_enc", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)
    op.create_index("ix_tenants_public_key", "tenants", ["public_key"], unique=True)
    op.get_bind().execute(
        sa.text("INSERT INTO tenants (id, slug, name, public_key, is_active) VALUES ('default', 'default', 'Default', :pk, :active)"),
        {"pk": "wt_" + secrets.token_urlsafe(18), "active": True},
    )

    for table in TABLES:
        with op.batch_alter_table(table) as b:
            b.add_column(sa.Column("tenant_id", sa.String(), nullable=False, server_default="default"))
            b.create_index(f"ix_{table}_tenant_id", ["tenant_id"])
            b.create_foreign_key(f"fk_{table}_tenant", "tenants", ["tenant_id"], ["id"])

    # Settings are now unique per tenant, not globally.
    op.drop_index("ix_system_settings_key", table_name="system_settings")
    op.create_index("ix_system_settings_key", "system_settings", ["key"], unique=False)
    with op.batch_alter_table("system_settings") as b:
        b.create_unique_constraint("uq_system_settings_tenant_key", ["tenant_id", "key"])


def downgrade() -> None:
    with op.batch_alter_table("system_settings") as b:
        b.drop_constraint("uq_system_settings_tenant_key", type_="unique")
    op.drop_index("ix_system_settings_key", table_name="system_settings")
    op.create_index("ix_system_settings_key", "system_settings", ["key"], unique=True)
    for table in reversed(TABLES):
        with op.batch_alter_table(table) as b:
            b.drop_constraint(f"fk_{table}_tenant", type_="foreignkey")
            b.drop_index(f"ix_{table}_tenant_id")
            b.drop_column("tenant_id")
    op.drop_index("ix_tenants_public_key", table_name="tenants")
    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")
