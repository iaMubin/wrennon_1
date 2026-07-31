"""
FastAPI dependency for protecting agent-only routes.

Usage in a route: add `agent: Agent = Depends(get_current_agent)` as a
parameter. FastAPI runs this before the route's own code — if the
token is missing or invalid, the request is rejected with 401 before
any of the route's logic (or any database query) runs.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.db.session import get_db
from app.db.models import Agent

# tokenUrl points at the login endpoint — used only for generating
# OpenAPI docs (the "Authorize" button in /docs), not for routing logic.
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/agent/login")


_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_current_agent(request: Request, db: Session = Depends(get_db)) -> Agent:
    # First try Authorization header, then fallback to cookie
    token = request.headers.get("Authorization")
    used_cookie_fallback = False
    if token and token.startswith("Bearer "):
        token = token.replace("Bearer ", "")
    else:
        token = request.cookies.get("access_token")
        if token and token.startswith("Bearer "):
            token = token.replace("Bearer ", "")
            used_cookie_fallback = True

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # CSRF mitigation: a browser attaches cookies to cross-site requests
    # automatically (that's the whole problem CSRF exploits), but it will
    # NOT attach an Authorization header, and it cannot add an arbitrary
    # custom header to a cross-site request without the target's CORS
    # policy explicitly allowing that origin first. So for any
    # state-changing request authenticated purely via the cookie (no
    # Authorization header present), require this custom header — a
    # same-site JS client can always set it, a cross-site <form> submit
    # or plain cross-site fetch cannot.
    if used_cookie_fallback and request.method.upper() not in _SAFE_METHODS:
        if request.headers.get("X-Wrennon-Client") != "agent-dashboard":
            raise HTTPException(
                status_code=403,
                detail="Missing required client header for cookie-authenticated request.",
            )
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
        
    # Check for token revocation (password change, or an explicit
    # revoke-all-sessions bump) via the token_version counter.
    if token_data.get("tv") != agent.token_version:
        raise HTTPException(status_code=401, detail="Token revoked (password was changed)")
        
    return agent


def get_current_manager(agent: Agent = Depends(get_current_agent)) -> Agent:
    if agent.role not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Manager or Admin access required")
    return agent
