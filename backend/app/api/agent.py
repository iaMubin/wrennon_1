"""
Agent-facing REST endpoints: login, and fetching the two dashboard
sections (needs-attention conversations, and the full conversation
list). Live updates after the page loads come through /ws/agent —
these REST routes are for the initial page load only.
"""

from __future__ import annotations

import datetime
import json

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
        # If Redis is down, brute-force lockout silently fails OPEN — an
        # attacker can hammer this endpoint unthrottled until Redis comes
        # back. That's an operationally important signal, not routine
        # noise, so it's logged at WARNING (visible in production/Sentry)
        # rather than DEBUG (which would make this failure mode invisible
        # exactly when it matters most).
        logger.warning(f"Redis unavailable during login rate-limit check for {form_data.username}: {e}")

    agent = db.query(Agent).filter(
        or_(Agent.username == form_data.username, Agent.employee_id == form_data.username)
    ).first()
    
    if not agent or not verify_password(form_data.password, agent.password_hash):
        try:
            r = get_redis()
            await r.incr(rate_key)
            await r.expire(rate_key, 60)
        except Exception as e:
            logger.warning(f"Redis unavailable while recording a failed login attempt for {form_data.username}: {e}")
            
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
        # Non-critical (a stale lockout counter just lingers an extra
        # ~60s), but still worth a WARNING for consistency with the two
        # login-path Redis fallbacks above.
        logger.warning(f"Redis unavailable while clearing rate-limit counter for {agent.username}: {e}")
        
    token = create_access_token(subject=agent.username, token_version=agent.token_version)
    
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


@router.post("/agent/logout")
def logout(
    response: Response,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> dict:
    """Clears the auth cookie and revokes the token that was used to call
    this endpoint (via token_version bump), so it can't be replayed even
    if it leaked before logout. Now that agent.js relies on the cookie
    rather than a client-held copy of the JWT, "logging out" has to be a
    real server round-trip — deleting client-side state alone would leave
    the cookie (and the token inside it) valid until it expires on its own.
    """
    agent.token_version = (agent.token_version or 1) + 1
    db.commit()
    response.delete_cookie(key="access_token", samesite="none", secure=True)
    return {"status": "logged_out"}


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
        .filter(Conversation.handoff_active == True, Conversation.resolved == False, Conversation.handled_by == None)
        .filter(Conversation.messages.any())
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
        .filter(Conversation.resolved == False)
        .filter(Conversation.messages.any())
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
        .filter(Conversation.messages.any())
        .options(selectinload(Conversation.messages))
        .order_by(Conversation.updated_at.desc())
        .limit(50)
        .all()
    )
    return [_conversation_summary(c) for c in conversations]


