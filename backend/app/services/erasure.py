"""Single source of truth for finding and permanently erasing a data subject's records.

Used by both DELETE /api/admin/customer-data and scripts/purge_old_conversations.py so the
two can never drift apart again (the purge script and the endpoint both used to miss
csat_responses, which violates a FK on Postgres, and neither removed uploaded files).
"""
from __future__ import annotations

import os
import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    AnalyticsScorecard, Conversation, CSATResponse, KnowledgeGap, Message,
)
from app.logger import logger

_UPLOAD_REF = re.compile(r"/uploads/([0-9a-fA-F-]{36}\.[A-Za-z0-9]{2,5})")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def extract_email(text: str) -> str | None:
    m = _EMAIL_RE.search(text or "")
    return m.group(0).lower() if m else None


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def find_conversations_for_email(db: Session, email: str) -> list[Conversation]:
    """Conversations tied to an email by the stored column OR because the customer
    typed the address in a message (customer_email alone was historically never
    populated, which made export/erasure silently find nothing)."""
    needle = email.lower().strip()
    by_column = db.query(Conversation.id).filter(func.lower(Conversation.customer_email) == needle)
    by_content = (
        db.query(Message.conversation_id)
        .filter(Message.sender == "human")
        .filter(func.lower(Message.content).like(f"%{_like_escape(needle)}%", escape="\\"))
    )
    ids = {r[0] for r in by_column.all()} | {r[0] for r in by_content.all()}
    if not ids:
        return []
    return db.query(Conversation).filter(Conversation.id.in_(ids)).all()


def erase_conversations(db: Session, conversation_ids: list[str], upload_dir: str | None = None, actor: str | None = None) -> int:
    """Hard-delete conversations plus every dependent row, in FK-safe order, and the
    uploaded files they reference. Caller commits.

    Also (a) removes each conversation's per-session upload directory and (b) puts its
    session id on the token deny-list, otherwise the customer's still-valid 72h token
    could silently re-create the conversation after the erase."""
    if not conversation_ids:
        return 0

    from app.auth.sessions import revoke_session
    from app.services.uploads import delete_session_uploads

    for (sid,) in db.query(Conversation.session_id).filter(Conversation.id.in_(conversation_ids)).all():
        revoke_session(db, sid, actor, "gdpr_erase")
        delete_session_uploads(sid)

    # Collect uploaded-file references before the messages are gone.
    files: set[str] = set()
    for (content,) in db.query(Message.content).filter(Message.conversation_id.in_(conversation_ids)).all():
        files.update(_UPLOAD_REF.findall(content or ""))

    # Break the self-referencing merge FK (merged_into_id) pointing at rows we delete.
    db.query(Conversation).filter(Conversation.merged_into_id.in_(conversation_ids)).update(
        {Conversation.merged_into_id: None}, synchronize_session=False
    )
    for model in (Message, AnalyticsScorecard, KnowledgeGap, CSATResponse):
        db.query(model).filter(model.conversation_id.in_(conversation_ids)).delete(synchronize_session=False)
    db.query(Conversation).filter(Conversation.id.in_(conversation_ids)).delete(synchronize_session=False)

    if upload_dir:
        for name in files:
            path = os.path.join(upload_dir, os.path.basename(name))  # basename: no traversal
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError as e:
                logger.warning(f"Could not delete uploaded file {name}: {e}")
    return len(conversation_ids)
