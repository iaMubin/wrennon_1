"""
Agent-facing REST endpoints: login, and fetching the two dashboard
sections (needs-attention conversations, and the full conversation
list). Live updates after the page loads come through /ws/agent —
these REST routes are for the initial page load only.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Body, status, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import or_

from app.auth.dependencies import get_current_agent
from app.auth.security import create_access_token, verify_password
from app.config import settings
import re
from app.services.mock_apis import get_order_status, get_order_by_email
from app.db.models import Agent, Conversation, Message, AuditLog
from app.db.session import get_db
from app.realtime.connection_manager import manager
from app.config import settings
import re
from app.services.mock_apis import get_order_status, get_order_by_email
import redis.asyncio as redis

# Create a Redis client for rate limiting
_redis_client = None

class DummyRedis:
    async def get(self, key): return None
    async def setex(self, key, time, value): pass
    async def set(self, key, value, ex=None, nx=None): pass
    async def incr(self, key): return 1
    async def expire(self, key, time): pass
    async def delete(self, key): pass

def get_redis():
    global _redis_client
    if _redis_client is None:
        if settings.redis_url.startswith("memory://"):
            _redis_client = DummyRedis()
        else:
            _redis_client = redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=1.0, socket_timeout=1.0)
    return _redis_client

router = APIRouter()


@router.post("/agent/login")
async def login(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
) -> dict:
    # Rate Limiting
    rate_key = f"login_attempts:{form_data.username}"
    try:
        r = get_redis()
        attempts = await r.get(rate_key)
        if attempts and int(attempts) >= 5:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed login attempts. Please try again later.",
            )
    except Exception as e:
        # Fallback if Redis is down or times out
        pass

    agent = db.query(Agent).filter(
        or_(Agent.username == form_data.username, Agent.employee_id == form_data.username)
    ).first()
    
    if not agent or not verify_password(form_data.password, agent.password_hash):
        try:
            r = get_redis()
            await r.incr(rate_key)
            await r.expire(rate_key, 60)
        except Exception:
            pass
            
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
        
    # Reset rate limit on success
    try:
        r = get_redis()
        await r.delete(rate_key)
    except Exception:
        pass
        
    token = create_access_token(subject=agent.username, pwd_hash=agent.password_hash)
    
    # Audit log
    audit = AuditLog(
        actor_username=agent.username,
        action="login"
    )
    db.add(audit)
    db.commit()
    
    # Set httpOnly cookie
    response.set_cookie(
        key="access_token",
        value=f"Bearer {token}",
        httponly=True,
        secure=True,     # Must be True for samesite="none" (HTTPS)
        samesite="none", # Allow cross-origin requests
        max_age=60 * 60 * 24 * 7 # 7 days
    )
    
    return {"access_token": token, "token_type": "bearer", "role": agent.role}


@router.get("/agent/conversations/needs-attention")
def needs_attention(
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> list[dict]:
    conversations = (
        db.query(Conversation)
        .filter_by(handoff_active=True, resolved=False, handled_by=None)
        .options(selectinload(Conversation.messages))
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    return [_conversation_summary(c) for c in conversations]


@router.get("/agent/conversations/my-cases")
def get_my_cases(
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    convs = db.query(Conversation).filter(
        Conversation.handled_by == agent.username,
        Conversation.resolved == False
    ).order_by(Conversation.updated_at.desc()).all()
    
    return [{"session_id": c.session_id, "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(), "handoff_active": c.handoff_active, "resolved": c.resolved, "handled_by": c.handled_by, "reopen_count": c.reopen_count} for c in convs]


@router.get("/agent/conversations/active")
def active_chats(
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> list[dict]:
    conversations = (
        db.query(Conversation)
        .filter_by(resolved=False)
        .options(selectinload(Conversation.messages))
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
        .options(selectinload(Conversation.messages))
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
) -> dict:
    """Full message history for one conversation — used when an agent
    clicks into a conversation to see what's been said so far."""
    conversation = db.query(Conversation).filter_by(session_id=session_id).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "pinned_message_id": conversation.pinned_message_id,
        "messages": [
            {"id": m.id, "sender": m.sender, "content": m.content, "created_at": m.created_at.isoformat()}
            for m in conversation.messages
        ]
    }


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
    conversation.resolved_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    conversation.handoff_active = False
    conversation.handled_by = agent.username
    
    audit = AuditLog(
        actor_username=agent.username,
        action="resolve_conversation",
        target_username=session_id
    )
    db.add(audit)
    db.commit()
    return {"status": "resolved", "session_id": session_id}

@router.delete("/agent/messages/{message_id}")
def delete_internal_note(
    message_id: str,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
) -> dict:
    msg = db.query(Message).filter_by(id=message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
        
    if msg.sender != "agent_internal":
        raise HTTPException(status_code=403, detail="Only internal notes can be deleted")
        
    db.delete(msg)
    
    audit = AuditLog(
        actor_username=agent.username,
        action="delete_internal_note",
        target_username=message_id
    )
    db.add(audit)
    db.commit()
    return {"status": "deleted", "message_id": message_id}


@router.post("/agent/conversations/{session_id}/pin")
def pin_message(
    session_id: str,
    message_id: int | None = Body(None, embed=True),
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
) -> dict:
    conversation = db.query(Conversation).filter_by(session_id=session_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    # If message_id is empty/null, we unpin.
    if message_id:
        msg = db.query(Message).filter_by(id=message_id, conversation_id=conversation.id).first()
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found in this conversation")
            
    conversation.pinned_message_id = message_id or None
    db.commit()
    return {"status": "success", "pinned_message_id": conversation.pinned_message_id}


@router.get("/agent/conversations/{session_id}/order-context")
def get_order_context(
    session_id: str,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> dict | None:
    """Retrieve order context for the customer in a conversation.
    Checks last_order_id first, then scans messages for order IDs or emails."""
    conversation = db.query(Conversation).filter_by(session_id=session_id).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # Strategy 1: Use stored last_order_id
    if conversation.last_order_id:
        order = get_order_status(conversation.last_order_id)
        if order:
            return {"order": order, "source": "conversation_state"}
    
    # Strategy 2: Use customer email if available
    if conversation.customer_email:
        order = get_order_by_email(conversation.customer_email)
        if order:
            return {"order": order, "source": "customer_email"}
    
    # Strategy 3: Scan messages for order ID patterns or email
    messages = (
        db.query(Message)
        .filter_by(conversation_id=conversation.id)
        .filter(Message.sender == "human")
        .order_by(Message.created_at.desc())
        .limit(20)
        .all()
    )
    
    for msg in messages:
        # Look for order ID patterns: #1001, order 1001, order #1001, order: 1001
        order_match = re.search(r'(?:order\s*[#:]?\s*|#)(\d{4,})', msg.content, re.IGNORECASE)
        if order_match:
            order = get_order_status(order_match.group(1))
            if order:
                return {"order": order, "source": "message_scan"}
        
        # Look for email patterns
        email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', msg.content)
        if email_match:
            order = get_order_by_email(email_match.group(0))
            if order:
                return {"order": order, "source": "email_scan"}
    
    # No order context found
    from fastapi.responses import Response as FastAPIResponse
    return FastAPIResponse(status_code=204)


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
        "sentiment": getattr(c, "sentiment", None),
        "language": getattr(c, "language", None),
    }
