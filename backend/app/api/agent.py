"""
Agent-facing REST endpoints: login, and fetching the two dashboard
sections (needs-attention conversations, and the full conversation
list). Live updates after the page loads come through /ws/agent —
these REST routes are for the initial page load only.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.auth.dependencies import get_current_agent
from app.auth.security import create_access_token, verify_password
from app.config import settings
from app.db.models import Agent, Conversation, Message, AuditLog
from app.db.session import get_db
from app.realtime.connection_manager import manager

router = APIRouter()


@router.post("/agent/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
) -> dict:
    agent = db.query(Agent).filter(
        or_(Agent.username == form_data.username, Agent.employee_id == form_data.username)
    ).first()
    
    if not agent or not verify_password(form_data.password, agent.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    token = create_access_token(subject=agent.username)
    
    # Audit log
    audit = AuditLog(
        actor_username=agent.username,
        action="login"
    )
    db.add(audit)
    db.commit()
    
    return {"access_token": token, "token_type": "bearer", "role": agent.role}


@router.get("/agent/conversations/needs-attention")
def needs_attention(
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> list[dict]:
    conversations = (
        db.query(Conversation)
        .filter_by(handoff_active=True, resolved=False)
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    return [_conversation_summary(c) for c in conversations]


@router.get("/agent/conversations/active")
def active_chats(
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> list[dict]:
    conversations = (
        db.query(Conversation)
        .filter_by(resolved=False)
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    return [_conversation_summary(c) for c in conversations]


@router.get("/agent/conversations")
def all_conversations(
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> list[dict]:
    conversations = (
        db.query(Conversation)
        .order_by(Conversation.updated_at.desc())
        .limit(50)
        .all()
    )
    return [_conversation_summary(c) for c in conversations]


@router.get("/agent/conversations/{session_id}/messages")
def conversation_messages(
    session_id: str,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> list[dict]:
    """Full message history for one conversation — used when an agent
    clicks into a conversation to see what's been said so far."""
    conversation = db.query(Conversation).filter_by(session_id=session_id).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return [
        {"sender": m.sender, "content": m.content, "created_at": m.created_at.isoformat()}
        for m in conversation.messages
    ]


@router.post("/agent/conversations/{session_id}/resolve")
def resolve_conversation(
    session_id: str,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> dict:
    conversation = db.query(Conversation).filter_by(session_id=session_id).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation.resolved = True
    conversation.resolved_at = datetime.datetime.utcnow()
    conversation.handoff_active = False
    conversation.handled_by = agent.username
    db.commit()
    return {"status": "resolved", "session_id": session_id}


def _conversation_summary(c: Conversation) -> dict:
    last_message = c.messages[-1].content if c.messages else None
    
    stage = "AI"
    if c.resolved:
        stage = "Resolved"
    elif c.handoff_active:
        stage = "Human Agent"

    return {
        "session_id": c.session_id,
        "short_id": getattr(c, "short_id", "CUST-XXXX"),
        "customer_email": c.customer_email,
        "handoff_active": c.handoff_active,
        "resolved": c.resolved,
        "reopen_count": getattr(c, "reopen_count", 0),
        "stage": stage,
        "handled_by": getattr(c, "handled_by", None),
        "last_message": last_message,
        "updated_at": c.updated_at.isoformat(),
    }
