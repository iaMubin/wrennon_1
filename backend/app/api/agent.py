"""
Agent-facing REST endpoints: login, and fetching the two dashboard
sections (needs-attention conversations, and the full conversation
list). Live updates after the page loads come through /ws/agent —
these REST routes are for the initial page load only.
"""

from __future__ import annotations

import datetime
import json

from fastapi import APIRouter, Depends, HTTPException, Body, status, Response, Form, BackgroundTasks, Request, Query
from fastapi.security import OAuth2PasswordRequestForm
import pyotp
from app.services.qa import process_resolved_conversation_tasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import or_

from app.auth.dependencies import get_current_agent
from app.auth.access import get_conversation_or_404, require_permission, scope_conversations, can_access_conversation
from app.auth.sessions import revoke_session
from app.auth.security import create_access_token, verify_password
from app.config import settings
from app.logger import logger
import re
from app.services.mock_apis import get_order_status, get_order_by_email, get_customer_info
from app.db.models import Agent, Conversation, Message, AuditLog, CSATResponse, CannedResponse, SavedView, SystemSetting
from app.db.session import get_db
from app.realtime.connection_manager import manager
import redis.asyncio as redis
from app.services.integrations import USE_MOCK, get_ecommerce_provider
from app.services.integrations import store_db_enabled as _store_db_enabled
_STORE_DB = _store_db_enabled()
from app.services.uploads import resign_text
from app.security.totp_store import read_secret, upgrade_if_plaintext, write_secret
from app.services import ratelimit
from app.services.audit import add_audit, audit_now


def _store_customers(db):
    from app.db.store_models import StoreCustomer
    return [{"email": c.email} for c in db.query(StoreCustomer).order_by(StoreCustomer.id).all()]

if not USE_MOCK or _STORE_DB:
    # Dashboard lookups used to import mock_apis directly, so agents saw fake orders
    # and customers even with real integrations enabled. Agents are trusted: include email.
    def _shop():
        # The tenant is bound to the request by get_current_agent; every lookup
        # goes to THAT tenant's store (or an "unconfigured" provider), never
        # another tenant's credentials.
        from app.db.tenancy import current_tenant
        return get_ecommerce_provider(current_tenant.get())

    def get_order_status(order_id):
        return _shop().get_order_status(order_id, include_email=True)

    def get_order_by_email(email):
        return _shop().get_order_by_email(email, include_email=True)

    def get_customer_info(email=None, phone=None, customer_id=None):
        return _shop().get_customer_info(email=email, phone=phone, customer_id=customer_id)

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

async def _totp_valid_once(agent: Agent, code: str) -> bool:
    """Verify a TOTP code and reject replays of an already-used code.
    valid_window=1 tolerates one 30s step of clock drift. Replay tracking uses the
    shared counter helper, which falls back to an in-process store if Redis is down
    (so replay protection does not silently disappear)."""
    secret = read_secret(agent)
    if not code or not secret or not pyotp.TOTP(secret).verify(code, valid_window=1):
        return False
    upgrade_if_plaintext(agent)   # legacy plaintext secret -> encrypted at rest (committed with the caller's next commit)
    return await ratelimit.hit(f"totp_used:{agent.username}:{code}", 120) == 1


_DUMMY_HASH: str | None = None


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        from app.auth.security import hash_password
        _DUMMY_HASH = hash_password("timing-equaliser")
    return _DUMMY_HASH


