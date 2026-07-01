"""
WebSocket endpoints. Two endpoints:
- /ws/customer/{session_id} — one customer's conversation
- /ws/agent — an agent dashboard, sees every conversation
"""

from __future__ import annotations

import datetime
import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.db.models import Conversation, Message
from app.db.session import SessionLocal
from app.graph.builder import build_graph
from app.graph.state import initial_state
from app.logger import logger
from app.realtime.connection_manager import manager

router = APIRouter()
_graph = build_graph()


def _get_or_create_conversation(db: Session, session_id: str, customer_email: str | None) -> Conversation:
    """Look up an existing conversation or create a new one.
    If the conversation was resolved within 72 hours, reactivate it."""
    conversation = db.query(Conversation).filter_by(session_id=session_id).first()
    if conversation is None:
        conversation = Conversation(session_id=session_id, customer_email=customer_email)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation

    # Reactivate a resolved conversation (within 72-hour window)
    if conversation.resolved:
        conversation.resolved = False
        conversation.resolved_at = None
        conversation.reopen_count += 1
        db.commit()
        logger.info(f"Conversation {session_id} reopened (count: {conversation.reopen_count})")

    return conversation


def _save_message(db: Session, conversation_id: str, sender: str, content: str) -> Message:
    message = Message(conversation_id=conversation_id, sender=sender, content=content)
    db.add(message)
    # Update the conversation's updated_at so sorting works
    conversation = db.query(Conversation).filter_by(id=conversation_id).first()
    if conversation:
        conversation.updated_at = datetime.datetime.utcnow()
    db.commit()
    return message


@router.websocket("/ws/customer/{session_id}")
async def customer_websocket(websocket: WebSocket, session_id: str):
    logger.info(f"Customer connected: {session_id}")
    await manager.connect_customer(session_id, websocket)
    db = SessionLocal()

    try:
        conversation = _get_or_create_conversation(db, session_id, customer_email=None)

        # Notify agents if this is a reopened conversation
        if conversation.reopen_count > 0 and not conversation.handoff_active:
            await manager.broadcast_to_agents({
                "type": "reopen",
                "session_id": session_id,
                "reopen_count": conversation.reopen_count,
                "is_resolved": conversation.resolved,
            })

        while True:
            data = await websocket.receive_json()
            customer_text = data["message"]
            logger.info(f"Received message from customer {session_id}: {customer_text}")

            _save_message(db, conversation.id, sender="human", content=customer_text)

            # Broadcast ALL customer messages to the agent dashboard for real-time sync.
            await manager.broadcast_to_agents({
                "type": "new_message",
                "session_id": session_id,
                "sender": "human",
                "content": customer_text,
                "is_resolved": conversation.resolved,
            })

            # Refresh conversation state from DB (in case agent resolved while we were waiting)
            db.refresh(conversation)

            # If the customer sends a message after resolution, it automatically reopens
            if conversation.resolved:
                conversation.resolved = False
                conversation.resolved_at = None
                conversation.reopen_count += 1
                db.commit()
                # Notify agents
                await manager.broadcast_to_agents({
                    "type": "reopen",
                    "session_id": session_id,
                    "reopen_count": conversation.reopen_count,
                    "is_resolved": conversation.resolved,
                })

            if conversation.handoff_active and not conversation.resolved:
                # A human agent already owns this conversation — the AI stays silent.
                continue

            state = initial_state(customer_email=conversation.customer_email)

            # Pass existing ticket_id so handoff_node can reopen it instead of creating new
            if conversation.handoff_ticket_id:
                state["existing_ticket_id"] = conversation.handoff_ticket_id

            # Load conversation history so the AI has full context
            prev_messages = (
                db.query(Message)
                .filter_by(conversation_id=conversation.id)
                .order_by(Message.created_at.asc())
                .all()
            )
            for msg in prev_messages:
                if msg.sender == "human":
                    state["messages"].append(HumanMessage(content=msg.content))
                elif msg.sender in ("ai", "agent"):
                    state["messages"].append(AIMessage(content=msg.content))
                # Skip "system" messages — they're internal summaries

            # Add the current message
            state["messages"].append(HumanMessage(content=customer_text))

            # Extract order ID from the current message before invoking graph
            order_match = re.search(r"#?(\d{4,})", customer_text)
            if order_match:
                state["order_id"] = order_match.group(1)

            updated_state = _graph.invoke(state)
            reply_text = updated_state["messages"][-1].content

            _save_message(db, conversation.id, sender="ai", content=reply_text)

            # Broadcast AI messages to agent dashboard as well
            await manager.broadcast_to_agents({
                "type": "new_message",
                "session_id": session_id,
                "sender": "ai",
                "content": reply_text,
                "is_resolved": conversation.resolved,
            })

            if updated_state.get("handoff_ticket_id"):
                conversation.handoff_active = True
                conversation.handoff_ticket_id = updated_state["handoff_ticket_id"]
                
                if conversation.resolved:
                    conversation.resolved = False
                    conversation.resolved_at = None
                    conversation.reopen_count += 1
                    
                db.commit()

                # Save the AI-generated summary as a system message
                summary = updated_state.get("handoff_summary", "")
                if summary:
                    _save_message(db, conversation.id, sender="system", content=f"📋 Summary: {summary}")

                await manager.broadcast_to_agents({
                    "type": "handoff",
                    "session_id": session_id,
                    "ticket_id": updated_state["handoff_ticket_id"],
                    "summary": summary,
                    "is_resolved": conversation.resolved,
                })
            elif updated_state.get("conversation_mode") == "resolved":
                conversation.resolved = True
                conversation.resolved_at = datetime.datetime.utcnow()
                conversation.handoff_active = False
                db.commit()
                
                await manager.broadcast_to_agents({
                    "type": "reopen",  # Re-use reopen event to force UI refresh
                    "session_id": session_id,
                    "is_resolved": conversation.resolved,
                })

            await websocket.send_json({"reply": reply_text})

    except WebSocketDisconnect:
        logger.info(f"Customer disconnected: {session_id}")
        manager.disconnect_customer(session_id)
    finally:
        db.close()


@router.websocket("/ws/agent")
async def agent_websocket(websocket: WebSocket, token: str):
    username = decode_access_token(token)
    if username is None:
        logger.warning("Agent connection rejected: unauthorized")
        await websocket.close(code=4401)
        return

    logger.info(f"Agent connected: {username}")
    await manager.connect_agent(websocket)

    try:
        db = SessionLocal()
        while True:
            data = await websocket.receive_json()
            session_id = data["session_id"]
            reply_text = data["message"]
            logger.info(f"Agent {username} replied to conversation {session_id}")

            conversation = db.query(Conversation).filter_by(session_id=session_id).first()
            if conversation is None:
                continue

            _save_message(db, conversation.id, sender="agent", content=reply_text)

            # If agent manually intervenes, lock out the AI.
            if not conversation.handoff_active:
                conversation.handoff_active = True
                db.commit()
                await manager.broadcast_to_agents({
                    "type": "handoff",
                    "session_id": session_id,
                    "ticket_id": "manual_intervention",
                    "is_resolved": conversation.resolved,
                })

            # Customer receives same shape as AI reply — seamless handoff.
            await manager.send_to_customer(session_id, {"reply": reply_text})

    except WebSocketDisconnect:
        manager.disconnect_agent(websocket)
    finally:
        db.close()
