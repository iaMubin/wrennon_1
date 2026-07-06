"""
WebSocket endpoints. Two endpoints:
- /ws/customer/{session_id} — one customer's conversation
- /ws/agent — an agent dashboard, sees every conversation
"""

from __future__ import annotations

import datetime
import re
import asyncio
import redis.asyncio as redis

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Cookie
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.db.models import Conversation, Message, Agent
from app.db.session import SessionLocal
from app.graph.builder import build_graph
from app.graph.state import initial_state
from app.logger import logger
from app.realtime.connection_manager import manager
from app.config import settings
from app.services.llm import mask_pii
from app.services.cache import get_cache, set_cache

from app.api.agent import get_redis

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

    try:
        # One-off connection for initial setup
        with SessionLocal() as db:
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
            customer_text = data.get("message")
            if not customer_text:
                continue
                
            logger.info(f"Received message from customer {session_id}: {mask_pii(customer_text)}")

            # Rate Limiting (max 15 msgs / minute)
            try:
                r = get_redis()
                rate_key = f"rate_limit:{session_id}"
                count = await r.incr(rate_key)
                if count == 1:
                    await r.expire(rate_key, 60)
                if count > 15:
                    logger.warning(f"Rate limit exceeded for {session_id}")
                    await websocket.send_json({"reply": "You are sending messages too quickly. Please wait a minute."})
                    continue
            except Exception as e:
                logger.error(f"Rate limiting error: {e}")

            # Open a fresh DB connection only for the duration of this message
            with SessionLocal() as db:
                conversation = db.query(Conversation).filter_by(session_id=session_id).first()
                if not conversation:
                    continue
                    
                _save_message(db, conversation.id, sender="human", content=customer_text)

                # Broadcast ALL customer messages to the agent dashboard for real-time sync.
                await manager.broadcast_to_agents({
                    "type": "new_message",
                    "session_id": session_id,
                    "sender": "human",
                    "content": customer_text,
                    "is_resolved": conversation.resolved,
                })

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

                state["conversation_summary"] = conversation.summary
                state["active_topic"] = conversation.active_topic
                state["last_order_id"] = conversation.last_order_id
                state["turn_count"] = conversation.turn_count

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

                # Update rolling summary if conversation gets long (e.g., every 6 messages)
                if len(state["messages"]) > 0 and len(state["messages"]) % 6 == 0:
                    from app.services.llm import update_conversation_summary
                    new_summary = await asyncio.to_thread(update_conversation_summary, state["messages"][-6:], conversation.summary)
                    conversation.summary = new_summary
                    db.commit()
                    state["conversation_summary"] = new_summary

                # Run graph in a separate thread to avoid blocking the main async event loop
                # Semantic Cache logic: Only check cache for early generic questions
                reply_text = None
                updated_state = None
                if len(state["messages"]) == 1: # Only human's very first message
                    cached_reply = await get_cache(customer_text)
                    if cached_reply:
                        reply_text = cached_reply
                        logger.info(f"Semantic Cache HIT for '{customer_text}'")
                
                if not reply_text:
                    updated_state = await asyncio.to_thread(_graph.invoke, state)
                    reply_text = updated_state["messages"][-1].content
                    
                    # Store RAG/Generic questions in cache if no tools were used except knowledge base
                    if updated_state.get("planned_tools"):
                        tool_names = [t.get("name") for t in updated_state["planned_tools"]]
                        if tool_names == ["search_knowledge_base"]:
                            await set_cache(customer_text, reply_text, ttl=3600)
                
                # Persist state updates if graph ran
                if updated_state:
                    conversation.active_topic = updated_state.get("active_topic")
                    conversation.last_order_id = updated_state.get("last_order_id")
                    conversation.turn_count = updated_state.get("turn_count", conversation.turn_count) + 1

                _save_message(db, conversation.id, sender="ai", content=reply_text)

                # Broadcast AI messages to agent dashboard as well
                await manager.broadcast_to_agents({
                    "type": "new_message",
                    "session_id": session_id,
                    "sender": "ai",
                    "content": reply_text,
                    "is_resolved": conversation.resolved,
                })

                if updated_state and updated_state.get("handoff_ticket_id"):
                    conversation.handoff_active = True
                    conversation.handoff_ticket_id = updated_state["handoff_ticket_id"]
                    
                    if conversation.resolved:
                        conversation.resolved = False
                        conversation.resolved_at = None
                        conversation.reopen_count += 1
                        
                    db.commit()

                    # Save the AI-generated summary as a system message
                    _save_message(db, conversation.id, sender="system", content=f"[System] AI generated summary for agent handoff: {updated_state.get('conversation_summary', '')}")
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
                    
                    from app.db.models import AuditLog
                    audit = AuditLog(
                        actor_username="AI Agent",
                        action="resolve_conversation",
                        target_username=session_id
                    )
                    db.add(audit)
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
    except Exception as e:
        logger.error(f"Error in customer_websocket: {e}", exc_info=True)
        manager.disconnect_customer(session_id)


@router.websocket("/ws/agent")
async def agent_websocket(websocket: WebSocket, access_token: str | None = Cookie(None)):
    if not access_token:
        logger.warning("Agent connection rejected: missing cookie")
        await websocket.close(code=4401)
        return
        
    token = access_token.replace("Bearer ", "")
    token_data = decode_access_token(token)
    if token_data is None or not token_data.get("sub"):
        logger.warning("Agent connection rejected: unauthorized")
        await websocket.close(code=4401)
        return

    username = token_data["sub"]

    try:
        # Validate agent once
        with SessionLocal() as db:
            agent = db.query(Agent).filter_by(username=username).first()
            if not agent:
                logger.warning("Agent connection rejected: agent not found")
                await websocket.close(code=4401)
                return
                
            expected_frag = agent.password_hash[-10:] if agent.password_hash else ""
            if token_data.get("pwd_frag") != expected_frag:
                logger.warning("Agent connection rejected: token revoked")
                await websocket.close(code=4401)
                return

        logger.info(f"Agent connected: {username}")
        await manager.connect_agent(websocket)
        
        while True:
            data = await websocket.receive_json()
            session_id = data.get("session_id")
            reply_text = data.get("message")
            
            if not session_id or not reply_text:
                continue
                
            logger.info(f"Agent {username} replied to conversation {session_id}")

            with SessionLocal() as db:
                conversation = db.query(Conversation).filter_by(session_id=session_id).first()
                if conversation is None:
                    continue

                _save_message(db, conversation.id, sender="agent", content=reply_text)

                # If agent manually intervenes, lock out the AI.
                if not conversation.handoff_active:
                    conversation.handoff_active = True
                    
                conversation.handled_by = username
                db.commit()
                
                if conversation.handoff_active:
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
    except Exception as e:
        logger.error(f"Error in agent_websocket: {e}", exc_info=True)
        manager.disconnect_agent(websocket)