@router.post("/agent/login")
async def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    totp_code: str | None = Form(None),
    db: Session = Depends(get_db)
) -> dict:
    # Rate Limiting
    # Keyed by IP + username so an attacker can only lock out their own IP,
    # not the real admin (username alone = trivial lockout DoS). A second,
    # IP-wide counter stops one source from walking through many usernames.
    client_ip = request.client.host if request.client else "unknown"
    username_key = form_data.username.lower()[:80]
    rate_key = f"login_attempts:{client_ip}:{username_key}"
    ip_key = f"login_ip:{client_ip}"
    locked = False
    try:
        r = get_redis()
        attempts = await r.get(rate_key)
        locked = bool(attempts) and int(attempts) >= 5
        ip_attempts = await r.get(ip_key)
        locked = locked or (bool(ip_attempts) and int(ip_attempts) >= 40)
    except Exception as e:
        # If Redis is down, brute-force lockout silently fails OPEN — an
        # attacker can hammer this endpoint unthrottled until Redis comes
        # back. That's an operationally important signal, not routine
        # noise, so it's logged at WARNING (visible in production/Sentry).
        logger.warning(f"Redis unavailable during login rate-limit check for {form_data.username}: {e}")
    # Raised OUTSIDE the try block: previously this 429 was raised inside
    # `except Exception`'s scope and got swallowed, so lockout never fired.
    if locked:
        audit_now(db, username_key, "login_locked_out", ip=client_ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again later.",
        )

    async def _record_failure(reason: str) -> None:
        try:
            r = get_redis()
            if await r.incr(rate_key) == 1:
                await r.expire(rate_key, 300)  # fixed 5-min window, not refreshed per attempt
            if await r.incr(ip_key) == 1:
                await r.expire(ip_key, 600)
        except Exception as e:
            logger.warning(f"Redis unavailable while recording a failed login attempt for {form_data.username}: {e}")
        audit_now(db, username_key, "login_failed", details=reason, ip=client_ip)

    agent = db.query(Agent).filter(
        or_(Agent.username == form_data.username, Agent.employee_id == form_data.username)
    ).first()

    # Always run one bcrypt comparison so "no such user" and "wrong password"
    # cost the same time (no username enumeration by timing).
    if agent:
        db.info["tenant_id"] = agent.tenant_id   # failed/successful logins are audited in the account's own tenant
    password_ok = verify_password(form_data.password, agent.password_hash if agent else _dummy_hash())
    if not agent or not password_ok:
        await _record_failure("bad_credentials")
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
        # A wrong 2FA code counts as a failed login (it used to be free to
        # guess), and an accepted code cannot be replayed inside its window.
        if not await _totp_valid_once(agent, totp_code):
            await _record_failure("bad_totp")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid 2FA code"
            )

    # Reset rate limit on success
    try:
        r = get_redis()
        await r.delete(rate_key)
    except Exception as e:
        logger.warning(f"Redis unavailable while clearing rate-limit counter for {agent.username}: {e}")

    token = create_access_token(subject=agent.username, token_version=agent.token_version)

    audit_now(db, agent.username, "login", ip=client_ip)

    # Set httpOnly cookie. Its lifetime now matches the JWT's (it was 7 days
    # against an 8-hour token).
    response.set_cookie(
        key="access_token",
        value=f"Bearer {token}",
        httponly=True,
        secure=True,     # Must be True for samesite="none" (HTTPS)
        samesite="none", # Allow cross-origin requests
        max_age=settings.jwt_expire_minutes * 60,
    )

    return {"access_token": token, "token_type": "bearer",  # nosec B105 - OAuth token type label, not a secret
            "role": agent.role, "dp_url": agent.dp_url, "full_name": agent.full_name,
            "suggestions_enabled": bool(getattr(agent, "suggestions_enabled", True))}

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
    add_audit(db, agent.username, "logout")
    db.commit()
    response.delete_cookie(key="access_token", samesite="none", secure=True)
    return {"status": "logged_out"}


class AgentPreferencesUpdate(BaseModel):
    suggestions_enabled: bool


@router.get("/agent/preferences")
def get_preferences(
    agent: Agent = Depends(get_current_agent),
) -> dict:
    return {
        "suggestions_enabled": bool(getattr(agent, "suggestions_enabled", True))
    }


