"""Authorization helpers: who may see / act on which conversation.

Model
-----
* Agents with ``view_all_conversations`` (managers and admins by default) see
  everything.
* Everyone else sees the unclaimed queue (no ``handled_by`` and no
  ``assigned_agent``), conversations they own (handled / assigned), and
  conversations where a colleague @-mentioned them in an internal note.
* ``RESTRICT_AGENT_VISIBILITY=false`` restores the old "every agent sees
  everything" behaviour for very small teams.

Every per-conversation endpoint goes through ``get_conversation_or_404`` and
every listing through ``scope_conversations`` so the rule lives in one place.
Unauthorised access returns 404 (not 403) so conversation ids are not an oracle.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy import and_, exists, or_
from sqlalchemy.orm import Query, Session

from app.auth.dependencies import get_current_agent
from app.config import settings
from app.db.models import Agent, Conversation, Message


def can_view_all(agent: Agent) -> bool:
    return (not settings.restrict_agent_visibility) or agent.has_permission("view_all_conversations")


def _mentioned(agent: Agent):
    return exists().where(
        Message.conversation_id == Conversation.id,
        Message.sender == "agent_internal",
        Message.content.like(f"%@{agent.username}%"),
    )


def scope_conversations(q: Query, agent: Agent) -> Query:
    """Restrict a Conversation query to what *agent* may see."""
    if can_view_all(agent):
        return q
    return q.filter(
        or_(
            and_(Conversation.handled_by.is_(None), Conversation.assigned_agent.is_(None)),
            Conversation.handled_by == agent.username,
            Conversation.assigned_agent == agent.username,
            _mentioned(agent),
        )
    )


def can_access_conversation(db: Session, agent: Agent, conversation: Conversation) -> bool:
    if can_view_all(agent):
        return True
    return (
        db.query(Conversation.id)
        .filter(Conversation.id == conversation.id)
        .filter(
            or_(
                and_(Conversation.handled_by.is_(None), Conversation.assigned_agent.is_(None)),
                Conversation.handled_by == agent.username,
                Conversation.assigned_agent == agent.username,
                _mentioned(agent),
            )
        )
        .first()
        is not None
    )


def get_conversation_or_404(db: Session, agent: Agent, session_id: str, *, options=()) -> Conversation:
    q = db.query(Conversation).filter(Conversation.session_id == session_id)
    for o in options:
        q = q.options(o)
    conversation = q.first()
    if conversation is None or not can_access_conversation(db, agent, conversation):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def require_permission(name: str):
    """Dependency factory: 403 unless the current agent holds permission *name*."""

    def _dep(agent: Agent = Depends(get_current_agent)) -> Agent:
        if not agent.has_permission(name):
            raise HTTPException(status_code=403, detail=f"Missing permission: {name}")
        return agent

    return _dep
