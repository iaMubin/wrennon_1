"""Create a tenant (merchant) and, optionally, its first admin account.

Usage:
  python scripts/create_tenant.py --slug acme --name "Acme Ltd" \
      [--admin-username acme_admin --admin-password '...' --admin-name "Acme Admin"]

Prints the tenant's PUBLIC key: put it on the storefront widget as
<script src=".../widget.js" data-tenant-key="wt_..."></script>
Shopify credentials are then set by that tenant's admin in the dashboard
(PUT /api/admin/tenant/shopify), encrypted with TENANT_SECRETS_KEY.
"""
import argparse
import re
import secrets
import sys

from app.auth.security import hash_password
from app.db.models import Agent, Tenant
from app.db.session import SessionLocal


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--admin-username")
    ap.add_argument("--admin-password")
    ap.add_argument("--admin-name", default="Administrator")
    a = ap.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,40}", a.slug):
        print("slug must be 2-41 chars of a-z 0-9 _ -", file=sys.stderr)
        return 2
    if a.admin_username and (not a.admin_password or len(a.admin_password) < 12):
        print("--admin-password (>= 12 chars) is required with --admin-username", file=sys.stderr)
        return 2

    with SessionLocal() as db:
        if db.query(Tenant).filter_by(slug=a.slug).first():
            print("tenant already exists", file=sys.stderr)
            return 1
        tenant = Tenant(id=a.slug, slug=a.slug, name=a.name, public_key="wt_" + secrets.token_urlsafe(18))
        db.add(tenant)
        db.flush()
        if a.admin_username:
            db.add(Agent(
                username=a.admin_username, full_name=a.admin_name, employee_id=f"{a.slug}-{secrets.token_hex(3)}",
                password_hash=hash_password(a.admin_password), role="admin", tenant_id=tenant.id,
            ))
        db.commit()
        print(f"tenant id      : {tenant.id}")
        print(f"public key     : {tenant.public_key}")
        print(f"pinecone ns    : {tenant.pinecone_namespace}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
