"""
Agent-facing REST endpoints: login, and fetching the two dashboard
sections (needs-attention conversations, and the full conversation
list). Live updates after the page loads come through /ws/agent —
these REST routes are for the initial page load only.
"""

from __future__ import annotations

import datetime
import json

from fastapi import APIRouter, Depends, HTTPException, Body, status, Response, Form, BackgroundTasks, Query
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
from app.db.models import Agent, Conversation, Message, AuditLog, CSATResponse, CannedResponse, SavedView, SystemSetting
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
    
    return {"access_token": token, "token_type": "bearer", "role": agent.role, "dp_url": agent.dp_url}  # nosec B105


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


@router.get("/agent/dashboard-summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from sqlalchemy import func
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from datetime import timezone

    open_tickets = db.query(Conversation).filter(Conversation.resolved == False).count()

    unassigned = db.query(Conversation).filter(
        Conversation.assigned_agent == None,
        Conversation.resolved == False
    ).count()

    tz = ZoneInfo('Asia/Dhaka')
    now = datetime.now(tz)
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_today_utc_naive = start_of_today.astimezone(timezone.utc).replace(tzinfo=None)
    
    solved_today = db.query(Conversation).filter(
        Conversation.resolved == True,
        Conversation.resolved_at >= start_of_today_utc_naive
    ).count()

    csat_avg = db.query(func.avg(CSATResponse.rating)).scalar()
    csat_score = round(csat_avg, 1) if csat_avg is not None else 0.0

    chat_counts = db.query(
        Conversation.assigned_agent, 
        func.count(Conversation.id)
    ).filter(
        Conversation.resolved == False,
        Conversation.assigned_agent != None
    ).group_by(Conversation.assigned_agent).all()
    
    agent_chat_counts = {agent_name: count for agent_name, count in chat_counts}
    
    todays_convs = db.query(Conversation.created_at).filter(
        Conversation.created_at >= start_of_today_utc_naive
    ).all()

    hourly_volume = [0] * 24
    for c in todays_convs:
        if c.created_at.tzinfo is None:
             local_dt = c.created_at.replace(tzinfo=timezone.utc).astimezone(tz)
        else:
             local_dt = c.created_at.astimezone(tz)
        hourly_volume[local_dt.hour] += 1

    # SLA Risks: tickets closest to or past breach, ordered by urgency
    open_convs = db.query(Conversation).filter(
        Conversation.resolved == False,
        Conversation.handoff_active == True
    ).all()
    
    sla_policy = get_sla_policy(db)
    
    sla_list = []
    for c in open_convs:
        status = get_sla_status(c, sla_policy)
        if status == "ok":
            continue
            
        if c.created_at.tzinfo is None:
            created_utc = c.created_at.replace(tzinfo=timezone.utc)
        else:
            created_utc = c.created_at.astimezone(timezone.utc)
            
        age_minutes = (datetime.now(timezone.utc) - created_utc).total_seconds() / 60
        priority = getattr(c, "priority", None) or "normal"
        threshold = sla_policy.get(priority, 240)
        ratio = age_minutes / threshold if threshold > 0 else 0
        
        sla_list.append({
            "session_id": c.session_id,
            "short_id": c.short_id,
            "customer_email": c.customer_email,
            "created_at": created_utc.isoformat(),
            "reopen_count": getattr(c, "reopen_count", 0),
            "priority": priority,
            "sla_status": status,
            "ratio": ratio
        })
        
    # sort by ratio descending
    sla_list.sort(key=lambda x: x["ratio"], reverse=True)
    sla_risks = sla_list[:5]

    # Inject mock data if DB is barren (for showcase purposes)
    if open_tickets == 0 and len(sla_risks) == 0:
        open_tickets = 14
        unassigned = 3
        solved_today = 28
        csat_score = 4.8
        agent_chat_counts = {"Sarah Jenkins": 4, "Michael Chang": 2, agent.username: 1}
        hourly_volume = [0, 0, 0, 0, 0, 0, 4, 12, 18, 26, 21, 35, 42, 38, 29, 22, 15, 8, 3, 0, 0, 0, 0, 0]
        
        # Add a couple of mock SLA risks to show the UI
        sla_risks = [
            {
                "session_id": "mock-risk-1",
                "short_id": "TK-A9B2",
                "customer_email": "urgent.client@example.com",
                "created_at": (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat(),
                "reopen_count": 1,
                "priority": "high",
                "sla_status": "breached",
                "ratio": 1.5
            },
            {
                "session_id": "mock-risk-2",
                "short_id": "TK-C4F8",
                "customer_email": "waiting.long@example.com",
                "created_at": (datetime.now(timezone.utc) - timedelta(minutes=28)).isoformat(),
                "reopen_count": 0,
                "priority": "normal",
                "sla_status": "warning",
                "ratio": 0.9
            }
        ]

    return {
        "open_tickets": open_tickets,
        "unassigned": unassigned,
        "solved_today": solved_today,
        "csat_score": csat_score,
        "agent_chat_counts": agent_chat_counts,
        "hourly_volume": hourly_volume,
        "sla_risks": sla_risks
    }

@router.get("/agent/customers")
def get_customers(
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from sqlalchemy import func, cast, Float, case
    from app.services.mock_apis import MOCK_CUSTOMERS, MOCK_ORDERS
    
    # Group by customer_email using SQL aggregations
    query = db.query(
        Conversation.customer_email.label("email"),
        func.count(Conversation.id).label("total_tickets"),
        func.max(Conversation.created_at).label("last_active"),
        func.sum(case((Conversation.resolved == True, 1), else_=0)).label("resolved_count"),
        func.avg(CSATResponse.rating).label("avg_csat")
    ).outerjoin(
        CSATResponse, Conversation.id == CSATResponse.conversation_id
    ).filter(
        Conversation.customer_email != None
    ).group_by(
        Conversation.customer_email
    )
    
    rows = query.all()
    
    # Dictionary of stats by email
    db_stats = {}
    for r in rows:
        email = r.email.lower() if r.email else ""
        if not email:
            continue
        total_tickets = r.total_tickets or 0
        resolved_count = r.resolved_count or 0
        resolved_ratio = (resolved_count / total_tickets) if total_tickets > 0 else 0
        db_stats[email] = {
            "total_tickets": total_tickets,
            "last_active": r.last_active,
            "resolved_ratio": resolved_ratio,
            "avg_csat": float(r.avg_csat) if r.avg_csat is not None else None
        }

    import hashlib
    from datetime import datetime, timedelta, timezone

    def generate_mock_stats(email_str):
        hash_val = int(hashlib.md5(email_str.encode()).hexdigest(), 16)
        
        total_tickets = (hash_val % 15) + 1  # 1 to 15 tickets
        resolved_ratio = ((hash_val % 40) + 60) / 100.0  # 0.60 to 0.99
        avg_csat = ((hash_val % 20) + 30) / 10.0  # 3.0 to 4.9
        
        # last_active between 1 hour and 14 days ago
        days_ago = (hash_val % 14)
        hours_ago = (hash_val % 24)
        last_active = datetime.now(timezone.utc) - timedelta(days=days_ago, hours=hours_ago)
        
        return {
            "total_tickets": total_tickets,
            "resolved_ratio": resolved_ratio,
            "avg_csat": float(avg_csat),
            "last_active": last_active
        }

    results = []
    seen_emails = set()
    
    # First, append all mock customers
    for cust in MOCK_CUSTOMERS:
        email = cust.get("email", "").lower()
        if not email:
            continue
            
        seen_emails.add(email)
        stats = db_stats.get(email)
        if not stats or stats.get("total_tickets", 0) == 0:
            stats = generate_mock_stats(email)
        
        results.append({
            "email": cust.get("email"), # Use original case
            "total_tickets": stats.get("total_tickets", 0),
            "last_active": stats.get("last_active").isoformat() if stats.get("last_active") else None,
            "resolved_ratio": stats.get("resolved_ratio", 0),
            "avg_csat": stats.get("avg_csat", None)
        })
        
    # Add any emails from MOCK_ORDERS not in MOCK_CUSTOMERS
    for order in MOCK_ORDERS.values():
        email_order = order.get("email", "")
        email = email_order.lower()
        if not email or email in seen_emails:
            continue
            
        seen_emails.add(email)
        stats = db_stats.get(email)
        if not stats or stats.get("total_tickets", 0) == 0:
            stats = generate_mock_stats(email)
        
        results.append({
            "email": email_order, # original case
            "total_tickets": stats.get("total_tickets", 0),
            "last_active": stats.get("last_active").isoformat() if stats.get("last_active") else None,
            "resolved_ratio": stats.get("resolved_ratio", 0),
            "avg_csat": stats.get("avg_csat", None)
        })
        
    # Also add any customers from the DB that are not in MOCK_CUSTOMERS
    # (Just in case there are real users interacting)
    for r in rows:
        email_lower = r.email.lower() if r.email else ""
        # Exclude old seed script users (mockuser0@example.com, etc.)
        if not email_lower or email_lower in seen_emails or email_lower.startswith("mockuser"):
            continue
            
        total_tickets = r.total_tickets or 0
        resolved_count = r.resolved_count or 0
        resolved_ratio = (resolved_count / total_tickets) if total_tickets > 0 else 0
        
        results.append({
            "email": r.email,
            "total_tickets": total_tickets,
            "last_active": r.last_active.isoformat() if r.last_active else None,
            "resolved_ratio": resolved_ratio,
            "avg_csat": float(r.avg_csat) if r.avg_csat is not None else None
        })
        
    # Sort by total_tickets descending
    results.sort(key=lambda x: x["total_tickets"], reverse=True)
    
    return results

class CreateSavedViewRequest(BaseModel):
    name: str
    filter_json: str

@router.get("/agent/saved-views")
def get_saved_views(
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
):
    views = db.query(SavedView).all()
    return [{"id": v.id, "name": v.name, "filter_json": v.filter_json, "agent_username": v.agent_username} for v in views]

@router.post("/agent/saved-views")
def create_saved_view(
    payload: CreateSavedViewRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
):
    view = SavedView(
        agent_username=agent.username,
        name=payload.name,
        filter_json=payload.filter_json
    )
    db.add(view)
    db.commit()
    db.refresh(view)
    return {"id": view.id, "name": view.name, "filter_json": view.filter_json, "agent_username": view.agent_username}

@router.delete("/agent/saved-views/{view_id}")
def delete_saved_view(
    view_id: str,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
):
    view = db.query(SavedView).filter(SavedView.id == view_id).first()
    if not view:
        raise HTTPException(status_code=404, detail="View not found")
    db.delete(view)
    db.commit()
    return {"status": "deleted"}


def _apply_conversation_filters(q, priority: str | None, assigned_agent: str | None, tag: str | None):
    if priority:
        q = q.filter(Conversation.priority == priority)
    if assigned_agent:
        if assigned_agent.lower() == "unassigned":
            q = q.filter(Conversation.assigned_agent == None)
        else:
            q = q.filter(Conversation.assigned_agent == assigned_agent)
    if tag:
        q = q.filter(Conversation.tags.like(f'%"{tag}"%'))
    return q

@router.get("/agent/conversations/needs-attention")
def needs_attention(
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
    priority: str | None = None,
    assigned_agent: str | None = None,
    tag: str | None = None,
) -> list[dict]:
    q = db.query(Conversation)
    q = _apply_conversation_filters(q, priority, assigned_agent, tag)
    conversations = (
        q
        .filter(Conversation.handoff_active == True, Conversation.resolved == False, Conversation.handled_by == None)
        .filter(Conversation.messages.any())
        .options(selectinload(Conversation.messages))
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    sla_policy = get_sla_policy(db)
    return [_conversation_summary(c, sla_policy) for c in conversations]


@router.get("/agent/conversations/my-cases")
def get_my_cases(
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
    priority: str | None = None,
    assigned_agent: str | None = None,
    tag: str | None = None,
):
    q = db.query(Conversation)
    q = _apply_conversation_filters(q, priority, assigned_agent, tag)
    convs = q.options(selectinload(Conversation.messages)).outerjoin(
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
        sla_policy = get_sla_policy(db) if 'sla_policy' not in locals() else sla_policy
        summary = _conversation_summary(c, sla_policy)
        summary["is_mentioned"] = (c.handled_by != agent.username)
        results.append(summary)
        
    return results


def _add_merge_info_to_summary(summary: dict, conversation: Conversation, db: Session):
    summary["merged_into_id"] = conversation.merged_into_id
    summary["merged_into_session_id"] = None
    summary["merged_into_short_id"] = None
    if conversation.merged_into_id:
        target = db.query(Conversation).filter_by(id=conversation.merged_into_id).first()
        if target:
            summary["merged_into_session_id"] = target.session_id
            summary["merged_into_short_id"] = target.short_id
            
    merged_from = db.query(Conversation).filter_by(merged_into_id=conversation.id).all()
    summary["merged_from"] = [{"session_id": m.session_id, "short_id": getattr(m, "short_id", "???")} for m in merged_from]

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
    priority: str | None = None,
    assigned_agent: str | None = None,
    tag: str | None = None,
) -> list[dict]:
    q = db.query(Conversation)
    q = _apply_conversation_filters(q, priority, assigned_agent, tag)
    conversations = (
        q
        .filter(Conversation.resolved == False)
        .filter(Conversation.messages.any())
        .options(selectinload(Conversation.messages))
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    sla_policy = get_sla_policy(db)
    return [_conversation_summary(c, sla_policy) for c in conversations]


@router.get("/agent/conversations")
def all_conversations(
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
    priority: str | None = None,
    assigned_agent: str | None = None,
    tag: str | None = None,
) -> list[dict]:
    q = db.query(Conversation)
    q = _apply_conversation_filters(q, priority, assigned_agent, tag)
    conversations = (
        q
        .filter(Conversation.messages.any())
        .options(selectinload(Conversation.messages))
        .order_by(Conversation.updated_at.desc())
        .limit(50)
        .all()
    )
    sla_policy = get_sla_policy(db)
    return [_conversation_summary(c, sla_policy) for c in conversations]


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
    sla_policy = get_sla_policy(db)
    summary = _conversation_summary(conversation, sla_policy)
    
    # Add merge info
    _add_merge_info_to_summary(summary, conversation, db)
    
    return summary


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
    _do_resolve_conversation(conversation, agent.username, db, background_tasks)
    db.commit()
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

    _do_update_ticket_properties(conversation, agent.username, db, priority, tags, assigned_agent)

    db.commit()
    db.refresh(conversation)
    sla_policy = get_sla_policy(db)
    summary = _conversation_summary(conversation, sla_policy)
    
    # Add merge info
    _add_merge_info_to_summary(summary, conversation, db)
    
    return summary


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
                
    # 2.5. Check for explicit phone number in messages
    for msg in messages:
        phone_match = re.search(r'\b\d{3}[-.\s]?\d{4}\b', msg.content)
        if phone_match:
            cust = get_customer_info(phone=phone_match.group(0))
            if cust and cust.get("recent_order"):
                order = get_order_status(cust["recent_order"])
                if order:
                    resp = build_response(order, "phone_scan")
                    resp["customer"] = cust
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




def _do_resolve_conversation(conversation: Conversation, agent_username: str, db: Session, background_tasks: BackgroundTasks):
    if not conversation.resolved:
        conversation.resolved = True
        conversation.resolved_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        conversation.handoff_active = False
        conversation.handled_by = agent_username
        
        audit = AuditLog(
            actor_username=agent_username,
            action="resolve_conversation",
            target_username=conversation.session_id
        )
        db.add(audit)
        background_tasks.add_task(process_resolved_conversation_tasks, conversation.id)
        background_tasks.add_task(manager.send_to_customer, conversation.session_id, {"type": "resolved"})

def _do_update_ticket_properties(conversation: Conversation, agent_username: str, db: Session, priority: str | None = None, tags: list[str] | None = None, assigned_agent: str | None = None) -> list[str]:
    changes = []
    if priority is not None:
        if priority not in VALID_PRIORITIES:
            raise HTTPException(status_code=400, detail=f"priority must be one of {sorted(VALID_PRIORITIES)}")
        if conversation.priority != priority:
            changes.append(f"priority: {conversation.priority} -> {priority}")
        conversation.priority = priority

    if tags is not None:
        clean_tags = []
        for t in tags:
            t = t.strip()[:40]
            if t and t not in clean_tags:
                clean_tags.append(t)
        clean_tags = clean_tags[:20]
        conversation.tags = json.dumps(clean_tags)
        changes.append(f"tags: {clean_tags}")

    if assigned_agent is not None:
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
            actor_username=agent_username,
            action="update_ticket_properties",
            target_username=conversation.session_id,
            details="; ".join(changes),
        )
        db.add(audit)
    return changes

class BulkActionRequest(BaseModel):
    session_ids: list[str]
    action: str  # "resolve" | "assign" | "tag" | "priority"
    value: str | list[str] | None = None

@router.patch("/agent/conversations/bulk")
def bulk_update_conversations(
    payload: BulkActionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> dict:
    if not payload.session_ids:
        return {"status": "success", "updated": 0}
        
    conversations = db.query(Conversation).filter(Conversation.session_id.in_(payload.session_ids)).all()
    
    updated_count = 0
    for conv in conversations:
        if payload.action == "resolve":
            _do_resolve_conversation(conv, agent.username, db, background_tasks)
            updated_count += 1
        elif payload.action == "assign":
            _do_update_ticket_properties(conv, agent.username, db, assigned_agent=payload.value)
            updated_count += 1
        elif payload.action == "tag":
            if isinstance(payload.value, list):
                _do_update_ticket_properties(conv, agent.username, db, tags=payload.value)
                updated_count += 1
            else:
                _do_update_ticket_properties(conv, agent.username, db, tags=[payload.value] if payload.value else [])
                updated_count += 1
        elif payload.action == "priority":
            _do_update_ticket_properties(conv, agent.username, db, priority=payload.value)
            updated_count += 1
            
    db.commit()
    return {"status": "success", "updated": updated_count}

class CannedResponseCreate(BaseModel):
    shortcut: str
    title: str
    body: str

@router.get("/agent/canned-responses")
def get_canned_responses(
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
) -> list[dict]:
    responses = db.query(CannedResponse).order_by(CannedResponse.shortcut).all()
    return [{"id": r.id, "shortcut": r.shortcut, "title": r.title, "body": r.body} for r in responses]

@router.post("/agent/canned-responses")
def create_canned_response(
    payload: CannedResponseCreate,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
) -> dict:
    if not agent.has_permission("manage_canned_responses"):
        raise HTTPException(status_code=403, detail="Not authorized")
    if not payload.shortcut.startswith("/"):
        raise HTTPException(status_code=400, detail="Shortcut must start with /")
        
    existing = db.query(CannedResponse).filter_by(shortcut=payload.shortcut).first()
    if existing:
        raise HTTPException(status_code=400, detail="Shortcut already exists")
        
    new_resp = CannedResponse(
        shortcut=payload.shortcut,
        title=payload.title,
        body=payload.body,
        created_by=agent.username
    )
    db.add(new_resp)
    
    audit = AuditLog(actor_username=agent.username, action="create_canned_response", target_username=payload.shortcut)
    db.add(audit)
    db.commit()
    
    return {"status": "created", "id": new_resp.id}

@router.patch("/agent/canned-responses/{response_id}")
def update_canned_response(
    response_id: str,
    payload: CannedResponseCreate,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
) -> dict:
    if not agent.has_permission("manage_canned_responses"):
        raise HTTPException(status_code=403, detail="Not authorized")
    if not payload.shortcut.startswith("/"):
        raise HTTPException(status_code=400, detail="Shortcut must start with /")
        
    resp = db.query(CannedResponse).filter_by(id=response_id).first()
    if not resp:
        raise HTTPException(status_code=404, detail="Not found")
        
    existing = db.query(CannedResponse).filter(CannedResponse.shortcut == payload.shortcut, CannedResponse.id != response_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Shortcut already exists")
        
    resp.shortcut = payload.shortcut
    resp.title = payload.title
    resp.body = payload.body
    
    audit = AuditLog(actor_username=agent.username, action="update_canned_response", target_username=payload.shortcut)
    db.add(audit)
    db.commit()
    
    return {"status": "updated"}

@router.delete("/agent/canned-responses/{response_id}")
def delete_canned_response(
    response_id: str,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
) -> dict:
    if not agent.has_permission("manage_canned_responses"):
        raise HTTPException(status_code=403, detail="Not authorized")
        
    resp = db.query(CannedResponse).filter_by(id=response_id).first()
    if not resp:
        raise HTTPException(status_code=404, detail="Not found")
        
    audit = AuditLog(actor_username=agent.username, action="delete_canned_response", target_username=resp.shortcut)
    db.add(audit)
    db.delete(resp)
    db.commit()
    
    return {"status": "deleted"}

def get_sla_policy(db: Session) -> dict:
    setting = db.query(SystemSetting).filter(SystemSetting.key == "sla_policy").first()
    if setting:
        import json
        try:
            return json.loads(setting.value)
        except:
            pass
    return {"urgent": 15, "high": 60, "normal": 240, "low": 1440}

def get_sla_status(c: Conversation, sla_policy: dict) -> str:
    if c.resolved or not getattr(c, "handoff_active", False):
        return "ok"
    if c.created_at.tzinfo is None:
        import datetime
        created_utc = c.created_at.replace(tzinfo=datetime.timezone.utc)
    else:
        import datetime
        created_utc = c.created_at.astimezone(datetime.timezone.utc)
        
    import datetime
    age_minutes = (datetime.datetime.now(datetime.timezone.utc) - created_utc).total_seconds() / 60
    priority = getattr(c, "priority", None) or "normal"
    threshold = sla_policy.get(priority, 240)
    
    if age_minutes >= threshold:
        return "breached"
    elif age_minutes >= threshold * 0.8:
        return "warning"
    return "ok"

def _conversation_summary(c: Conversation, sla_policy: dict = None) -> dict:
    last_msg_obj = c.messages[-1] if c.messages else None
    last_message = last_msg_obj.content if last_msg_obj else None
    last_message_is_internal = (last_msg_obj.sender == 'agent_internal') if last_msg_obj else False
    
    stage = "AI"
    if c.resolved:
        stage = "Resolved"
    elif c.handoff_active:
        stage = "Human Agent"

    customer_name = None
    email_to_use = c.customer_email

    if not email_to_use and c.messages:
        # 1. Scan for explicit Order ID first
        for msg in reversed(c.messages):
            if msg.sender == "human":
                order_match = re.search(r'(?:order\s*[#:]?\s*|#)(\d{4,})', msg.content, re.IGNORECASE)
                if order_match:
                    order = get_order_status(order_match.group(1))
                    if order and "email" in order:
                        email_to_use = order["email"]
                        break
                        
        # 2. Check for explicit email if no order found
        if not email_to_use:
            for msg in reversed(c.messages):
                if msg.sender == "human":
                    email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', msg.content)
                    if email_match:
                        email_to_use = email_match.group(0)
                        break

        # 3. Check for last_order_id stored on the conversation state
        if not email_to_use and c.last_order_id:
            order = get_order_status(c.last_order_id)
            if order and "email" in order:
                email_to_use = order["email"]

    if email_to_use:
        cust = get_customer_info(email=email_to_use)
        if cust:
            customer_name = cust.get("name")

    return {
        "session_id": c.session_id,
        "short_id": getattr(c, "short_id", "CUST-XXXX"),
        "customer_email": email_to_use,
        "customer_name": customer_name,
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
        "sla_status": get_sla_status(c, sla_policy) if sla_policy else "ok",
        "tags": _safe_json_list(getattr(c, "tags", None)),
        "assigned_agent": getattr(c, "assigned_agent", None),
        "csat_rating": c.csat_response.rating if c.csat_response else None,
        "csat_comment": c.csat_response.comment if c.csat_response else None,
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

@router.get("/agent/my-scorecards")
def get_my_scorecards(
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
):
    from app.db.models import AnalyticsScorecard, Conversation
    scorecards = (
        db.query(AnalyticsScorecard, Conversation.short_id, Conversation.created_at)
        .join(Conversation, Conversation.id == AnalyticsScorecard.conversation_id)
        .filter(Conversation.handled_by == agent.username)
        .order_by(AnalyticsScorecard.created_at.desc())
        .limit(20)
        .all()
    )
    
    results = []
    for sc, short_id, conv_created_at in scorecards:
        results.append({
            "id": sc.id,
            "conversation_id": sc.conversation_id,
            "short_id": short_id,
            "conversation_date": conv_created_at.isoformat() if conv_created_at else None,
            "empathy_score": sc.empathy_score,
            "accuracy_score": sc.accuracy_score,
            "resolution_score": sc.resolution_score,
            "csat_prediction": sc.csat_prediction,
            "feedback_notes": sc.feedback_notes,
            "created_at": sc.created_at.isoformat() if sc.created_at else None
        })
    return results

class MergeRequest(BaseModel):
    target_session_id: str

@router.post("/agent/conversations/{session_id}/merge")
def merge_conversation(
    session_id: str,
    payload: MergeRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
):
    source = db.query(Conversation).filter_by(session_id=session_id).first()
    if not source:
        raise HTTPException(404, "Source conversation not found")
        
    target = db.query(Conversation).filter((Conversation.session_id == payload.target_session_id) | (Conversation.short_id == payload.target_session_id)).first()
    if not target:
        raise HTTPException(404, "Target conversation not found")
        
    if source.id == target.id:
        raise HTTPException(400, "Cannot merge a conversation into itself")
        
    # Cycle protection: ensure target doesn't eventually point back to source
    current = target
    while current.merged_into_id:
        if current.merged_into_id == source.id:
            raise HTTPException(400, "Merge cycle detected: target eventually merges back into source")
        current = db.query(Conversation).filter_by(id=current.merged_into_id).first()
        if not current:
            break
        
    source.merged_into_id = target.id
    
    audit = AuditLog(
        actor_username=agent.username,
        action="merge_ticket",
        target_username=session_id,
        details=f"merged into target_session_id={target.session_id}"
    )
    db.add(audit)
    db.commit()
    
    return {"status": "merged", "source_id": source.id, "target_id": target.id}