@router.get("/agent/conversations/{session_id}")
def get_conversation(
    session_id: str,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> dict:
    """Single-conversation summary (priority/tags/assignee/stage/etc).
    Used by the dashboard to (re)hydrate the ticket properties bar when a
    conversation is opened, independent of whichever list view it was
    clicked from — the list's cached copy can be stale by the time the
    agent clicks it."""
    conversation = db.query(Conversation).filter_by(session_id=session_id).options(
        selectinload(Conversation.messages)
    ).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _conversation_summary(conversation)


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
        "messages": [
            {
                "id": m.id, 
                "sender": m.sender, 
                "content": m.content, 
                "created_at": m.created_at.isoformat(), 
                "author_username": m.author_username,
                "author_role": agent_roles.get(m.author_username, "agent") if m.author_username else "agent",
                "is_pinned": getattr(m, 'is_pinned', False)
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


VALID_PRIORITIES = {"low", "normal", "high", "urgent"}


@router.patch("/agent/conversations/{session_id}/properties")
def update_ticket_properties(
    session_id: str,
    priority: str | None = Body(None, embed=True),
    tags: list[str] | None = Body(None, embed=True),
    assigned_agent: str | None = Body(None, embed=True),
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> dict:
    """Partial update of agent-facing ticket metadata (priority, tags,
    assignee). Separate from /resolve — this is triage info an agent can
    change at any point in a ticket's life, not a workflow transition."""
    conversation = db.query(Conversation).filter_by(session_id=session_id).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    changes = []

    if priority is not None:
        if priority not in VALID_PRIORITIES:
            raise HTTPException(status_code=400, detail=f"priority must be one of {sorted(VALID_PRIORITIES)}")
        if conversation.priority != priority:
            changes.append(f"priority: {conversation.priority} -> {priority}")
        conversation.priority = priority

    if tags is not None:
        # Normalize: strip, drop empties, dedupe, cap length so one agent
        # fat-fingering a paste can't blow up the column.
        clean_tags = []
        for t in tags:
            t = t.strip()[:40]
            if t and t not in clean_tags:
                clean_tags.append(t)
        clean_tags = clean_tags[:20]
        conversation.tags = json.dumps(clean_tags)
        changes.append(f"tags: {clean_tags}")

    if assigned_agent is not None:
        # Empty string means "unassign".
        new_assignee = assigned_agent.strip() or None
        if new_assignee is not None:
            exists = db.query(Agent).filter_by(username=new_assignee).first()
            if not exists:
                raise HTTPException(status_code=400, detail=f"No agent with username '{new_assignee}'")
        if conversation.assigned_agent != new_assignee:
            changes.append(f"assigned_agent: {conversation.assigned_agent} -> {new_assignee}")
        conversation.assigned_agent = new_assignee

    if changes:
        audit = AuditLog(
            actor_username=agent.username,
            action="update_ticket_properties",
            target_username=session_id,
            details="; ".join(changes),
        )
        db.add(audit)

    db.commit()
    db.refresh(conversation)
    return _conversation_summary(conversation)


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


MAX_PINNED_PER_CONVERSATION = 5  # Slack/Discord-style small cap — this is a
                                  # ticket-triage aid (key order #, key promise),
                                  # not a bookmarking system; an unbounded list
                                  # defeats the point and blows up the banner.


def _pinned_messages_payload(conversation: Conversation, db: Session) -> list[dict]:
    """Serializes the conversation's currently-pinned messages, oldest first
    (i.e. pin order), for the pinned-messages banner. Shared by pin_message
    and get_conversation_messages so both return an identical shape."""
    pinned = (
        db.query(Message)
        .filter_by(conversation_id=conversation.id, is_pinned=True)
        .order_by(Message.created_at.asc())
        .all()
    )
    return [
        {
            "id": m.id,
            "sender": m.sender,
            "content": m.content,
            "author_username": m.author_username,
            "created_at": m.created_at.isoformat(),
        }
        for m in pinned
    ]


@router.post("/agent/conversations/{session_id}/pin")
def pin_message(
    session_id: str,
    message_id: str = Body(..., embed=True),
    is_pinned: bool = Body(..., embed=True),
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
) -> dict:
    conversation = db.query(Conversation).filter_by(session_id=session_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg = db.query(Message).filter_by(id=message_id, conversation_id=conversation.id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found in this conversation")

    if msg.is_pinned == is_pinned:
        # Idempotent no-op: nothing changed, so no commit/audit-log noise —
        # just return current state (still useful, e.g. after a race with
        # another agent's click).
        return {
            "status": "success",
            "message_id": msg.id,
            "is_pinned": msg.is_pinned,
            "pinned_messages": _pinned_messages_payload(conversation, db),
        }

    if is_pinned:
        current_count = db.query(Message).filter_by(
            conversation_id=conversation.id, is_pinned=True
        ).count()
        if current_count >= MAX_PINNED_PER_CONVERSATION:
            raise HTTPException(
                status_code=409,
                detail=f"Already at the {MAX_PINNED_PER_CONVERSATION}-pin limit for this conversation — unpin something first.",
            )

    msg.is_pinned = is_pinned

    audit = AuditLog(
        actor_username=agent.username,
        action="pin_message" if is_pinned else "unpin_message",
        target_username=session_id,
        details=f"message_id={message_id}",
    )
    db.add(audit)
    db.commit()
    db.refresh(msg)

    return {
        "status": "success",
        "message_id": msg.id,
        "is_pinned": msg.is_pinned,
        "pinned_messages": _pinned_messages_payload(conversation, db),
    }


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
        "priority": getattr(c, "priority", None) or "normal",
        "tags": _safe_json_list(getattr(c, "tags", None)),
        "assigned_agent": getattr(c, "assigned_agent", None),
    }


def _safe_json_list(raw: str | None) -> list[str]:
    """Parses the Conversation.tags JSON-text column defensively — a
    conversation created before this migration has tags=None, and any
    hand-edited or corrupted value should degrade to an empty list rather
    than 500ing the whole conversation list."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
