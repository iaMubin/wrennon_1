"""
Agent-facing REST endpoints: login, and fetching the two dashboard
sections (needs-attention conversations, and the full conversation
list). Live updates after the page loads come through /ws/agent —
these REST routes are for the initial page load only.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Body, status, Response, Form, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
import pyotp
from app.services.qa import process_resolved_conversation_tasks
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import or_

from app.auth.dependencies import get_current_agent
from app.auth.security import create_access_token, verify_password
from app.config import settings
from app.logger import logger
import re
from app.services.mock_apis import get_order_status, get_order_by_email, get_customer_info
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
    totp_code: str | None = Form(None),
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
        logger.debug(f"Redis fallback during login for {form_data.username}: {e}")

    agent = db.query(Agent).filter(
        or_(Agent.username == form_data.username, Agent.employee_id == form_data.username)
    ).first()
    
    if not agent or not verify_password(form_data.password, agent.password_hash):
        try:
            r = get_redis()
            await r.incr(rate_key)
            await r.expire(rate_key, 60)
        except Exception as e:
            logger.debug(f"Redis fallback during rate limit increment: {e}")
            
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
        
    if agent.totp_enabled:
        if not totp_code:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="2FA_REQUIRED"
            )
        totp = pyotp.TOTP(agent.totp_secret)
        if not totp.verify(totp_code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid 2FA code"
            )

    # Reset rate limit on success
    try:
        r = get_redis()
        await r.delete(rate_key)
    except Exception as e:
        logger.debug(f"Redis fallback during rate limit reset: {e}")
        
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
    
    return {"access_token": token, "token_type": "bearer", "role": agent.role}  # nosec B105


class VerifyTOTPRequest(BaseModel):
    code: str

@router.post("/agent/2fa/setup")
def setup_2fa(
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> dict:
    secret = pyotp.random_base32()
    agent.totp_secret = secret
    agent.totp_enabled = False
    db.commit()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=agent.username, issuer_name="Wrennon")
    return {"uri": uri}

@router.post("/agent/2fa/verify")
def verify_2fa(
    payload: VerifyTOTPRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> dict:
    if not agent.totp_secret:
        raise HTTPException(status_code=400, detail="2FA setup not initiated")
    totp = pyotp.TOTP(agent.totp_secret)
    if not totp.verify(payload.code):
        raise HTTPException(status_code=400, detail="Invalid 2FA code")
    agent.totp_enabled = True
    
    audit = AuditLog(actor_username=agent.username, action="enable_2fa")
    db.add(audit)
    db.commit()
    return {"status": "success"}

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
    convs = db.query(Conversation).options(selectinload(Conversation.messages)).outerjoin(
        Message, Conversation.id == Message.conversation_id
    ).filter(
        Conversation.resolved == False,
        or_(
            Conversation.handled_by == agent.username,
            (Message.sender == "agent_internal") & (Message.content.like(f"%@{agent.username}%"))
        )
    ).distinct().order_by(Conversation.updated_at.desc()).all()
    
    results = []
    for c in convs:
        summary = _conversation_summary(c)
        summary["is_mentioned"] = (c.handled_by != agent.username)
        results.append(summary)
        
    return results


@router.get("/agent/list")
async def list_agents(
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_agent)
) -> list[dict]:
    agents = db.query(Agent).all()
    return [{"username": a.username, "full_name": a.full_name, "role": a.role} for a in agents]

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
    agent_roles = {a.username: a.role for a in db.query(Agent).all()}
    
    return {
        "pinned_message_id": conversation.pinned_message_id,
        "messages": [
            {
                "id": m.id, 
                "sender": m.sender, 
                "content": m.content, 
                "created_at": m.created_at.isoformat(), 
                "author_username": m.author_username,
                "author_role": agent_roles.get(m.author_username, "agent") if m.author_username else "agent"
            }
            for m in conversation.messages
        ]
    }


@router.post("/agent/conversations/{session_id}/resolve")
def resolve_conversation(
    session_id: str,
    background_tasks: BackgroundTasks,
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

    background_tasks.add_task(process_resolved_conversation_tasks, conversation.id)
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
        
    if msg.author_username and msg.author_username != agent.username and agent.role != "admin":
        raise HTTPException(status_code=403, detail="You can only delete your own notes")
        
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
    """Retrieve order and customer context for a conversation.
    Prioritizes order ID in messages, then stored customer email."""
    conversation = db.query(Conversation).filter_by(session_id=session_id).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # helper
    def build_response(order, source):
        resp = {"source": source}
        if order:
            resp["order"] = order
            # Always ensure the customer info matches the order's email if possible
            cust = None
            if "email" in order:
                cust = get_customer_info(email=order["email"])
            elif conversation.customer_email:
                cust = get_customer_info(email=conversation.customer_email)
            resp["customer"] = cust
        else:
            if conversation.customer_email:
                resp["customer"] = get_customer_info(email=conversation.customer_email)
        return resp
        
    messages = (
        db.query(Message)
        .filter_by(conversation_id=conversation.id)
        .filter(Message.sender == "human")
        .order_by(Message.created_at.desc())
        .limit(20)
        .all()
    )
    
    # 1. Scan for explicit Order ID first (highest priority)
    for msg in messages:
        order_match = re.search(r'(?:order\s*[#:]?\s*|#)(\d{4,})', msg.content, re.IGNORECASE)
        if order_match:
            order = get_order_status(order_match.group(1))
            if order:
                return build_response(order, "message_scan")
    
    # 2. Check for explicit email in messages
    for msg in messages:
        email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', msg.content)
        if email_match:
            order = get_order_by_email(email_match.group(0))
            if order:
                resp = build_response(order, "email_scan")
                resp["customer"] = get_customer_info(email=email_match.group(0))
                return resp
                
    # 3. Use logged-in customer_email (or fallback)
    if conversation.customer_email:
        order = get_order_by_email(conversation.customer_email)
        return build_response(order, "customer_email")
        
    # 4. Use legacy stored last_order_id
    if conversation.last_order_id:
        order = get_order_status(conversation.last_order_id)
        if order:
            return build_response(order, "conversation_state")
            
    from fastapi.responses import Response as FastAPIResponse
    return FastAPIResponse(status_code=204)



def _conversation_summary(c: Conversation) -> dict:
    last_msg_obj = c.messages[-1] if c.messages else None
    last_message = last_msg_obj.content if last_msg_obj else None
    last_message_is_internal = (last_msg_obj.sender == 'agent_internal') if last_msg_obj else False
    
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
        "last_message_is_internal": last_message_is_internal,
        "updated_at": c.updated_at.isoformat(),
        "sentiment": getattr(c, "sentiment", None),
        "language": getattr(c, "language", None),
    }
