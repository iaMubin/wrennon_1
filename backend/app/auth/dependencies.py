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

from app.auth.security import decode_access_token, verify_password
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.db.models import ApiKey
import datetime
from app.db.session import get_db
from app.db.tenancy import bind_session
from app.services import ratelimit
from app.db.models import Agent

# tokenUrl points at the login endpoint — used only for generating
# OpenAPI docs (the "Authorize" button in /docs), not for routing logic.
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/agent/login")


_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


async def get_current_agent(request: Request, db: Session = Depends(get_db)) -> Agent:
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
        
    # Bind the tenant for this request: the ORM filters every query by it and helper
    # sessions / background tasks spawned from here inherit it. This dependency is
    # async so the ContextVar set here is visible to the (sync) endpoint that follows.
    bind_session(db, agent.tenant_id)
    return agent


def get_current_manager(agent: Agent = Depends(get_current_agent)) -> Agent:
    if not agent.has_permission("manage_agents"):
        raise HTTPException(status_code=403, detail="Manager or Admin access required")
    return agent

api_key_scheme = HTTPBearer(auto_error=False)

API_KEY_SCOPES = {
    "conversations:read": "List and read conversations (customer-visible messages only)",
    "notes:read": "Also read internal notes / system messages",
    "notes:write": "Add internal notes",
    "messages:send": "Send customer-visible messages (only while a human handoff is active)",
    "conversations:resolve": "Resolve conversations",
}


async def get_api_key(
    request: Request,
    db: Session = Depends(get_db),
    auth: HTTPAuthorizationCredentials = Depends(api_key_scheme)
) -> ApiKey:
    ip = request.client.host if request.client else "unknown"
    # Failed-auth throttle: bcrypt verification is deliberately slow, so unlimited
    # bad keys is also a CPU-exhaustion vector.
    if await ratelimit.peek(f"apikey_fail:{ip}") >= 20:
        raise HTTPException(status_code=429, detail="Too many failed attempts")

    async def _fail(detail: str):
        await ratelimit.hit(f"apikey_fail:{ip}", 600)
        raise HTTPException(status_code=401, detail=detail)

    if not auth or auth.scheme.lower() != "bearer":
        await _fail("Invalid or missing API Key")

    raw_key = auth.credentials
    if not raw_key.startswith("wk_live_") or len(raw_key) > 128:
        await _fail("Invalid API Key format")

    prefix = raw_key[:16]
    now = datetime.datetime.now(datetime.timezone.utc)

    # Find all keys that match this prefix (usually just 1, but we'll check hashes)
    keys = db.query(ApiKey).filter_by(prefix=prefix, is_active=True).all()

    for key in keys:
        if verify_password(raw_key, key.key_hash):
            expires = key.expires_at
            if expires is not None:
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=datetime.timezone.utc)
                if expires <= now:
                    await _fail("API Key expired")
            last = key.last_used_at
            if last is not None and last.tzinfo is None:
                last = last.replace(tzinfo=datetime.timezone.utc)
            if last is None or (now - last).total_seconds() > 60:   # not one write per request
                key.last_used_at = now
                db.commit()
            bind_session(db, key.tenant_id)   # a key only ever sees its own tenant's data
            return key

    await _fail("Invalid or revoked API Key")


def require_scope(scope: str):
    """Dependency factory: the authenticated key must carry *scope*."""

    async def _dep(api_key: ApiKey = Depends(get_api_key)) -> ApiKey:
        if scope not in api_key.scope_list:
            raise HTTPException(status_code=403, detail=f"API key lacks required scope: {scope}")
        return api_key

    return _dep
