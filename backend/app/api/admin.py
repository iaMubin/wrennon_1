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
from app.db.models import Agent, Conversation
from app.db.session import get_db

router = APIRouter()

class AgentCreate(BaseModel):
    username: str
    full_name: str
    employee_id: str
    password: str
    role: str = "agent"

@router.get("/admin/agents")
def list_agents(
    db: Session = Depends(get_db),
    manager: Agent = Depends(get_current_manager),
) -> list[dict]:
    # Get all agents
    agents = db.query(Agent).all()
    
    # Get resolution stats
    results = db.query(
        Conversation.handled_by, 
        func.count(Conversation.id)
    ).filter(Conversation.resolved == True).group_by(Conversation.handled_by).all()
    
    stats_map = {handled_by: count for handled_by, count in results if handled_by}
    ai_count = next((count for handled_by, count in results if not handled_by), 0)

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
        "full_name": "Artificial Intelligence",
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
    db.commit()
    return {"status": "deleted", "username": username}


