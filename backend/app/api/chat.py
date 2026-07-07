"""
Customer-facing REST endpoint. Only one job left here: when the
customer widget first loads, it needs the conversation history that
already happened (if this session_id has been seen before) before the
WebSocket connection takes over for everything that happens next.
"""

from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Depends, Request, Header, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
import shutil
import os

from app.db.models import Conversation
from app.db.session import get_db
from app.limiter import limiter
from app.auth.security import create_session_token, decode_session_token

router = APIRouter()

REOPEN_WINDOW_HOURS = 72


def verify_session_token(session_id: str, authorization: str | None = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid token")
    
    token = authorization.split(" ")[1]
    decoded_session = decode_session_token(token)
    
    if not decoded_session or decoded_session != session_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token for this session")


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
        elapsed = datetime.datetime.utcnow() - conversation.resolved_at
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
    # sender is intentionally collapsed to "bot" for anything that
    # isn't the customer — this is where the "customer never knows it's
    # a human" rule actually gets enforced on the way out. The database
    # keeps the true sender ("ai" vs "agent") for the agent dashboard
    # and any future analytics; the customer-facing history never
    # exposes that distinction.
    return [
        {
            "sender": "user" if m.sender == "human" else "bot",
            "content": m.content,
        }
        for m in conversation.messages
        if m.sender != "system"  # Hide internal summaries from customer
    ]


UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/chat/upload")
@limiter.limit("20/minute")
async def upload_file(
    request: Request,
    file: UploadFile = File(...)
):
    """Upload a file for the chat (audio, image, document)."""
    file_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1]
    safe_filename = f"{file_id}{ext}"
    
    file_path = os.path.join(UPLOAD_DIR, safe_filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    file_url = f"{request.base_url}uploads/{safe_filename}"
    return {"url": file_url, "filename": safe_filename, "type": file.content_type}
