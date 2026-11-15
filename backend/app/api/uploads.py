"""Serving of uploaded files. Every request needs a valid signed link (or an
authenticated agent); a bare ``/uploads/<id>`` URL no longer works."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.db.models import Agent
from app.db.session import get_db
from app.services import uploads

router = APIRouter()


def _agent_authenticated(request: Request, db: Session) -> bool:
    token = request.headers.get("Authorization", "")
    token = token[7:] if token.startswith("Bearer ") else request.cookies.get("access_token", "").replace("Bearer ", "")
    data = decode_access_token(token) if token else None
    if not data or not data.get("sub"):
        return False
    agent = db.query(Agent).filter_by(username=data["sub"]).first()
    return bool(agent and agent.token_version == data.get("tv"))


def _serve(request: Request, db: Session, session_id: str | None, filename: str):
    path = uploads.resolve_path(session_id, filename)
    key = f"{session_id}/{filename}" if session_id else filename
    q = request.query_params
    if not uploads.verify_signature(key, q.get("exp"), q.get("sig")) and not _agent_authenticated(request, db):
        raise HTTPException(status_code=403, detail="Invalid or expired link")
    if path is None or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    ext = os.path.splitext(filename)[1].lower()
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cache-Control": "private, max-age=300",
        "Cross-Origin-Resource-Policy": "cross-origin",
    }
    if ext not in uploads.INLINE_EXTENSIONS:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return FileResponse(path, headers=headers)


@router.get("/uploads/{session_id}/{filename}")
def get_session_upload(session_id: str, filename: str, request: Request, db: Session = Depends(get_db)):
    return _serve(request, db, session_id, filename)


@router.get("/uploads/{filename}")
def get_legacy_upload(filename: str, request: Request, db: Session = Depends(get_db)):
    """Pre-per-session layout. Still signature-protected."""
    return _serve(request, db, None, filename)
