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
from app.db.models import Agent, Conversation, AuditLog
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
            "resolved_count": stats_map.get(a.username, 0)
        })
        
    # Append AI Agent
    directory.append({
        "full_name": "AI Agent",
        "username": "AI Agent",
        "employee_id": "AUTO",
        "role": "ai",
        "created_at": "",
        "resolved_count": ai_count
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
        
    if manager.role == "manager" and agent_in.role != "agent":
        raise HTTPException(status_code=403, detail="Managers can only create standard Agent accounts.")
        
    if db.query(Agent).filter_by(employee_id=agent_in.employee_id).first():
        raise HTTPException(status_code=400, detail="Employee ID already exists")

    new_agent = Agent(
        username=agent_in.username,
        full_name=agent_in.full_name,
        employee_id=agent_in.employee_id,
        password_hash=hash_password(agent_in.password),
        role=agent_in.role
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
        
    if manager.role == "manager" and agent.role != "agent":
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
        
    if manager.role == "manager" and agent.role != "agent":
        raise HTTPException(status_code=403, detail="Managers can only reset passwords for standard Agent accounts.")
        
    validate_password(payload.new_password)
        
    agent.password_hash = hash_password(payload.new_password)
    
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
