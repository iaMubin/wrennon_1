"""Public REST API (``/api/v1``), authenticated with scoped API keys.

Hardening vs. the first version:
* every route demands a specific scope (default key = read-only);
* internal notes / system messages are only visible with ``notes:read``;
* customer-visible messages need ``messages:send`` AND an active human
  handoff, are length-bounded, marker-neutralised and audit-logged;
* keys expire / can be revoked, and every write is attributed to the key in the
  audit log (actor ``api:<key id>``).
"""

import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import require_scope
from app.db.models import ApiKey, Conversation, Message
from app.db.session import get_db
from app.limiter import limiter
from app.security.sanitize import MAX_AGENT_MESSAGE_CHARS, sanitize_customer_text
from app.services.audit import add_audit
from app.services.uploads import resign_text

router = APIRouter()

_INTERNAL_SENDERS = ("agent_internal", "system")


class PublicMessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=MAX_AGENT_MESSAGE_CHARS)
    is_internal: bool = False


def _find(db: Session, ref: str) -> Conversation:
    ref = ref[:64]
    conv = db.query(Conversation).filter_by(short_id=ref).first() or db.query(Conversation).filter_by(id=ref).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


def _actor(key: ApiKey) -> str:
    return f"api:{key.id}"


@router.get("/conversations")
@limiter.limit("60/minute")
def list_conversations(
    request: Request,
    status: Optional[str] = Query(None, pattern="^(open|resolved)$"),
    assigned_agent: Optional[str] = Query(None, max_length=80),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100_000),
    api_key: ApiKey = Depends(require_scope("conversations:read")),
    db: Session = Depends(get_db),
):
    query = db.query(Conversation)
    if status:
        query = query.filter(Conversation.resolved == (status == "resolved"))
    if assigned_agent:
        query = query.filter(Conversation.assigned_agent == assigned_agent)   # was assigned_agent_id: no such column

    conversations = query.order_by(Conversation.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "data": [
            {
                "id": c.id,
                "short_id": c.short_id,
                "session_id": c.session_id,
                "resolved": c.resolved,
                "assigned_agent": c.assigned_agent,
                "created_at": c.created_at,
                "last_message_at": c.updated_at,
                "priority": c.priority,
            } for c in conversations
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/conversations/{short_id}")
@limiter.limit("60/minute")
def get_conversation_details(
    request: Request,
    short_id: str,
    api_key: ApiKey = Depends(require_scope("conversations:read")),
    db: Session = Depends(get_db),
):
    conv = _find(db, short_id)
    q = db.query(Message).filter_by(conversation_id=conv.id)
    if "notes:read" not in api_key.scope_list:
        q = q.filter(Message.sender.notin_(_INTERNAL_SENDERS))
    messages = q.order_by(Message.created_at.asc()).limit(1000).all()

    return {
        "id": conv.id,
        "short_id": conv.short_id,
        "session_id": conv.session_id,
        "resolved": conv.resolved,
        "assigned_agent": conv.assigned_agent,
        "created_at": conv.created_at,
        "last_message_at": conv.updated_at,
        "priority": conv.priority,
        "intent_category": conv.intent_category,
        "sentiment": conv.sentiment,
        "csat_score": conv.csat_response.rating if conv.csat_response else None,
        "messages": [
            {
                "id": m.id,
                "type": m.sender,
                "content": resign_text(m.content),
                "created_at": m.created_at,
                "is_internal": m.sender in _INTERNAL_SENDERS,
                "sender_name": m.author_username,
            } for m in messages
        ],
    }


@router.post("/conversations/{short_id}/messages")
@limiter.limit("30/minute")
def add_message(
    request: Request,
    short_id: str,
    payload: PublicMessageCreate,
    api_key: ApiKey = Depends(require_scope("conversations:read")),
    db: Session = Depends(get_db),
):
    needed = "notes:write" if payload.is_internal else "messages:send"
    if needed not in api_key.scope_list:
        raise HTTPException(status_code=403, detail=f"API key lacks required scope: {needed}")

    conv = _find(db, short_id)
    if conv.resolved:
        raise HTTPException(status_code=400, detail="Cannot add message to resolved conversation")
    if not payload.is_internal and not conv.handoff_active:
        # A customer-visible "agent" message injected while the AI is still handling the
        # chat would impersonate staff mid-conversation; only allowed once a human is in.
        raise HTTPException(status_code=409, detail="Customer-visible messages are only allowed during an active human handoff")

    content = sanitize_customer_text(payload.content, max_len=MAX_AGENT_MESSAGE_CHARS)
    if not content.strip():
        raise HTTPException(status_code=422, detail="Empty message")

    new_msg = Message(
        conversation_id=conv.id,
        sender="agent" if not payload.is_internal else "system",
        content=content,
        author_username="API: " + api_key.name,
    )
    db.add(new_msg)
    conv.updated_at = datetime.datetime.now(datetime.timezone.utc)
    add_audit(db, _actor(api_key), "api_internal_note" if payload.is_internal else "api_customer_message",
              conv.short_id or conv.id, details=f"key={api_key.name[:40]} len={len(content)}",
              ip=request.client.host if request.client else None)
    db.commit()
    db.refresh(new_msg)

    return {
        "id": new_msg.id,
        "type": new_msg.sender,
        "content": new_msg.content,
        "created_at": new_msg.created_at,
        "is_internal": payload.is_internal,
        "sender_name": new_msg.author_username,
    }


@router.post("/conversations/{short_id}/resolve")
@limiter.limit("30/minute")
def resolve_conversation(
    request: Request,
    short_id: str,
    api_key: ApiKey = Depends(require_scope("conversations:resolve")),
    db: Session = Depends(get_db),
):
    conv = _find(db, short_id)
    if conv.resolved:
        return {"status": "success", "message": "Already resolved"}

    conv.resolved = True
    conv.resolved_at = datetime.datetime.now(datetime.timezone.utc)
    add_audit(db, _actor(api_key), "api_resolve", conv.short_id or conv.id, details=f"key={api_key.name[:40]}",
              ip=request.client.host if request.client else None)
    db.commit()
    return {"status": "success", "message": "Conversation resolved"}
