"""
WebSocket endpoints. This replaces the old POST /api/chat as the
primary way messages flow — a persistent connection instead of one
request per message, which is what makes the agent's reply reach the
customer's widget without the customer refreshing anything.

Two endpoints:
- /ws/customer/{session_id} — one customer's conversation
- /ws/agent — an agent dashboard, sees every conversation

The REST endpoint in api/chat.py still exists, but now only for
fetching conversation history on initial page load (a WebSocket isn't
a great fit for "give me everything that already happened" — that's
a one-time fetch, which REST already does well).
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage
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
    conversation = db.query(Conversation).filter_by(session_id=session_id).first()
    if conversation is None:
        conversation = Conversation(session_id=session_id, customer_email=customer_email)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
    return conversation


import datetime

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
            })

            if conversation.handoff_active and not conversation.resolved:
                # A human agent already owns this conversation — the AI
                # stays silent. The agent's reply (sent from the agent
                # websocket below) is what reaches the customer here,
                # not anything the graph would generate. This is the
                # core of the "customer can't tell it's a human"
                # design: the customer's send/receive flow never
                # changes shape, only who is actually typing changes.
                continue

            state = initial_state(customer_email=conversation.customer_email)

            # Load conversation history so the AI has full context
            prev_messages = (
                db.query(Message)
                .filter_by(conversation_id=conversation.id)
                .order_by(Message.id.asc())
                .all()
            )
            for msg in prev_messages:
                if msg.sender == "human":
                    state["messages"].append(HumanMessage(content=msg.content))
                else:
                    from langchain_core.messages import AIMessage
                    state["messages"].append(AIMessage(content=msg.content))

            # Add the current message
            state["messages"].append(HumanMessage(content=customer_text))

            # Extract order ID from the current message before invoking graph
            import re
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
            })

            if updated_state.get("handoff_ticket_id"):
                conversation.handoff_active = True
                conversation.handoff_ticket_id = updated_state["handoff_ticket_id"]
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
                })

            await websocket.send_json({"reply": reply_text})

    except WebSocketDisconnect:
        logger.info(f"Customer disconnected: {session_id}")
        manager.disconnect_customer(session_id)
    finally:
        db.close()


@router.websocket("/ws/agent")
async def agent_websocket(websocket: WebSocket, token: str):
    # Auth check happens BEFORE accepting the connection. A WebSocket
    # can't use the normal Depends(get_current_agent) pattern used by
    # REST routes, so the token is verified manually here — same
    # decode_access_token function, just called directly instead of
    # through FastAPI's dependency injection.
    username = decode_access_token(token)
    if username is None:
        logger.warning("Agent connection rejected: unauthorized")
        await websocket.close(code=4401)  # 4401: custom close code for "unauthorized"
        return

    logger.info(f"Agent connected: {username}")
    await manager.connect_agent(websocket)

    try:
        db = SessionLocal()
        while True:
            data = await websocket.receive_json()
            # Agent sent a reply to a specific conversation.
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
                })

            # This is the key line for the "seamless" design: the
            # customer receives this exactly the same shape
            # ({"reply": ...}) as an AI-generated reply. Nothing in the
            # customer widget's code path needs to know or care that a
            # human typed this instead of the graph.
            await manager.send_to_customer(session_id, {"reply": reply_text})

    except WebSocketDisconnect:
        manager.disconnect_agent(websocket)
    finally:
        db.close()
