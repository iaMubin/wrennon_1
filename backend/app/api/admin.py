"""
Admin dashboard API endpoints.
Only accessible by agents with role='manager'.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, File, Request, UploadFile
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, field_validator
import datetime
import json
import os
from zoneinfo import ZoneInfo
import uuid

from sqlalchemy import func
from app.auth.dependencies import get_current_manager
from app.auth.dependencies import API_KEY_SCOPES
from app.db.models import Tenant
from app.security.secrets_box import SecretsUnavailable, encrypt as encrypt_secret
from app.services.integrations import invalidate_provider_cache
from app.auth.security import hash_password
from app.security.sanitize import clean_brand_voice
from app.services.audit import add_audit
from app.db.models import Agent, AuditLog, ApiKey
from app.services.erasure import find_conversations_for_email, erase_conversations
import secrets
from app.db.session import get_db

import re

def validate_password(password: str) -> None:
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="Password must be at most 72 bytes long")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long")
    if not re.search(r"[A-Z]", password):
        raise HTTPException(status_code=400, detail="Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        raise HTTPException(status_code=400, detail="Password must contain at least one lowercase letter")
    if not re.search(r"[0-9]", password):
        raise HTTPException(status_code=400, detail="Password must contain at least one number")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        raise HTTPException(status_code=400, detail="Password must contain at least one special character")

router = APIRouter()

# Role hierarchy. Account management is gated on rank, NOT just on the
# "manage_managers" permission: that permission used to be granted to every
# manager by default, which let any manager mint an admin account (admin has
# every permission) or reset an admin's password and take the account over.
_ROLE_RANK = {"agent": 0, "manager": 1, "admin": 2}


def _assert_may_assign_role(actor: Agent, new_role: str) -> None:
    """Only an admin may create/promote to admin; creating a manager needs an
    explicit manage_managers grant; anyone with account access may create agents."""
    if new_role == "agent":
        return
    if actor.role == "admin":
        return
    if new_role == "admin":
        raise HTTPException(status_code=403, detail="Only an admin can create admin accounts.")
    if not actor.has_permission("manage_managers"):
        raise HTTPException(status_code=403, detail="Managers can only create standard Agent accounts.")


def _assert_may_manage(actor: Agent, target: Agent) -> None:
    """Block acting on an account that outranks (or, without an explicit
    grant, equals) the actor. Admins can manage anyone."""
    if actor.role == "admin":
        return
    if _ROLE_RANK.get(target.role, 2) >= _ROLE_RANK.get(actor.role, 0) and target.username != actor.username:
        if target.role == "admin" or not actor.has_permission("manage_managers"):
            raise HTTPException(status_code=403, detail="You cannot manage an account with equal or higher privileges.")


def _safe_dp_url(v: str | None) -> str | None:
    """dp_url is rendered into <img src>. Allow only our own uploads/static
    images or an https URL — never javascript:/data: or attribute-breaking text."""
    if v is None or v == "":
        return None
    if len(v) > 500 or any(c in v for c in '"\'<>\\ \n\r\t'):
        raise ValueError("Invalid image URL")
    if v.startswith("/agent/images/") or v.startswith("https://"):
        return v
    raise ValueError("Image URL must be an uploaded image or an https URL")


class AgentCreate(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_.-]{3,32}$")
    full_name: str = Field(min_length=1, max_length=80, pattern=r"^[^<>\"'&`]+$")
    employee_id: str = Field(pattern=r"^[A-Za-z0-9-]{1,20}$")
    password: str = Field(max_length=128)
    role: str = "agent"
    dp_url: str | None = None

    _check_dp = field_validator("dp_url")(lambda cls, v: _safe_dp_url(v))

class PasswordReset(BaseModel):
    new_password: str

ALLOWED_DP_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_DP_BYTES = 2 * 1024 * 1024  # 2 MB


@router.post("/admin/upload-dp")
def upload_agent_dp(
    file: UploadFile = File(...),
    manager: Agent = Depends(get_current_manager)
):
    # Sync def on purpose: FastAPI runs it in a threadpool, so the blocking
    # file write below does not stall the event loop.
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_DP_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only png, jpg, jpeg, webp or gif images are allowed")

    upload_dir = os.path.join("app", "static", "agent", "images", "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    new_filename = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(upload_dir, new_filename)

    data = file.file.read(MAX_DP_BYTES + 1)
    if len(data) > MAX_DP_BYTES:
        raise HTTPException(status_code=413, detail="Image must be 2 MB or smaller")
    with open(file_path, "wb") as buffer:
        buffer.write(data)
        
    dp_url = f"/agent/images/uploads/{new_filename}"
    return {"status": "success", "dp_url": dp_url}

@router.get("/admin/agents")
def list_agents(
    db: Session = Depends(get_db),
    manager: Agent = Depends(get_current_manager),
) -> list[dict]:
    # Get all agents
    agents = db.query(Agent).all()

    # Get resolution stats from AuditLogs
    results = db.query(
        AuditLog.actor_username, 
        func.count(AuditLog.id)
    ).filter(AuditLog.action == "resolve_conversation").group_by(AuditLog.actor_username).all()
    
    stats_map = {actor: count for actor, count in results}
    ai_count = stats_map.get("AI Agent", 0)

    # Combine
    directory = []
    for a in agents:
        directory.append({
            "full_name": a.full_name or a.username.capitalize(),
            "username": a.username,
            "employee_id": a.employee_id or "N/A",
            "role": a.role,
            "created_at": a.created_at.isoformat(),
            "resolved_count": stats_map.get(a.username, 0),
            "dp_url": a.dp_url
        })
        
    # Append AI Agent
    directory.append({
        "full_name": "AI Agent",
        "username": "AI Agent",
        "employee_id": "AUTO",
        "role": "ai",
        "created_at": "",
        "resolved_count": ai_count,
        "dp_url": "/agent/images/wren-mark.svg"
    })
    
    return directory

@router.post("/admin/agents")
def create_agent(
    agent_in: AgentCreate,
    db: Session = Depends(get_db),
    manager: Agent = Depends(get_current_manager),
) -> dict:
    if db.query(Agent).filter_by(username=agent_in.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
        
    validate_password(agent_in.password)
    
    if agent_in.role not in ["agent", "manager", "admin"]:
        raise HTTPException(status_code=400, detail="Invalid role.")
        
    _assert_may_assign_role(manager, agent_in.role)

    if db.query(Agent).filter_by(employee_id=agent_in.employee_id).first():
        raise HTTPException(status_code=400, detail="Employee ID already exists")

    new_agent = Agent(
        username=agent_in.username,
        full_name=agent_in.full_name,
        employee_id=agent_in.employee_id,
        password_hash=hash_password(agent_in.password),
        role=agent_in.role,
        dp_url=agent_in.dp_url
    )
    db.add(new_agent)
    
    # Audit log
    audit = AuditLog(
        actor_username=manager.username,
        action="create_agent",
        target_username=agent_in.username,
        details=f"Role: {agent_in.role}"
    )
    db.add(audit)
    
    db.commit()
    return {"status": "success", "username": agent_in.username, "role": agent_in.role}

@router.delete("/admin/agents/{username}")
def delete_agent(
    username: str,
    db: Session = Depends(get_db),
    manager: Agent = Depends(get_current_manager),
) -> dict:
    agent = db.query(Agent).filter_by(username=username).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.username == manager.username:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    if agent.role == "admin" and manager.role != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can modify admin accounts.")
        
    _assert_may_manage(manager, agent)
        
    db.delete(agent)
    
    # Audit log
    audit = AuditLog(
        actor_username=manager.username,
        action="delete_agent",
        target_username=username,
    )
    db.add(audit)
    
    db.commit()
    return {"status": "deleted", "username": username}

class AgentUpdate(BaseModel):
    dp_url: str | None = None

    _check_dp = field_validator("dp_url")(lambda cls, v: _safe_dp_url(v))

@router.put("/admin/agents/{username}")
def update_agent(
    username: str,
    payload: AgentUpdate,
    db: Session = Depends(get_db),
    manager: Agent = Depends(get_current_manager),
) -> dict:
    agent = db.query(Agent).filter_by(username=username).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
        
    _assert_may_manage(manager, agent)

    agent.dp_url = payload.dp_url
    
    audit = AuditLog(
        actor_username=manager.username,
        action="update_agent",
        target_username=username,
        details=f"Updated dp_url"
    )
    db.add(audit)
    db.commit()
    
    return {"status": "success", "username": username, "dp_url": agent.dp_url}

@router.put("/admin/agents/{username}/reset-password")
def reset_password(
    username: str,
    payload: PasswordReset,
    db: Session = Depends(get_db),
    manager: Agent = Depends(get_current_manager),
) -> dict:
    agent = db.query(Agent).filter_by(username=username).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
        
    _assert_may_manage(manager, agent)

    validate_password(payload.new_password)
        
    agent.password_hash = hash_password(payload.new_password)
    agent.token_version = (agent.token_version or 1) + 1
    
    # Audit log
    audit = AuditLog(
        actor_username=manager.username,
        action="reset_password",
        target_username=username,
    )
    db.add(audit)
    
    db.commit()
    return {"status": "success", "username": username}

@router.get("/admin/logs")
def get_audit_logs(
    db: Session = Depends(get_db),
    manager: Agent = Depends(get_current_manager),
) -> list[dict]:
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(100).all()
    return [
        {
            "id": log.id,
            "actor": log.actor_username,
            "action": log.action,
            "target": log.target_username,
            "details": log.details,
            "created_at": log.created_at.isoformat()
        }
        for log in logs
    ]

from app.db.models import SystemSetting, KnowledgeGap, AnalyticsScorecard
from app.security.kb_guard import MAX_ARTICLE_CHARS, review_findings
from app.services.vectorstore import delete_from_pinecone, insert_into_pinecone

class SettingUpdate(BaseModel):
    value: str = Field(..., max_length=4000)


_VALID_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _validate_business_hours(raw: str) -> str:
    if not raw.strip():
        return ""  # empty = always open
    try:
        data = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="business_hours must be valid JSON")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="business_hours must be a JSON object")
    tz = data.get("timezone", "UTC")
    try:
        ZoneInfo(tz)
    except Exception:
        raise HTTPException(status_code=400, detail="Unknown timezone")
    for k, v in data.items():
        if k == "timezone":
            continue
        if k not in _VALID_DAYS:
            raise HTTPException(status_code=400, detail=f"Unknown key '{k}'")
        if v in (None, []):
            continue
        if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, str) and _HHMM.match(x) for x in v)):
            raise HTTPException(status_code=400, detail=f"{k} must be [\"HH:MM\", \"HH:MM\"] or null")
    return json.dumps(data)


def _validate_sla_policy(raw: str) -> str:
    try:
        data = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="sla_policy must be valid JSON")
    if not isinstance(data, dict) or set(data) - {"urgent", "high", "normal", "low"}:
        raise HTTPException(status_code=400, detail="sla_policy keys must be urgent/high/normal/low")
    for k, v in data.items():
        if not isinstance(v, int) or isinstance(v, bool) or not (1 <= v <= 10080):
            raise HTTPException(status_code=400, detail=f"{k} must be minutes between 1 and 10080")
    return json.dumps(data)


def _validate_brand_voice(raw: str) -> str:
    return clean_brand_voice(raw)


# Only these keys exist. The endpoint used to accept ANY key/value pair, so a
# manager session could plant arbitrary settings (and brand_voice is injected
# straight into the system prompt).
SETTING_VALIDATORS = {
    "brand_voice": _validate_brand_voice,
    "business_hours": _validate_business_hours,
    "sla_policy": _validate_sla_policy,
}


def _check_setting_key(key: str) -> None:
    if key not in SETTING_VALIDATORS:
        raise HTTPException(status_code=404, detail="Unknown setting")


@router.get("/admin/settings/{key}")
def get_setting(key: str, db: Session = Depends(get_db), manager: Agent = Depends(get_current_manager)):
    _check_setting_key(key)
    setting = db.query(SystemSetting).filter_by(key=key).first()
    return {"key": key, "value": setting.value if setting else ""}


@router.put("/admin/settings/{key}")
def update_setting(
    key: str,
    payload: SettingUpdate,
    request: Request,
    db: Session = Depends(get_db),
    manager: Agent = Depends(get_current_manager),
):
    _check_setting_key(key)
    value = SETTING_VALIDATORS[key](payload.value)
    setting = db.query(SystemSetting).filter_by(key=key).first()
    old = setting.value if setting else ""
    if not setting:
        setting = SystemSetting(key=key, value=value)
        db.add(setting)
    else:
        setting.value = value
    add_audit(
        db, manager.username, "update_setting", key,
        details=f"old={old[:120]!r} new={value[:120]!r} (len {len(old)}->{len(value)})",
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return {"status": "success", "key": key, "value": value}

@router.get("/admin/knowledge-gaps")
def list_knowledge_gaps(db: Session = Depends(get_db), manager: Agent = Depends(get_current_manager)):
    gaps = db.query(KnowledgeGap).order_by(KnowledgeGap.created_at.desc()).limit(50).all()
    return [{
        "id": g.id,
        "conversation_id": g.conversation_id,
        "question": g.question,
        "draft_article": g.draft_article,
        "status": g.status,
        "created_at": g.created_at.isoformat()
    } for g in gaps]

class GapApproval(BaseModel):
    # The reviewer may correct the draft; the text that is indexed is exactly this
    # (or the draft if omitted) and it must pass review_findings().
    edited_article: str | None = Field(None, max_length=MAX_ARTICLE_CHARS * 2)
    confirm_reviewed: bool = False


@router.post("/admin/knowledge-gaps/{gap_id}/approve")
def approve_knowledge_gap(
    gap_id: str,
    request: Request,
    payload: GapApproval | None = None,
    db: Session = Depends(get_db),
    manager: Agent = Depends(get_current_manager),
):
    payload = payload or GapApproval()
    gap = db.query(KnowledgeGap).filter_by(id=gap_id).first()
    if not gap:
        raise HTTPException(status_code=404, detail="Gap not found")
    if gap.status != "pending":
        raise HTTPException(status_code=400, detail="Gap is already processed")
    if not payload.confirm_reviewed:
        raise HTTPException(status_code=422, detail="Review the article text and send confirm_reviewed=true")

    text = (payload.edited_article if payload.edited_article is not None else gap.draft_article).strip()
    findings = review_findings(text)
    if findings:
        raise HTTPException(status_code=422, detail={"message": "Article cannot be published as written", "findings": findings})

    title = gap.question[:50] + "..." if len(gap.question) > 50 else gap.question
    insert_into_pinecone(title, text, f"KB_GAP_{gap.id}", approved_by=manager.username)

    gap.status = "approved"
    gap.reviewed_by = manager.username
    gap.reviewed_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    gap.published_text = text
    add_audit(db, manager.username, "kb_gap_publish", gap.id, details=f"edited={payload.edited_article is not None} len={len(text)}",
              ip=request.client.host if request.client else None)
    db.commit()
    return {"status": "success", "id": gap.id}


@router.post("/admin/knowledge-gaps/{gap_id}/reject")
def reject_knowledge_gap(gap_id: str, db: Session = Depends(get_db), manager: Agent = Depends(get_current_manager)):
    gap = db.query(KnowledgeGap).filter_by(id=gap_id).first()
    if not gap:
        raise HTTPException(status_code=404, detail="Gap not found")
    gap.status = "rejected"
    gap.reviewed_by = manager.username
    add_audit(db, manager.username, "kb_gap_reject", gap.id)
    db.commit()
    return {"status": "success", "id": gap.id}


@router.post("/admin/knowledge-gaps/{gap_id}/unpublish")
def unpublish_knowledge_gap(gap_id: str, db: Session = Depends(get_db), manager: Agent = Depends(get_current_manager)):
    """Pull a published article back out of the index (bad content, poisoning, PII)."""
    gap = db.query(KnowledgeGap).filter_by(id=gap_id).first()
    if not gap or gap.status != "approved":
        raise HTTPException(status_code=404, detail="No published article for this id")
    delete_from_pinecone(f"KB_GAP_{gap.id}")
    gap.status = "unpublished"
    add_audit(db, manager.username, "kb_gap_unpublish", gap.id)
    db.commit()
    return {"status": "unpublished", "id": gap.id}

@router.get("/admin/analytics/scorecards")
def get_analytics_scorecards(db: Session = Depends(get_db), manager: Agent = Depends(get_current_manager)):
    cards = db.query(AnalyticsScorecard).order_by(AnalyticsScorecard.created_at.desc()).limit(50).all()
    return [{
        "id": c.id,
        "conversation_id": c.conversation_id,
        "empathy_score": c.empathy_score,
        "accuracy_score": c.accuracy_score,
        "resolution_score": c.resolution_score,
        "csat_prediction": c.csat_prediction,
        "feedback_notes": c.feedback_notes,
        "created_at": c.created_at.isoformat()
    } for c in cards]


@router.get("/admin/customer-data")
def export_customer_data(
    email: str,
    db: Session = Depends(get_db),
    manager: Agent = Depends(get_current_manager),
) -> dict:
    """Supports GDPR Art. 15/20 (right of access / data portability) and
    the CCPA right to know: returns every conversation and message tied
    to a customer's email in one payload, for an agent to hand over when
    a customer asks what data is held on them. Case-insensitive match,
    since the email is stored exactly as the customer typed it and
    wasn't normalized at capture time."""
    conversations = find_conversations_for_email(db, email)
    if not conversations:
        raise HTTPException(status_code=404, detail="No data found for this email")

    export = [
        {
            "conversation_id": conv.id,
            "session_id": conv.session_id,
            "created_at": conv.created_at.isoformat(),
            "resolved": conv.resolved,
            "sentiment": conv.sentiment,
            "intent_category": conv.intent_category,
            "messages": [
                {
                    "sender": m.sender,
                    "content": m.content,
                    "created_at": m.created_at.isoformat(),
                }
                for m in conv.messages
            ],
        }
        for conv in conversations
    ]

    audit = AuditLog(
        actor_username=manager.username,
        action="export_customer_data",
        target_username=email,
        details=f"{len(conversations)} conversation(s) exported",
    )
    db.add(audit)
    db.commit()

    return {"email": email, "conversations": export}


