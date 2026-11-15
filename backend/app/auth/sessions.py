"""Revocation of customer session tokens (stateless JWTs, 72h by default)."""

from __future__ import annotations

import datetime

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import RevokedSession


def is_session_revoked(db: Session, session_id: str) -> bool:
    return db.get(RevokedSession, session_id) is not None


def revoke_session(db: Session, session_id: str, by: str | None, reason: str | None = None) -> None:
    """Add *session_id* to the deny-list (idempotent). Caller commits."""
    if db.get(RevokedSession, session_id) is None:
        db.add(RevokedSession(session_id=session_id, revoked_by=by, reason=(reason or "")[:200] or None))


def purge_expired_revocations(db: Session) -> int:
    """A deny-list row is only needed while a token it blocks could still be valid."""
    cutoff = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(
        hours=settings.customer_session_ttl_hours + 1
    )
    n = db.query(RevokedSession).filter(RevokedSession.revoked_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return n