@router.patch("/agent/preferences")
def update_preferences(
    pref: AgentPreferencesUpdate,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> dict:
    agent.suggestions_enabled = pref.suggestions_enabled
    db.commit()
    db.refresh(agent)
    return {
        "suggestions_enabled": bool(agent.suggestions_enabled)
    }


class VerifyTOTPRequest(BaseModel):
    code: str


class Setup2FARequest(BaseModel):
    current_password: str
    code: str | None = None  # required when 2FA is already enabled


@router.post("/agent/2fa/setup")
async def setup_2fa(
    request: Request,
    payload: Setup2FARequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> dict:
    client_ip = request.client.host if request.client else "unknown"
    # Step-up auth: a stolen session/token must NOT be enough to (re)enroll or
    # silently disable 2FA. Require the password, and the current TOTP code if
    # 2FA is already on. Bounded guessing: 5 failures / 10 min / agent.
    if await ratelimit.peek(f"setup2fa_fail:{agent.username}") >= 5:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    if not verify_password(payload.current_password, agent.password_hash):
        await ratelimit.hit(f"setup2fa_fail:{agent.username}", 600)
        audit_now(db, agent.username, "2fa_setup_denied", details="bad_password", ip=client_ip)
        raise HTTPException(status_code=401, detail="Incorrect password")
    if agent.totp_enabled and not await _totp_valid_once(agent, payload.code or ""):
        await ratelimit.hit(f"setup2fa_fail:{agent.username}", 600)
        audit_now(db, agent.username, "2fa_setup_denied", details="bad_code", ip=client_ip)
        raise HTTPException(status_code=401, detail="Invalid 2FA code")
    secret = pyotp.random_base32()
    write_secret(agent, secret)
    agent.totp_enabled = False
    add_audit(db, agent.username, "2fa_setup_started", ip=client_ip)
    db.commit()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=agent.username, issuer_name="Wrennon")
    return {"uri": uri}


@router.post("/agent/2fa/verify")
async def verify_2fa(
    request: Request,
    payload: VerifyTOTPRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> dict:
    client_ip = request.client.host if request.client else "unknown"
    if not agent.totp_secret:
        raise HTTPException(status_code=400, detail="2FA setup not initiated")
    # Bounded guessing: 5 wrong codes per 10 minutes per agent.
    if await ratelimit.peek(f"totp_verify_fail:{agent.username}") >= 5:
        raise HTTPException(status_code=429, detail="Too many invalid codes. Try again later.")
    if not await _totp_valid_once(agent, payload.code):
        await ratelimit.hit(f"totp_verify_fail:{agent.username}", 600)
        audit_now(db, agent.username, "2fa_verify_failed", ip=client_ip)
        raise HTTPException(status_code=400, detail="Invalid 2FA code")
    agent.totp_enabled = True
    agent.token_version = (agent.token_version or 1) + 1   # other sessions must re-authenticate with 2FA
    add_audit(db, agent.username, "enable_2fa", ip=client_ip)
    db.commit()
    return {"status": "success", "relogin_required": True}


@router.get("/agent/dashboard-summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Live dashboard. Every figure is measured from the database; anything that cannot be
    measured is returned as null (or an empty list) and the UI shows an honest empty state."""
    from sqlalchemy import func
    from datetime import datetime, timedelta, timezone
    from app.services import dashboard_stats as ds

    now = datetime.now(ds.TZ)
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_today_utc_naive = ds.to_utc_naive(start_of_today)

    open_tickets = db.query(Conversation).filter(Conversation.resolved == False).count()
    unassigned = db.query(Conversation).filter(
        Conversation.assigned_agent == None,
        Conversation.resolved == False
    ).count()
    solved_today = db.query(Conversation).filter(
        Conversation.resolved == True,
        Conversation.resolved_at >= start_of_today_utc_naive
    ).count()
    ai_handling = db.query(Conversation).filter(
        Conversation.resolved == False, Conversation.handoff_active == False
    ).count()
    awaiting_human = db.query(Conversation).filter(
        Conversation.resolved == False, Conversation.handoff_active == True, Conversation.handled_by == None
    ).count()
    handoff_open = db.query(Conversation).filter(
        Conversation.resolved == False, Conversation.handoff_active == True
    ).count()

    csat_avg = db.query(func.avg(CSATResponse.rating)).scalar()
    csat_score = round(csat_avg, 1) if csat_avg is not None else None
    csat_count = db.query(func.count(CSATResponse.id)).scalar() or 0

    chat_counts = db.query(
        Conversation.assigned_agent,
        func.count(Conversation.id)
    ).filter(
        Conversation.resolved == False,
        Conversation.assigned_agent != None
    ).group_by(Conversation.assigned_agent).all()
    agent_chat_counts = {agent_name: count for agent_name, count in chat_counts}

    today_hours = ds.hourly_for_day(db, start_of_today)
    yesterday_hours = ds.hourly_for_day(db, start_of_today - timedelta(days=1))

    # SLA risks: open conversations waiting on a human, closest to (or past) breach first
    open_convs = scope_conversations(db.query(Conversation).filter(
        Conversation.resolved == False,
        Conversation.handoff_active == True
    ), agent).all()
    sla_policy = get_sla_policy(db)
    sla_list = []
    for c in open_convs:
        status = get_sla_status(c, sla_policy)
        if status == "ok":
            continue
        created_utc = c.created_at.replace(tzinfo=timezone.utc) if c.created_at.tzinfo is None else c.created_at.astimezone(timezone.utc)
        age_minutes = (datetime.now(timezone.utc) - created_utc).total_seconds() / 60
        priority = getattr(c, "priority", None) or "normal"
        threshold = sla_policy.get(priority, 240)
        ratio = age_minutes / threshold if threshold > 0 else 0
        minutes_remaining = max(0, int(threshold - age_minutes)) if ratio < 1.0 else -int(age_minutes - threshold)
        sla_list.append({
            "session_id": c.session_id,
            "short_id": c.short_id,
            "customer_email": c.customer_email,
            "created_at": created_utc.isoformat(),
            "reopen_count": getattr(c, "reopen_count", 0),
            "priority": priority,
            "sla_status": status,
            "ratio": ratio,
            "minutes_remaining": minutes_remaining,
            "subject": c.summary or None,
            "assigned_agent": c.assigned_agent,
        })
    sla_list.sort(key=lambda x: x["ratio"], reverse=True)

    window_days = 7
    kpis = ds.compute_period(db, sla_policy, ds.to_utc_naive(now - timedelta(days=window_days)))

    return {
        "open_tickets": open_tickets,
        "unassigned": unassigned,
        "solved_today": solved_today,
        "csat_score": csat_score,
        "csat_count": csat_count,
        "kpi_window_days": window_days,
        "sla_compliance_rate": ds._fmt(kpis["sla_compliance_pct"]),
        "first_response_time_seconds": ds._fmt(kpis["first_response_seconds"], 0),
        "fcr_rate_pct": ds._fmt(kpis["one_touch_pct"]),
        "ai_deflection_rate_pct": ds._fmt(kpis["ai_resolution_pct"]),
        "agent_chat_counts": agent_chat_counts,
        "hourly_volume": today_hours["created"],
        "hourly_ai_resolved": today_hours["ai_resolved"],
        "hourly_volume_yesterday": yesterday_hours["created"],
        "sla_risks": sla_list[:6],
        "live_team_status": ds.team_status(db, start_of_today_utc_naive),
        "copilot_stream": ds.recent_activity(db),
        "operational_telemetry": {
            "open_now": open_tickets,
            "ai_handling": ai_handling,
            "awaiting_human": awaiting_human,
            "handoff_open": handoff_open,
            "p95_first_response_seconds": ds._fmt(kpis["p95_first_response_seconds"], 0),
        },
    }

def _customer_health(avg_csat, resolved_ratio):
    """Health only exists once there is a rating and a resolution history to base it on."""
    if avg_csat is None or resolved_ratio is None:
        return None, None
    score = max(0, min(100, int((avg_csat / 5.0) * 70 + (resolved_ratio * 30))))
    return score, ("Healthy" if score >= 82 else ("Neutral" if score >= 62 else "At Risk"))


def _customer_sentiment(avg_csat):
    if avg_csat is None:
        return None
    return "Delighted" if avg_csat >= 4.6 else ("Satisfied" if avg_csat >= 4.0 else ("Neutral" if avg_csat >= 3.2 else "Frustrated"))


@router.get("/agent/customers")
def get_customers(
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permission("view_customers")),
):
    from sqlalchemy import func, case
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

    # Fetch recent conversations grouped by customer email for instant drawer history
    conv_rows = db.query(
        Conversation.customer_email,
        Conversation.session_id,
        Conversation.short_id,
        Conversation.resolved,
        Conversation.priority,
        Conversation.created_at
    ).order_by(Conversation.created_at.desc()).limit(150).all()

    convs_by_email = {}
    for cr in conv_rows:
        if not cr.customer_email:
            continue
        em = cr.customer_email.lower()
        if em not in convs_by_email:
            convs_by_email[em] = []
        if len(convs_by_email[em]) < 5:
            convs_by_email[em].append({
                "session_id": cr.session_id,
                "short_id": cr.short_id,
                "resolved": cr.resolved,
                "priority": cr.priority or "normal",
                "created_at": cr.created_at.isoformat() if cr.created_at else None
            })

    demo_mode = bool(USE_MOCK and not _STORE_DB)

    def build_customer_record(email_str, mock_c=None, demo=False):
        """Facts only. Phone, plan, lifetime value and order count come from the store (or the
        explicit demo data) when it has them; a customer is never given invented contact details,
        a made-up location or a guessed spend. What the helpdesk itself measured (tickets,
        resolution rate, ratings) comes from the database; if there is nothing, the field is null."""
        email_clean = email_str.strip()
        email_lower = email_clean.lower()
        mock_c = mock_c or {}

        if mock_c.get("name"):
            name = mock_c["name"]
        else:
            local = email_clean.split('@')[0]
            words = [w.capitalize() for w in local.replace('.', ' ').replace('_', ' ').replace('-', ' ').split()]
            name = " ".join(words) if words else "Customer"

        stats = db_stats.get(email_lower)
        total_tickets = stats["total_tickets"] if stats else 0
        resolved_ratio = stats["resolved_ratio"] if stats and total_tickets > 0 else None
        avg_csat = stats["avg_csat"] if stats else None
        last_active = stats["last_active"].isoformat() if stats and stats.get("last_active") else None

        orders = [o for o in MOCK_ORDERS.values() if o.get("email", "").lower() == email_lower] if USE_MOCK and not _STORE_DB else []
        total_orders = mock_c.get("total_orders", len(orders) if orders else None)

        health_score, health_label = _customer_health(avg_csat, resolved_ratio)
        sentiment = _customer_sentiment(avg_csat)

        return {
            "name": name,
            "email": email_clean,
            "phone": mock_c.get("phone") or None,
            "tier": mock_c.get("loyalty_tier") or None,
            "health_score": health_score,
            "health_label": health_label,
            "lifetime_value": mock_c.get("lifetime_value") or None,
            "total_orders": total_orders,
            "location": None,
            "tags": list(mock_c.get("tags", [])),
            "total_tickets": total_tickets,
            "resolved_ratio": resolved_ratio,
            "avg_csat": avg_csat,
            "sentiment": sentiment,
            "last_active": last_active,
            "recent_conversations": convs_by_email.get(email_lower, []),
            "orders": orders,
            "demo": demo,
        }

    results = []
    seen_emails = set()
    
    # 1. Seed with MOCK_CUSTOMERS
    for cust in (_store_customers(db) if _STORE_DB else (MOCK_CUSTOMERS if USE_MOCK else [])):
        em = cust.get("email", "").strip()
        if not em or em.lower() in seen_emails:
            continue
        seen_emails.add(em.lower())
        results.append(build_customer_record(em, cust, demo=demo_mode))
        
    # 2. Add emails from MOCK_ORDERS not in MOCK_CUSTOMERS
    for order in (MOCK_ORDERS.values() if (USE_MOCK and not _STORE_DB) else []):
        em = order.get("email", "").strip()
        if not em or em.lower() in seen_emails:
            continue
        seen_emails.add(em.lower())
        results.append(build_customer_record(em, demo=demo_mode))
        
    # 3. Add any customers from DB
    for r in rows:
        em = (r.email or "").strip()
        if not em or em.lower() in seen_emails or em.lower().startswith("mockuser"):
            continue
        seen_emails.add(em.lower())
        results.append(build_customer_record(em))
        
    # Sort by total_tickets descending
    results.sort(key=lambda x: x["total_tickets"], reverse=True)
    
    return results

@router.get("/agent/customers/profile")
def get_customer_profile(
    email: str = Query(..., min_length=3, max_length=254),
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """One customer's facts for the conversation side panel.

    Cheap on purpose (queries only this email) so the panel can open instantly. Everything is
    limited to conversations this agent may see, and nothing is invented: an unknown email
    simply comes back with zero tickets and null ratings."""
    from sqlalchemy import func
    from app.services.mock_apis import MOCK_CUSTOMERS, MOCK_ORDERS

    em = email.strip().lower()
    base = scope_conversations(db.query(Conversation).filter(func.lower(Conversation.customer_email) == em), agent)
    total = base.count()
    resolved = base.filter(Conversation.resolved == True).count()  # noqa: E712
    first_seen, last_active = base.with_entities(func.min(Conversation.created_at), func.max(Conversation.created_at)).one()
    ids = [i for (i,) in base.with_entities(Conversation.id).all()]
    avg_csat = db.query(func.avg(CSATResponse.rating)).filter(CSATResponse.conversation_id.in_(ids)).scalar() if ids else None
    avg_csat = float(avg_csat) if avg_csat is not None else None
    resolved_ratio = (resolved / total) if total else None
    health_score, health_label = _customer_health(avg_csat, resolved_ratio)

    demo_mode = bool(USE_MOCK and not _STORE_DB)
    mock_c = next((c for c in (MOCK_CUSTOMERS if demo_mode else []) if (c.get("email") or "").strip().lower() == em), {})
    orders = [o for o in MOCK_ORDERS.values() if o.get("email", "").lower() == em] if demo_mode else []

    recent = base.order_by(Conversation.created_at.desc()).limit(8).all()
    return {
        "email": email.strip(),
        "name": mock_c.get("name"),
        "phone": mock_c.get("phone") or None,
        "tier": mock_c.get("loyalty_tier") or None,
        "lifetime_value": mock_c.get("lifetime_value") or None,
        "total_orders": mock_c.get("total_orders", len(orders) if orders else None),
        "tags": list(mock_c.get("tags", [])),
        "orders": orders,
        "total_tickets": total,
        "resolved_ratio": resolved_ratio,
        "avg_csat": avg_csat,
        "csat_count": int(db.query(func.count(CSATResponse.id)).filter(CSATResponse.conversation_id.in_(ids)).scalar() or 0) if ids else 0,
        "health_score": health_score,
        "health_label": health_label,
        "sentiment": _customer_sentiment(avg_csat),
        "first_seen": first_seen.isoformat() if first_seen else None,
        "last_active": last_active.isoformat() if last_active else None,
        "demo": demo_mode and bool(mock_c or orders),
        "recent_conversations": [{
            "session_id": c.session_id, "short_id": c.short_id, "resolved": bool(c.resolved), "priority": c.priority or "normal",
            "created_at": c.created_at.isoformat() if c.created_at else None, "summary": c.summary,
            "customer_email": c.customer_email,
        } for c in recent],
    }


class CreateSavedViewRequest(BaseModel):
    name: str = Field(..., max_length=80)
    filter_json: str = Field(..., max_length=2000)

@router.get("/agent/saved-views")
def get_saved_views(
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
):
    views = db.query(SavedView).filter(SavedView.agent_username == agent.username).all()
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
    view = db.query(SavedView).filter(SavedView.id == view_id, SavedView.agent_username == agent.username).first()
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
    q = scope_conversations(_apply_conversation_filters(q, priority, assigned_agent, tag), agent)
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
    q = scope_conversations(_apply_conversation_filters(q, priority, assigned_agent, tag), agent)
    convs = q.options(selectinload(Conversation.messages)).outerjoin(
        Message, Conversation.id == Message.conversation_id
    ).filter(
        Conversation.resolved == False,
        or_(
            Conversation.handled_by == agent.username,
            (Message.sender == "agent_internal") & (Message.content.like(f"%@{agent.username}%"))
        )
    ).distinct().order_by(Conversation.updated_at.desc()).all()
    
    sla_policy = get_sla_policy(db)
    results = []
    for c in convs:
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
    q = scope_conversations(_apply_conversation_filters(q, priority, assigned_agent, tag), agent)
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
    q = scope_conversations(_apply_conversation_filters(q, priority, assigned_agent, tag), agent)
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
    conversation = get_conversation_or_404(db, agent, session_id, options=(selectinload(Conversation.messages),))
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
    conversation = get_conversation_or_404(db, agent, session_id)
    agent_roles = {a.username: a.role for a in db.query(Agent).all()}
    
    return {
        "messages": [
            {
                "id": m.id, 
                "sender": m.sender, 
                "content": resign_text(m.content), 
                "created_at": m.created_at.isoformat(), 
                "author_username": m.author_username,
                "author_role": agent_roles.get(m.author_username, "agent") if m.author_username else "agent",
                "is_pinned": getattr(m, 'is_pinned', False)
            }
            for m in conversation.messages
        ]
    }


@router.post("/agent/conversations/{session_id}/revoke-session")
def revoke_customer_session(
    session_id: str,
    request: Request,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> dict:
    """Invalidate the customer's session token (abuse, compromised device,
    support request). The live WebSocket is dropped on its next message."""
    conversation = get_conversation_or_404(db, agent, session_id)
    revoke_session(db, session_id, agent.username, "revoked by agent")
    add_audit(db, agent.username, "revoke_customer_session", session_id, ip=request.client.host if request.client else None)
    db.commit()
    return {"status": "revoked", "session_id": session_id}


@router.post("/agent/conversations/{session_id}/resolve")
def resolve_conversation(
    session_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> dict:
    conversation = get_conversation_or_404(db, agent, session_id)
    _do_resolve_conversation(conversation, agent.username, db, background_tasks)
    db.commit()
    resolved_at_iso = conversation.resolved_at.isoformat() if conversation.resolved_at else datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()
    return {"status": "resolved", "session_id": session_id, "resolved_at": resolved_at_iso}


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
    conversation = get_conversation_or_404(db, agent, session_id)

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
        
    conv = db.query(Conversation).filter_by(id=msg.conversation_id).first()
    if conv is None or not can_access_conversation(db, agent, conv):
        raise HTTPException(status_code=404, detail="Message not found")

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
            "content": resign_text(m.content),
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
    conversation = get_conversation_or_404(db, agent, session_id)

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
    request: Request,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> dict | None:
    """Retrieve order and customer context for a conversation.
    Prioritizes order ID in messages, then stored customer email."""
    conversation = get_conversation_or_404(db, agent, session_id)

    # Reading order + customer PII from the commerce backend is an audited event.
    audit_now(db, agent.username, "read_order_context", session_id, ip=request.client.host if request.client else None)

    # helper
    def build_response(order, source):
        resp = {"source": source, "demo": USE_MOCK and not _STORE_DB}
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
        
    if len(payload.session_ids) > 200:
        raise HTTPException(status_code=400, detail="At most 200 conversations per bulk action")
    conversations = scope_conversations(
        db.query(Conversation).filter(Conversation.session_id.in_(payload.session_ids)), agent
    ).all()
    
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
        except ValueError:  # nosec B110 - malformed setting falls back to defaults below
            pass
    return {"urgent": 15, "high": 60, "normal": 240, "low": 1440}

def get_sla_status(c: Conversation, sla_policy: dict) -> str:
    if c.resolved or not getattr(c, "handoff_active", False):
        return "ok"
        
    import datetime
    
    target_time = c.created_at
    customer_waiting = True
    
    if hasattr(c, "messages") and c.messages:
        for msg in reversed(c.messages):
            if msg.sender == "agent":
                customer_waiting = False
                break
            if msg.sender == "human":
                target_time = msg.created_at
                break
                
    if not customer_waiting:
        return "ok"

    if target_time.tzinfo is None:
        target_utc = target_time.replace(tzinfo=datetime.timezone.utc)
    else:
        target_utc = target_time.astimezone(datetime.timezone.utc)
        
    age_minutes = (datetime.datetime.now(datetime.timezone.utc) - target_utc).total_seconds() / 60
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
        "resolved_at": c.resolved_at.isoformat() if getattr(c, "resolved_at", None) else None,
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
    source = get_conversation_or_404(db, agent, session_id)

    target = scope_conversations(
        db.query(Conversation).filter((Conversation.session_id == payload.target_session_id) | (Conversation.short_id == payload.target_session_id)),
        agent,
    ).first()
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
