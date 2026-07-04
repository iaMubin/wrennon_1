"""
Admin dashboard API endpoints.
Only accessible by agents with role='manager'.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.auth.dependencies import get_current_manager
from app.auth.security import hash_password
from app.db.models import Agent
from app.db.session import get_db

router = APIRouter()

class AgentCreate(BaseModel):
    username: str
    password: str
    role: str = "agent"

@router.get("/admin/agents")
def list_agents(
    db: Session = Depends(get_db),
    manager: Agent = Depends(get_current_manager),
) -> list[dict]:
    agents = db.query(Agent).all()
    return [{"username": a.username, "role": a.role, "created_at": a.created_at.isoformat()} for a in agents]

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

    new_agent = Agent(
        username=agent_in.username,
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
