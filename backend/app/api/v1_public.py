from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.session import get_db
from app.db.models import Conversation, Message, ApiKey
from app.auth.dependencies import get_api_key
from app.limiter import limiter
import datetime

router = APIRouter()

class PublicMessageCreate(BaseModel):
    content: str
    is_internal: bool = False

@router.get("/conversations")
@limiter.limit("60/minute")
def list_conversations(
    request: Request,
    status: Optional[str] = None,
    assigned_agent: Optional[str] = None,
    api_key: ApiKey = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    query = db.query(Conversation)
    
    if status:
        query = query.filter(Conversation.resolved == (status == "resolved"))
    if assigned_agent:
        query = query.filter(Conversation.assigned_agent_id == assigned_agent)
        
    conversations = query.order_by(Conversation.created_at.desc()).limit(100).all()
    
    return {
        "data": [
            {
                "id": c.id,
                "short_id": c.short_id,
                "session_id": c.session_id,
                "resolved": c.resolved,
                "assigned_agent": c.assigned_agent,
                "created_at": c.created_at,
                "last_message_at": c.updated_at,
                "priority": c.priority,
            } for c in conversations
        ]
    }

@router.get("/conversations/{short_id}")
@limiter.limit("60/minute")
def get_conversation_details(
    request: Request,
    short_id: str,
    api_key: ApiKey = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    conv = db.query(Conversation).filter_by(short_id=short_id).first()
    if not conv:
        conv = db.query(Conversation).filter_by(id=short_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    messages = db.query(Message).filter_by(conversation_id=conv.id).order_by(Message.created_at.asc()).all()
    
    return {
        "id": conv.id,
        "short_id": conv.short_id,
        "session_id": conv.session_id,
        "resolved": conv.resolved,
        "assigned_agent": conv.assigned_agent,
        "created_at": conv.created_at,
        "last_message_at": conv.updated_at,
        "priority": conv.priority,
        "intent_category": conv.intent_category,
        "sentiment": conv.sentiment,
        "csat_score": conv.csat_response.rating if conv.csat_response else None,
        "messages": [
            {
                "id": m.id,
                "type": m.sender,
                "content": m.content,
                "created_at": m.created_at,
                "is_internal": m.sender == "system",
                "sender_name": m.author_username
            } for m in messages
        ]
    }

@router.post("/conversations/{short_id}/messages")
@limiter.limit("60/minute")
def add_message(
    request: Request,
    short_id: str,
    payload: PublicMessageCreate,
    api_key: ApiKey = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    conv = db.query(Conversation).filter_by(short_id=short_id).first()
    if not conv:
        conv = db.query(Conversation).filter_by(id=short_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    if conv.resolved:
        raise HTTPException(status_code=400, detail="Cannot add message to resolved conversation")
        
    new_msg = Message(
        conversation_id=conv.id,
        sender="agent" if not payload.is_internal else "system",
        content=payload.content,
        author_username="API: " + api_key.name
    )
    db.add(new_msg)
    
    conv.updated_at = datetime.datetime.now(datetime.timezone.utc)
    # Important: adding a message does NOT automatically broadcast to connected websocket clients in this simple v1
    # You'd need to publish a redis pub/sub message or similar to sync realtime clients.
    
    db.commit()
    db.refresh(new_msg)
    
    return {
        "id": new_msg.id,
        "type": new_msg.sender,
        "content": new_msg.content,
        "created_at": new_msg.created_at,
        "is_internal": payload.is_internal,
        "sender_name": new_msg.author_username
    }

@router.post("/conversations/{short_id}/resolve")
@limiter.limit("60/minute")
def resolve_conversation(
    request: Request,
    short_id: str,
    api_key: ApiKey = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    conv = db.query(Conversation).filter_by(short_id=short_id).first()
    if not conv:
        conv = db.query(Conversation).filter_by(id=short_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    if conv.resolved:
        return {"status": "success", "message": "Already resolved"}
        
    conv.resolved = True
    conv.resolved_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    
    return {"status": "success", "message": "Conversation resolved"}