@router.delete("/admin/customer-data")
def delete_customer_data(
    email: str,
    dry_run: bool = False,
    db: Session = Depends(get_db),
    manager: Agent = Depends(get_current_manager),
) -> dict:
    """Supports GDPR Art. 17 (right to erasure) and the CCPA right to
    delete: permanently removes every conversation, message, scorecard,
    and knowledge-gap record tied to a customer's email. There is no
    undo — the audit log entry this leaves behind (which intentionally
    does not include message content) is the only record this happened."""
    conversations = find_conversations_for_email(db, email)
    if not conversations:
        raise HTTPException(status_code=404, detail="No data found for this email")

    conversation_ids = [c.id for c in conversations]
    if dry_run:
        # Lets the operator see the blast radius before an irreversible delete.
        return {"status": "dry_run", "email": email, "conversations_matched": len(conversation_ids)}

    from app.services.uploads import UPLOAD_DIR
    erase_conversations(db, conversation_ids, upload_dir=UPLOAD_DIR, actor=manager.username)

    audit = AuditLog(
        actor_username=manager.username,
        action="delete_customer_data",
        target_username=email,
        details=f"{len(conversation_ids)} conversation(s) permanently erased",
    )
    db.add(audit)
    db.commit()

    return {"status": "deleted", "email": email, "conversations_removed": len(conversation_ids)}

