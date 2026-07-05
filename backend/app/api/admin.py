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
    
    # Quick backfill for legacy resolved conversations that have no audit log
    legacy_conversations = db.query(Conversation).filter(Conversation.resolved == True).all()
    for c in legacy_conversations:
        actor = c.handled_by if c.handled_by else "AI Agent"
        existing = db.query(AuditLog).filter_by(action="resolve_conversation", target_username=c.session_id).first()
        if not existing:
            db.add(AuditLog(actor_username=actor, action="resolve_conversation", target_username=c.session_id))
    db.commit()

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
    
    if agent_in.role not in ["agent", "manager"]:
        raise HTTPException(status_code=400, detail="Invalid role. Must be 'agent' or 'manager'")
        
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


