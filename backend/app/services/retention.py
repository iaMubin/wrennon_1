"""Automatic data retention: delete RESOLVED conversations (and everything hanging off them: messages,
scorecards, CSAT, KB-gap rows, uploads, customer-token deny-listing) that have been idle longer than the
configured window.

Why this exists: chat text carries names, emails, phones and addresses. Keeping it forever turns every future
database leak into a leak of the whole history ("storage limitation": GDPR Art. 5(1)(e); a sound practice under
any data-protection law). OFF by default (CONVERSATION_RETENTION_DAYS=0); once enabled it runs once a day,
cluster-wide, in batches. Open conversations and conversations in an active human handoff are never touched.
"""

from __future__ import annotations

import datetime

from app.logger import logger

BATCH = 200
MAX_PER_RUN = 5000


def purge_resolved_conversations(days: int, dry_run: bool = False, actor: str = "system:retention") -> int:
    """Delete resolved conversations idle for more than *days*. Returns how many were (or, with dry_run,
    would be) deleted. Unscoped by design: retention applies to every tenant."""
    from app.db.models import AuditLog, Conversation
    from app.db.session import SessionLocal
    from app.services.erasure import erase_conversations
    from app.services.uploads import UPLOAD_DIR

    if days < 30:
        raise ValueError("retention window must be at least 30 days")
    cutoff = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(days=days)
    total = 0
    with SessionLocal() as db:
        eligible = db.query(Conversation.id).filter(
            Conversation.resolved.is_(True), Conversation.handoff_active.is_(False), Conversation.updated_at < cutoff
        )
        if dry_run:
            total = eligible.count()
        while not dry_run and total < MAX_PER_RUN:
            ids = [row[0] for row in eligible.order_by(Conversation.updated_at).limit(BATCH).all()]
            if not ids:
                break
            erase_conversations(db, ids, upload_dir=UPLOAD_DIR, actor=actor)
            db.add(AuditLog(actor_username=actor, action="retention_purge", details=f"deleted={len(ids)} older_than_days={days}"))
            db.commit()
            total += len(ids)
    logger.info(f"Retention: {'would delete' if dry_run else 'deleted'} {total} resolved conversation(s) idle > {days} days")
    return total
