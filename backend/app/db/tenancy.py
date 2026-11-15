"""Row-level tenant isolation for the ORM.

Every tenant-owned table carries ``tenant_id``. Isolation is enforced centrally
instead of relying on each query remembering a ``.filter(tenant_id == ...)``:

* ``TenantSession`` picks its tenant up from ``session.info["tenant_id"]`` (set
  explicitly by the auth dependencies) or from the ``current_tenant`` context
  variable (inherited by helper sessions, background tasks and threads that are
  spawned from an authenticated request / WebSocket).
* A ``do_orm_execute`` hook appends ``WHERE tenant_id = :tenant`` to every
  SELECT / UPDATE / DELETE on a tenant-owned model, including joins and
  eager loads, so a forgotten filter cannot leak another tenant's rows.
* A ``before_flush`` hook stamps new rows with the session's tenant and refuses
  to write a row for a different tenant.

A session with NO tenant context is unscoped. That is deliberate and limited to
system work (login lookup, migrations, maintenance scripts, and the explicit
``skip_tenant_filter`` execution option used for cross-tenant uniqueness checks).
"""

from __future__ import annotations

from contextvars import ContextVar

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

DEFAULT_TENANT_ID = "default"

current_tenant: ContextVar[str | None] = ContextVar("current_tenant", default=None)
TENANT_MODELS: list[type] = []   # filled by app.db.models


class TenantSession(Session):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "tenant_id" not in self.info:
            tid = current_tenant.get()
            if tid:
                self.info["tenant_id"] = tid


def bind_session(db: Session, tenant_id: str | None) -> None:
    """Scope *db* (and everything spawned from this context) to *tenant_id*."""
    db.info["tenant_id"] = tenant_id
    current_tenant.set(tenant_id)


def _criteria(model: type, tid: str):
    # IMPORTANT: ``tid`` must be a CLOSURE variable of the lambda. SQLAlchemy caches
    # compiled lambdas per code location and extracts closure variables as bound
    # parameters on every execution; a default argument (``lambda cls, t=tid: ...``)
    # is NOT tracked, so the first tenant's id would be baked in and every later
    # request would be filtered by the wrong tenant (see test_filter_follows_tenant_across_requests).
    return with_loader_criteria(model, lambda cls: cls.tenant_id == tid, include_aliases=True)


@event.listens_for(Session, "do_orm_execute")
def _scope_statement(state) -> None:
    tid = state.session.info.get("tenant_id")
    if not tid or state.execution_options.get("skip_tenant_filter"):
        return
    if not (state.is_select or state.is_update or state.is_delete):
        return
    state.statement = state.statement.options(*[_criteria(model, tid) for model in TENANT_MODELS])


@event.listens_for(Session, "before_flush")
def _stamp_new_rows(session: Session, flush_context, instances) -> None:
    tid = session.info.get("tenant_id")
    for obj in session.new:
        if not isinstance(obj, tuple(TENANT_MODELS)):
            continue
        if getattr(obj, "tenant_id", None) in (None, ""):
            obj.tenant_id = tid or DEFAULT_TENANT_ID
        elif tid and obj.tenant_id != tid:
            raise RuntimeError(f"Cross-tenant write blocked: {type(obj).__name__} for {obj.tenant_id!r} in tenant {tid!r}")
