"""
FastAPI dependency for protecting agent-only routes.

Usage in a route: add `agent: Agent = Depends(get_current_agent)` as a
parameter. FastAPI runs this before the route's own code — if the
token is missing or invalid, the request is rejected with 401 before
any of the route's logic (or any database query) runs.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.db.session import get_db
from app.db.models import Agent

# tokenUrl points at the login endpoint — used only for generating
# OpenAPI docs (the "Authorize" button in /docs), not for routing logic.
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/agent/login")


def get_current_agent(token: str = Depends(_oauth2_scheme), db: Session = Depends(get_db)) -> Agent:
    token_data = decode_access_token(token)
    if token_data is None or not token_data.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    username = token_data["sub"]
    agent = db.query(Agent).filter_by(username=username).first()
    if agent is None:
        raise HTTPException(status_code=401, detail="Agent not found")
        
    # Check for token revocation via password change
    expected_frag = agent.password_hash[-10:] if agent.password_hash else ""
    if token_data.get("pwd_frag") != expected_frag:
        raise HTTPException(status_code=401, detail="Token revoked (password was changed)")
        
    return agent


def get_current_manager(agent: Agent = Depends(get_current_agent)) -> Agent:
    if agent.role != "manager":
        raise HTTPException(status_code=403, detail="Manager access required")
    return agent