class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[^<>\"'&`]+$")
    # Least privilege by default: read-only, expires in 90 days.
    scopes: list[str] = Field(default_factory=lambda: ["conversations:read"])
    expires_in_days: int | None = Field(90, ge=1, le=365)

@router.get("/api-keys")
def list_api_keys(
    manager: Agent = Depends(get_current_manager),
    db: Session = Depends(get_db)
):
    if not manager.has_permission("manage_api_keys"):
        raise HTTPException(status_code=403, detail="Not authorized to manage API keys")
        
    keys = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
    return [{
        "id": k.id,
        "name": k.name,
        "prefix": k.prefix,
        "created_at": k.created_at,
        "last_used_at": k.last_used_at,
        "is_active": k.is_active,
        "created_by_username": k.created_by_username,
        "scopes": k.scope_list,
        "expires_at": k.expires_at,
        "revoked_by": k.revoked_by,
    } for k in keys]

@router.post("/api-keys")
def create_api_key(
    payload: ApiKeyCreate,
    manager: Agent = Depends(get_current_manager),
    db: Session = Depends(get_db)
):
    if not manager.has_permission("manage_api_keys"):
        raise HTTPException(status_code=403, detail="Not authorized to manage API keys")
        
    unknown = set(payload.scopes) - set(API_KEY_SCOPES)
    if unknown or not payload.scopes:
        raise HTTPException(status_code=400, detail=f"Invalid scopes. Allowed: {sorted(API_KEY_SCOPES)}")
    if db.query(ApiKey).filter_by(is_active=True).count() >= 50:
        raise HTTPException(status_code=400, detail="Too many active API keys; revoke unused ones first")

    raw_key = "wk_live_" + secrets.token_urlsafe(32)
    key_hash = hash_password(raw_key)
    prefix = raw_key[:16]
    expires_at = (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=payload.expires_in_days)
        if payload.expires_in_days else None
    )

    new_key = ApiKey(
        name=payload.name,
        key_hash=key_hash,
        prefix=prefix,
        created_by_username=manager.username,
        scopes=json.dumps(sorted(set(payload.scopes))),
        expires_at=expires_at,
    )
    db.add(new_key)
    add_audit(db, manager.username, "create_api_key", payload.name[:80],
              details=f"prefix={prefix} scopes={','.join(sorted(set(payload.scopes)))} expires={expires_at.date() if expires_at else 'never'}")
    db.commit()
    db.refresh(new_key)
    
    # Return the raw key ONLY ONCE
    return {
        "id": new_key.id,
        "name": new_key.name,
        "raw_key": raw_key,
        "created_at": new_key.created_at,
        "scopes": new_key.scope_list,
        "expires_at": new_key.expires_at,
    }

