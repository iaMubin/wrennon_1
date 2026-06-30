"""
FastAPI dependency for protecting agent-only routes.

Usage in a route: add `agent: str = Depends(get_current_agent)` as a
parameter. FastAPI runs this before the route's own code — if the
token is missing or invalid, the request is rejected with 401 before
any of the route's logic (or any database query) runs.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.auth.security import decode_access_token

# tokenUrl points at the login endpoint — used only for generating
# OpenAPI docs (the "Authorize" button in /docs), not for routing logic.
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/agent/login")


def get_current_agent(token: str = Depends(_oauth2_scheme)) -> str:
    username = decode_access_token(token)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username
