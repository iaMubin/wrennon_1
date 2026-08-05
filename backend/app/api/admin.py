"""
Admin dashboard API endpoints.
Only accessible by agents with role='manager'.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from sqlalchemy import func
from app.auth.dependencies import get_current_manager
from app.auth.security import hash_password
from app.db.models import Agent, Conversation, AuditLog, ApiKey
import secrets
from app.db.session import get_db

import re

def validate_password(password: str) -> None:
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

class AgentCreate(BaseModel):
    username: str
    full_name: str
    employee_id: str
    password: str
    role: str = "agent"
    dp_url: str | None = None

class PasswordReset(BaseModel):
    new_password: str

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
        "dp_url": None
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
        
    if not manager.has_permission("manage_managers") and agent_in.role != "agent":
        raise HTTPException(status_code=403, detail="Managers can only create standard Agent accounts.")
        
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
        
    if not manager.has_permission("manage_managers") and agent.role != "agent":
        raise HTTPException(status_code=403, detail="Managers can only delete standard Agent accounts.")
        
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
        
    if not manager.has_permission("manage_managers") and agent.role != "agent":
        if agent.username != manager.username:
            raise HTTPException(status_code=403, detail="Managers can only update standard Agent accounts.")
            
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
        
    if not manager.has_permission("manage_managers") and agent.role != "agent":
        raise HTTPException(status_code=403, detail="Managers can only reset passwords for standard Agent accounts.")
        
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

from app.db.models import SystemSetting, KnowledgeGap, AnalyticsScorecard, Message
from app.services.vectorstore import insert_into_pinecone

class SettingUpdate(BaseModel):
    value: str

@router.get("/admin/settings/{key}")
def get_setting(key: str, db: Session = Depends(get_db), manager: Agent = Depends(get_current_manager)):
    setting = db.query(SystemSetting).filter_by(key=key).first()
    return {"key": key, "value": setting.value if setting else ""}

@router.put("/admin/settings/{key}")
def update_setting(key: str, payload: SettingUpdate, db: Session = Depends(get_db), manager: Agent = Depends(get_current_manager)):
    setting = db.query(SystemSetting).filter_by(key=key).first()
    if not setting:
        setting = SystemSetting(key=key, value=payload.value)
        db.add(setting)
    else:
        setting.value = payload.value
    db.commit()
    return {"status": "success", "key": key, "value": payload.value}

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

@router.post("/admin/knowledge-gaps/{gap_id}/approve")
def approve_knowledge_gap(gap_id: str, db: Session = Depends(get_db), manager: Agent = Depends(get_current_manager)):
    gap = db.query(KnowledgeGap).filter_by(id=gap_id).first()
    if not gap:
        raise HTTPException(status_code=404, detail="Gap not found")
    if gap.status != "pending":
        raise HTTPException(status_code=400, detail="Gap is already processed")
    
    # Sync to pinecone
    title = gap.question[:50] + "..." if len(gap.question) > 50 else gap.question
    insert_into_pinecone(title, gap.draft_article, f"KB_GAP_{gap.id}")
    
    gap.status = "approved"
    db.commit()
    return {"status": "success", "id": gap.id}

@router.post("/admin/knowledge-gaps/{gap_id}/reject")
def reject_knowledge_gap(gap_id: str, db: Session = Depends(get_db), manager: Agent = Depends(get_current_manager)):
    gap = db.query(KnowledgeGap).filter_by(id=gap_id).first()
    if not gap:
        raise HTTPException(status_code=404, detail="Gap not found")
    gap.status = "rejected"
    db.commit()
    return {"status": "success", "id": gap.id}

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
    conversations = (
        db.query(Conversation)
        .filter(func.lower(Conversation.customer_email) == email.lower().strip())
        .all()
    )
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
    db: Session = Depends(get_db),
    manager: Agent = Depends(get_current_manager),
) -> dict:
    """Supports GDPR Art. 17 (right to erasure) and the CCPA right to
    delete: permanently removes every conversation, message, scorecard,
    and knowledge-gap record tied to a customer's email. There is no
    undo — the audit log entry this leaves behind (which intentionally
    does not include message content) is the only record this happened."""
    conversations = (
        db.query(Conversation)
        .filter(func.lower(Conversation.customer_email) == email.lower().strip())
        .all()
    )
    if not conversations:
        raise HTTPException(status_code=404, detail="No data found for this email")

    conversation_ids = [c.id for c in conversations]

    # Child rows first — Conversation.messages has no delete cascade
    # configured, so deleting the parent directly would either leave
    # these orphaned or fail on the FK, depending on the database.
    db.query(Message).filter(Message.conversation_id.in_(conversation_ids)).delete(synchronize_session=False)
    db.query(AnalyticsScorecard).filter(AnalyticsScorecard.conversation_id.in_(conversation_ids)).delete(synchronize_session=False)
    db.query(KnowledgeGap).filter(KnowledgeGap.conversation_id.in_(conversation_ids)).delete(synchronize_session=False)
    db.query(Conversation).filter(Conversation.id.in_(conversation_ids)).delete(synchronize_session=False)

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
    name: str

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
        "created_by_username": k.created_by_username
    } for k in keys]

@router.post("/api-keys")
def create_api_key(
    payload: ApiKeyCreate,
    manager: Agent = Depends(get_current_manager),
    db: Session = Depends(get_db)
):
    if not manager.has_permission("manage_api_keys"):
        raise HTTPException(status_code=403, detail="Not authorized to manage API keys")
        
    raw_key = "wk_live_" + secrets.token_urlsafe(32)
    key_hash = hash_password(raw_key)
    prefix = raw_key[:16]
    
    new_key = ApiKey(
        name=payload.name,
        key_hash=key_hash,
        prefix=prefix,
        created_by_username=manager.username
    )
    db.add(new_key)
    db.commit()
    db.refresh(new_key)
    
    # Return the raw key ONLY ONCE
    return {
        "id": new_key.id,
        "name": new_key.name,
        "raw_key": raw_key,
        "created_at": new_key.created_at
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
    db.commit()
    return {"status": "success", "message": "API key revoked"}
