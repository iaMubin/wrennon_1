"""Resolve which tenant a public (unauthenticated) caller belongs to."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Tenant
from app.db.tenancy import DEFAULT_TENANT_ID

TENANT_KEY_HEADER = "X-Wrennon-Tenant-Key"


def resolve_public_tenant(db: Session, tenant_key: str | None) -> str:
    """Tenant id for a storefront widget / help-center call.

    A request carrying a key must match an active tenant (unknown keys are
    rejected, never silently mapped to the default tenant). A request with no key
    belongs to the built-in default tenant, unless ALLOW_DEFAULT_TENANT=false.
    """
    if tenant_key:
        tenant = db.query(Tenant).filter_by(public_key=tenant_key[:80]).first()
        if not tenant or not tenant.is_active:
            raise HTTPException(status_code=403, detail="Unknown or inactive store")
        return tenant.id
    if not settings.allow_default_tenant:
        raise HTTPException(status_code=400, detail=f"Missing {TENANT_KEY_HEADER}")
    return DEFAULT_TENANT_ID