@router.delete("/api-keys/{key_id}")
def revoke_api_key(
    key_id: str,
    manager: Agent = Depends(get_current_manager),
    db: Session = Depends(get_db)
):
    if not manager.has_permission("manage_api_keys"):
        raise HTTPException(status_code=403, detail="Not authorized to manage API keys")
        
    key = db.query(ApiKey).filter_by(id=key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="API Key not found")
        
    key.is_active = False
    key.revoked_at = datetime.datetime.now(datetime.timezone.utc)
    key.revoked_by = manager.username
    add_audit(db, manager.username, "revoke_api_key", key.name[:80], details=f"prefix={key.prefix}")
    db.commit()
    return {"status": "success", "message": "API key revoked"}


# --------------------------------------------------------------------------
# Tenant (store) settings: each tenant manages ONLY its own record.
# --------------------------------------------------------------------------
_SHOPIFY_HOST = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}\.myshopify\.com$")


class ShopifyCredentials(BaseModel):
    store_url: str = Field(..., max_length=120)
    access_token: str = Field(..., min_length=10, max_length=200)


def _own_tenant(db: Session, manager: Agent) -> Tenant:
    tenant = db.get(Tenant, manager.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.get("/admin/tenant")
def get_tenant(db: Session = Depends(get_db), manager: Agent = Depends(get_current_manager)):
    t = _own_tenant(db, manager)
    return {
        "id": t.id, "slug": t.slug, "name": t.name, "public_key": t.public_key,
        "shopify_store_url": t.shopify_store_url,
        "shopify_configured": bool(t.shopify_store_url and t.shopify_token_enc),   # never the token itself
    }


@router.put("/admin/tenant/shopify")
def set_tenant_shopify(
    payload: ShopifyCredentials,
    request: Request,
    db: Session = Depends(get_db),
    manager: Agent = Depends(get_current_manager),
):
    if manager.role != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can change store credentials")
    store = payload.store_url.strip().lower().removeprefix("https://").rstrip("/")
    if not _SHOPIFY_HOST.match(store):
        raise HTTPException(status_code=400, detail="store_url must look like your-store.myshopify.com")
    try:
        encrypted = encrypt_secret(payload.access_token.strip())
    except SecretsUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    t = _own_tenant(db, manager)
    t.shopify_store_url = store
    t.shopify_token_enc = encrypted
    add_audit(db, manager.username, "set_tenant_shopify", t.id, details=f"store={store}", ip=request.client.host if request.client else None)
    db.commit()
    invalidate_provider_cache(t.id)
    return {"status": "success", "shopify_store_url": store}


@router.delete("/admin/tenant/shopify")
def clear_tenant_shopify(db: Session = Depends(get_db), manager: Agent = Depends(get_current_manager)):
    if manager.role != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can change store credentials")
    t = _own_tenant(db, manager)
    t.shopify_store_url = None
    t.shopify_token_enc = None
    add_audit(db, manager.username, "clear_tenant_shopify", t.id)
    db.commit()
    invalidate_provider_cache(t.id)
    return {"status": "success"}
