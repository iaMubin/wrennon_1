"""
Customer-facing REST endpoint. Only one job left here: when the
customer widget first loads, it needs the conversation history that
already happened (if this session_id has been seen before) before the
WebSocket connection takes over for everything that happens next.
"""

import asyncio
import datetime
import uuid

from fastapi import APIRouter, Depends, Request, Header, HTTPException, status, UploadFile, File, Body, BackgroundTasks
from sqlalchemy.orm import Session
import os
import re

from app.db.models import Agent, Conversation, CSATResponse
from app.services.public_identity import public_agent_name
from app.db.session import get_db
from app.limiter import limiter
from app.auth.security import create_session_token, decode_session_token, decode_access_token
from app.db.tenancy import bind_session
from app.auth.sessions import is_session_revoked
from app.auth.tenant_resolution import TENANT_KEY_HEADER, resolve_public_tenant
from app.auth.security import decode_session_claims
from app.services import uploads as upload_service
from app.services.uploads import ALLOWED_CONTENT_TYPES, ALLOWED_EXTENSIONS, MAX_FILE_SIZE  # noqa: F401  (re-exported)

router = APIRouter()

REOPEN_WINDOW_HOURS = 72


def verify_session_token(
    session_id: str,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid token")

    token = authorization.split(" ", 1)[1]
    claims = decode_session_claims(token)

    if not claims or claims["session_id"] != session_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token for this session")
    # Scope every query in this request to the tenant the token was minted for, then
    # check revocation (RevokedSession is not tenant-owned).
    bind_session(db, claims["tenant_id"])
    if is_session_revoked(db, session_id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token for this session")

def verify_upload_token(
    session_id: str,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> str:
    """Authenticate an upload. Returns "customer" or "agent".

    The agent branch now checks the agent still exists and that the token's
    token_version is current: before, any validly *signed* token was enough, so
    a revoked / logged-out agent token kept working for uploads.
    """
    def _agent_ok(token: str) -> bool:
        data = decode_access_token(token)
        if not data or not data.get("sub"):
            return False
        agent = db.query(Agent).filter_by(username=data["sub"]).first()
        return bool(agent and agent.token_version == data.get("tv"))

    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
        if decode_session_token(token) == session_id and not is_session_revoked(db, session_id):
            return "customer"
        if _agent_ok(token):
            return "agent"

    # Cookie fallback (agent dashboard): same CSRF mitigation as get_current_agent —
    # state-changing request, so a cookie-only credential must carry the custom header.
    cookie_token = request.cookies.get("access_token")
    if cookie_token and _agent_ok(cookie_token.replace("Bearer ", "")):
        if request.headers.get("X-Wrennon-Client") == "agent-dashboard":
            return "agent"
        raise HTTPException(
            status_code=403,
            detail="Missing required client header for cookie-authenticated request.",
        )

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid upload token")


@router.post("/chat/init")
@limiter.limit("100/minute;600/hour")
def init_session(request: Request, db: Session = Depends(get_db)):
    """Start a new session and get a signed token bound to the storefront's tenant."""
    tenant_id = resolve_public_tenant(db, request.headers.get(TENANT_KEY_HEADER))
    new_session_id = str(uuid.uuid4())
    token = create_session_token(new_session_id, tenant_id)
    from app.services.customer_auth import session_token_for_customer
    token = session_token_for_customer(new_session_id, request.headers.get("authorization"), tenant_id) or token
    return {"session_id": new_session_id, "token": token}


@router.get("/chat/{session_id}/status")
@limiter.limit("100/minute")
def session_status(
    request: Request, 
    session_id: str, 
    db: Session = Depends(get_db),
    _=Depends(verify_session_token)
) -> dict:
    """Check whether a session is still usable or expired."""
    conversation = db.query(Conversation).filter_by(session_id=session_id).first()
    if conversation is None:
        return {"status": "not_found"}

    if not conversation.resolved:
        return {"status": "active"}

    # Conversation was resolved — check if within 72-hour window
    if conversation.resolved_at:
        elapsed = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - conversation.resolved_at
        if elapsed.total_seconds() < REOPEN_WINDOW_HOURS * 3600:
            return {"status": "resolved_recent"}
        else:
            return {"status": "expired"}

    # resolved=True but no resolved_at (legacy data) — treat as expired
    return {"status": "expired"}


@router.get("/chat/{session_id}/history")
@limiter.limit("100/minute")
def get_history(
    request: Request, 
    session_id: str, 
    db: Session = Depends(get_db),
    _=Depends(verify_session_token)
) -> list[dict]:
    conversation = db.query(Conversation).filter_by(session_id=session_id).first()
    if conversation is None:
        return []
    # SECURITY: Whitelist-only approach — only explicitly approved sender
    # types are ever returned to the customer; a new internal sender type
    # does NOT leak unless it is added to the frozenset below.
    #
    # Identity is reported truthfully and identically to the live WebSocket
    # path: AI replies are "bot", human replies are "agent" with the agent's
    # FIRST name. (This used to collapse humans into "bot", so after a reload
    # a human's messages were shown as "AI Assistant" while live they showed
    # the agent's name.)
    CUSTOMER_VISIBLE_SENDERS = frozenset({"human", "ai", "agent"})
    # Strip [Translated: ...] tags from customer history so they don't see their own translations
    def clean_content(text):
        text = re.sub(r'\n\n\*\[Translated:.*?\]\*', '', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'\n\n\(Image Description:.*?\)', '', text, flags=re.DOTALL)
        text = re.sub(r'\[INTERNAL_IMAGE_DESC\].*?\[/INTERNAL_IMAGE_DESC\]', '', text, flags=re.DOTALL)
        return upload_service.resign_text(text.strip())

    visible = [m for m in conversation.messages if m.sender in CUSTOMER_VISIBLE_SENDERS]
    authors = {m.author_username for m in visible if m.sender == "agent" and m.author_username}
    first_names = {}
    if authors:
        rows = db.query(Agent.username, Agent.full_name).filter(Agent.username.in_(authors)).all()
        first_names = {u: public_agent_name(fn) for u, fn in rows}

    def _sender(m):
        return "user" if m.sender == "human" else ("agent" if m.sender == "agent" else "bot")

    return [
        {
            "sender": _sender(m),
            "content": clean_content(m.content),
            "created_at": m.created_at.isoformat(),
            "name": first_names.get(m.author_username) if m.sender == "agent" else None,
        }
        for m in visible
    ]


@router.post("/chat/upload/{session_id}")
@limiter.limit("20/minute")
async def upload_file(
    request: Request,
    session_id: str,
    file: UploadFile = File(...),
    _role: str = Depends(verify_upload_token),
):
    """Upload a file for the chat (audio, image, document)."""
    if not upload_service.SESSION_ID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session id")
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported file type")

    # Extension must also be on the allowlist — content_type is a
    # client-supplied header and trivially spoofable on its own.
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported file extension")

    # Read at most MAX+1 bytes: an unbounded read() let one request pull an
    # arbitrarily large body into memory before the size check ran.
    contents = await file.read(MAX_FILE_SIZE + 1)
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 2MB.")

    # Magic-byte check: the bytes must actually be what the extension claims.
    if not upload_service.content_matches_extension(ext, contents):
        raise HTTPException(status_code=415, detail="File content does not match its type")

    client_ip = request.client.host if request.client else "unknown"
    quota_error = await upload_service.check_quota(session_id, client_ip, len(contents))
    if quota_error:
        raise HTTPException(status_code=429, detail=quota_error)

    safe_filename = f"{uuid.uuid4().hex}{ext}"
    file_path = upload_service.resolve_path(session_id, safe_filename)
    if file_path is None:
        raise HTTPException(status_code=400, detail="Invalid upload target")
    await asyncio.to_thread(_write_bytes, file_path, contents)
    upload_service.note_stored(len(contents))

    file_url = upload_service.public_url(str(request.base_url), session_id, safe_filename)
    return {"url": file_url, "filename": safe_filename, "type": file.content_type}


def _write_bytes(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


@router.post("/chat/{session_id}/csat")
@limiter.limit("10/minute")
def submit_csat(
    request: Request,
    session_id: str,
    background_tasks: BackgroundTasks,
    rating: int = Body(..., embed=True),
    comment: str | None = Body(None, embed=True),
    db: Session = Depends(get_db),
    _=Depends(verify_session_token),
) -> dict:
    """Customer-submitted satisfaction rating after a conversation is
    resolved. One per conversation — resubmitting overwrites rather than
    creating duplicates, since a customer double-tapping a star button
    shouldn't be treated as two separate data points."""
    if rating < 1 or rating > 5:
        raise HTTPException(status_code=400, detail="rating must be between 1 and 5")

    conversation = db.query(Conversation).filter_by(session_id=session_id).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    comment = (comment or "").strip()[:1000] or None

    existing = db.query(CSATResponse).filter_by(conversation_id=conversation.id).first()
    if existing:
        existing.rating = rating
        existing.comment = comment
    else:
        db.add(CSATResponse(conversation_id=conversation.id, rating=rating, comment=comment))

    db.commit()

    if rating <= 2:
        from app.realtime.connection_manager import manager
        
        async def send_low_csat_alert():
            await manager.broadcast_to_agents({
                "type": "low_csat_alert",
                "session_id": session_id,
                "rating": rating,
                "comment": comment
            })
            
        background_tasks.add_task(send_low_csat_alert)

    return {"status": "success"}
