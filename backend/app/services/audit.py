"""Single entry point for writing audit-log rows.

Keeps field lengths bounded (an attacker controls e.g. the username on a failed
login) and keeps secrets out of ``details``.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import AuditLog
from app.security.pii import redact_secrets


def add_audit(
    db: Session,
    actor: str,
    action: str,
    target: str | None = None,
    details: str | None = None,
    ip: str | None = None,
) -> AuditLog:
    """Stage an audit row on *db* (caller commits, so it lands atomically with
    the change it describes)."""
    parts = [details] if details else []
    if ip:
        parts.append(f"ip={ip}")
    row = AuditLog(
        actor_username=(actor or "unknown")[:80],
        action=action[:60],
        target_username=(target[:200] if target else None),
        details=redact_secrets("; ".join(parts))[:1000] or None,
    )
    db.add(row)
    return row


def audit_now(db: Session, *args, **kwargs) -> None:
    """Write and commit immediately (for events with no accompanying change,
    e.g. failed logins, reads of customer PII)."""
    add_audit(db, *args, **kwargs)
    db.commit()
