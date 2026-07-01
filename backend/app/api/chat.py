"""
Customer-facing REST endpoint. Only one job left here: when the
customer widget first loads, it needs the conversation history that
already happened (if this session_id has been seen before) before the
WebSocket connection takes over for everything that happens next.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import Conversation
from app.db.session import get_db

router = APIRouter()

REOPEN_WINDOW_HOURS = 72


@router.get("/chat/{session_id}/status")
def session_status(session_id: str, db: Session = Depends(get_db)) -> dict:
    """Check whether a session is still usable or expired."""
    conversation = db.query(Conversation).filter_by(session_id=session_id).first()
    if conversation is None:
        return {"status": "not_found"}

    if not conversation.resolved:
        return {"status": "active"}

    # Conversation was resolved — check if within 72-hour window
    if conversation.resolved_at:
        elapsed = datetime.datetime.utcnow() - conversation.resolved_at
        if elapsed.total_seconds() < REOPEN_WINDOW_HOURS * 3600:
            return {"status": "resolved_recent"}
        else:
            return {"status": "expired"}

    # resolved=True but no resolved_at (legacy data) — treat as expired
    return {"status": "expired"}


@router.get("/chat/{session_id}/history")
def get_history(session_id: str, db: Session = Depends(get_db)) -> list[dict]:
    conversation = db.query(Conversation).filter_by(session_id=session_id).first()
    if conversation is None:
        return []
    # sender is intentionally collapsed to "bot" for anything that
    # isn't the customer — this is where the "customer never knows it's
    # a human" rule actually gets enforced on the way out. The database
    # keeps the true sender ("ai" vs "agent") for the agent dashboard
    # and any future analytics; the customer-facing history never
    # exposes that distinction.
    return [
        {
            "sender": "user" if m.sender == "human" else "bot",
            "content": m.content,
        }
        for m in conversation.messages
        if m.sender != "system"  # Hide internal summaries from customer
    ]
