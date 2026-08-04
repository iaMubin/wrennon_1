"""
Customer-facing REST endpoint. Only one job left here: when the
customer widget first loads, it needs the conversation history that
already happened (if this session_id has been seen before) before the
WebSocket connection takes over for everything that happens next.
"""

import datetime
import uuid

from fastapi import APIRouter, Depends, Request, Header, HTTPException, status, UploadFile, File, Body, BackgroundTasks, BackgroundTasks
from sqlalchemy.orm import Session
import shutil
import os
import re

from app.db.models import Conversation, CSATResponse
from app.db.session import get_db
from app.limiter import limiter
from app.auth.security import create_session_token, decode_session_token, decode_access_token

router = APIRouter()

REOPEN_WINDOW_HOURS = 72


def verify_session_token(session_id: str, authorization: str | None = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid token")
    
    token = authorization.split(" ")[1]
    decoded_session = decode_session_token(token)
    
    if not decoded_session or decoded_session != session_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token for this session")

def verify_upload_token(session_id: str, request: Request, authorization: str | None = Header(None)):
    # Customer widget always sends its session token via the Authorization
    # header (it has no cookie). Agent uploads can arrive either way.
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]

        decoded_session = decode_session_token(token)
        if decoded_session and decoded_session == session_id:
            return

        agent_data = decode_access_token(token)
        if agent_data and agent_data.get("sub"):
            return

    # Cookie fallback (agent dashboard, which no longer keeps the JWT in
    # localStorage): same CSRF mitigation as get_current_agent — this is a
    # state-changing request, so a cookie-only credential must also carry
    # the custom header a cross-site request can't add.
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        cookie_token = cookie_token.replace("Bearer ", "")
        agent_data = decode_access_token(cookie_token)
        if agent_data and agent_data.get("sub"):
            if request.headers.get("X-Wrennon-Client") == "agent-dashboard":
                return
            raise HTTPException(
                status_code=403,
                detail="Missing required client header for cookie-authenticated request.",
            )

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid upload token")


@router.post("/chat/init")
@limiter.limit("100/minute")
def init_session(request: Request):
    """Start a new session and get a signed token."""
    new_session_id = str(uuid.uuid4())
    token = create_session_token(new_session_id)
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
    # types are ever returned to the customer. If a new sender type is
    # added in the future, it will NOT leak to customers unless it is
    # explicitly added to this frozenset.
    #
    # sender is intentionally collapsed to "bot" for anything that
    # isn't the customer — this is where the "customer never knows it's
    # a human" rule actually gets enforced on the way out. The database
    # keeps the true sender ("ai" vs "agent") for the agent dashboard
    # and any future analytics; the customer-facing history never
    # exposes that distinction.
    CUSTOMER_VISIBLE_SENDERS = frozenset({"human", "ai", "agent"})
    # Strip [Translated: ...] tags from customer history so they don't see their own translations
    def clean_content(text):
        text = re.sub(r'\n\n\*\[Translated:.*?\]\*', '', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'\n\n\(Image Description:.*?\)', '', text, flags=re.DOTALL)
        text = re.sub(r'\[INTERNAL_IMAGE_DESC\].*?\[/INTERNAL_IMAGE_DESC\]', '', text, flags=re.DOTALL)
        return text.strip()

    return [
        {
            "sender": "user" if m.sender == "human" else "bot",
            "content": clean_content(m.content),
            "created_at": m.created_at.isoformat(),
        }
        for m in conversation.messages
        if m.sender in CUSTOMER_VISIBLE_SENDERS
    ]


UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "audio/webm", "audio/mp3", "audio/wav", "audio/mpeg", "audio/ogg", "audio/m4a",
    "application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
}
ALLOWED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".webm", ".mp3", ".wav", ".mpeg", ".m4a", ".ogg",
    ".pdf", ".doc", ".docx"
}
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB

@router.post("/chat/upload/{session_id}")
@limiter.limit("20/minute")
async def upload_file(
    request: Request,
    session_id: str,
    file: UploadFile = File(...),
    _=Depends(verify_upload_token)
):
    """Upload a file for the chat (audio, image)."""
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported file type")
        
    # Read file and check size
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 2MB.")
        
    file_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1].lower()
    
    # Extension must also be on the allowlist — content_type is a
    # client-supplied header and trivially spoofable on its own.
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported file extension")
        
    safe_filename = f"{file_id}{ext}"
    
    file_path = os.path.join(UPLOAD_DIR, safe_filename)
    with open(file_path, "wb") as buffer:
        buffer.write(contents)
        
    file_url = f"{request.base_url}uploads/{safe_filename}"
    return {"url": file_url, "filename": safe_filename, "type": file.content_type}


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
        import asyncio
        
        async def send_low_csat_alert():
            await manager.broadcast_to_agents({
                "type": "low_csat_alert",
                "session_id": session_id,
                "rating": rating,
                "comment": comment
            })
            
        background_tasks.add_task(send_low_csat_alert)

    return {"status": "success"}
