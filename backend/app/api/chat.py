"""
Customer-facing REST endpoint. Only one job left here: when the
customer widget first loads, it needs the conversation history that
already happened (if this session_id has been seen before) before the
WebSocket connection takes over for everything that happens next.
"""

import datetime
import uuid

from fastapi import APIRouter, Depends, Request, Header, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
import shutil
import os

from app.db.models import Conversation
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

def verify_upload_token(session_id: str, authorization: str | None = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid token")
    
    token = authorization.split(" ")[1]
    
    decoded_session = decode_session_token(token)
    if decoded_session and decoded_session == session_id:
        return
        
    agent_data = decode_access_token(token)
    if agent_data and agent_data.get("sub"):
        return
        
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
    return [
        {
            "sender": "user" if m.sender == "human" else "bot",
            "content": m.content,
        }
        for m in conversation.messages
        if m.sender in CUSTOMER_VISIBLE_SENDERS
    ]


UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml",
    "audio/webm", "audio/mp3", "audio/wav", "audio/mpeg", "audio/ogg", "audio/m4a"
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
    if file.content_type not in ALLOWED_CONTENT_TYPES and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Unsupported file type")
        
    # Read file and check size
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 2MB.")
        
    file_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1].lower()
    
    # Extra layer of defense on extension
    if ext in [".html", ".js", ".svg", ".php", ".sh", ".exe", ".bat"]:
        raise HTTPException(status_code=415, detail="Unsupported file extension")
        
    safe_filename = f"{file_id}{ext}"
    
    file_path = os.path.join(UPLOAD_DIR, safe_filename)
    with open(file_path, "wb") as buffer:
        buffer.write(contents)
        
    file_url = f"{request.base_url}uploads/{safe_filename}"
    return {"url": file_url, "filename": safe_filename, "type": file.content_type}
