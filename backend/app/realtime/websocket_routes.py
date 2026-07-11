"""
WebSocket endpoints. Two endpoints:
- /ws/customer/{session_id} — one customer's conversation
- /ws/agent — an agent dashboard, sees every conversation
"""

from __future__ import annotations

import datetime
import re
import asyncio
import time
import redis.asyncio as redis

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Cookie
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token, decode_session_token
from app.db.models import Conversation, Message, Agent, AuditLog
from app.db.session import SessionLocal
from app.graph.builder import build_graph
from app.graph.state import initial_state
from app.logger import logger
from app.realtime.connection_manager import manager
from app.config import settings
from app.services.llm import mask_pii, update_conversation_summary, transcribe_audio_if_present, auto_translate_if_needed
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


# --- SYNC WRAPPERS FOR ASYNC EVENT LOOP ---

def _sync_setup_conversation(session_id: str) -> dict:
    with SessionLocal() as db:
        conversation = _get_or_create_conversation(db, session_id, customer_email=None)
        return {
            "reopen_count": conversation.reopen_count,
            "handoff_active": conversation.handoff_active,
            "resolved": conversation.resolved
        }


def _sync_phase1(session_id: str, customer_text: str) -> dict | None:
    with SessionLocal() as db:
        conversation = db.query(Conversation).filter_by(session_id=session_id).first()
        if not conversation:
            return None
        msg = _save_message(db, conversation.id, sender="human", content=customer_text)

        reopened = False
        if conversation.resolved:
            conversation.resolved = False
            conversation.resolved_at = None
            conversation.reopen_count += 1
            conversation.turn_count = 0
            reopened = True
            
        db.commit()

        messages_data = []
        if not (conversation.handoff_active and not conversation.resolved):
            prev_messages = (
                db.query(Message)
                .filter_by(conversation_id=conversation.id)
                .order_by(Message.created_at.asc())
                .all()
            )
            messages_data = [
                {"sender": m.sender, "content": m.content}
                for m in prev_messages
                if m.sender != "system"
            ]

        return {
            "handoff_active": conversation.handoff_active,
            "reopened": reopened,
            "resolved": conversation.resolved,
            "reopen_count": conversation.reopen_count,
            "customer_email": conversation.customer_email,
            "handoff_ticket_id": conversation.handoff_ticket_id,
            "summary": conversation.summary,
            "active_topic": conversation.active_topic,
            "last_order_id": conversation.last_order_id,
            "turn_count": conversation.turn_count,
            "messages": messages_data,
            "message_id": msg.id
        }


def _sync_update_summary(session_id: str, new_summary: str):
    with SessionLocal() as db:
        conv = db.query(Conversation).filter_by(session_id=session_id).first()
        if conv:
            conv.summary = new_summary
            db.commit()


def _sync_phase3(session_id: str, reply_text: str, updated_state: dict | None, my_generation: int, turn_generation_ref: dict) -> dict | None:
    with SessionLocal() as db:
        conversation = db.query(Conversation).filter_by(session_id=session_id).first()
        if not conversation:
            return None

        # Race-proof guard: don't write anything if a follow-up message has
        # already superseded this turn (see turn_generation's declaration
        # in customer_websocket for the full reasoning). This check has to
        # live HERE — inside the worker thread, before any write — because
        # asyncio-level task cancellation of the calling coroutine cannot
        # stop this synchronous function once it's already running in a
        # thread pool worker (Python threads aren't preemptible). Checking
        # only at the asyncio layer would leave a narrow window where a
        # stale reply gets permanently committed anyway.
        if turn_generation_ref["value"] != my_generation:
            return None

        if updated_state:
            conversation.active_topic = updated_state.get("active_topic")
            conversation.last_order_id = updated_state.get("last_order_id")
            conversation.turn_count = updated_state.get("turn_count", conversation.turn_count) + 1
            conversation.sentiment = updated_state.get("sentiment")
            conversation.language = updated_state.get("language")

        msg = _save_message(db, conversation.id, sender="ai", content=reply_text)
        
        events = []

        if updated_state and updated_state.get("handoff_ticket_id"):
            conversation.handoff_active = True
            conversation.handoff_ticket_id = updated_state["handoff_ticket_id"]
            conversation.handled_by = None
            
            if conversation.resolved:
                conversation.resolved = False
                conversation.resolved_at = None
                conversation.reopen_count += 1
                
            db.commit()


            summary = updated_state.get("handoff_summary", "")
            if summary:
                _save_message(db, conversation.id, sender="system", content=f"📋 {summary}")

            events.append({
                "type": "handoff",
                "ticket_id": conversation.handoff_ticket_id,
                "summary": summary,
                "is_resolved": conversation.resolved
            })
        elif updated_state and updated_state.get("conversation_mode") == "resolved":
            conversation.resolved = True
            conversation.resolved_at = datetime.datetime.utcnow()
            conversation.handoff_active = False
            conversation.handled_by = None
            
            audit = AuditLog(
                actor_username="AI Agent",
                action="resolve_conversation",
                target_username=session_id
            )
            db.add(audit)
            db.commit()
            
            events.append({
                "type": "reopen",  # Re-use reopen event to force UI refresh
                "is_resolved": conversation.resolved
            })

        db.commit()
        return {
            "resolved": conversation.resolved,
            "events": events,
            "message_id": msg.id
        }


def _sync_validate_agent(username: str, pwd_frag: str | None) -> dict | None:
    with SessionLocal() as db:
        agent = db.query(Agent).filter_by(username=username).first()
        if not agent:
            return None
        expected_frag = agent.password_hash[-10:] if agent.password_hash else ""
        if pwd_frag != expected_frag:
            return None
        return {"full_name": agent.full_name}


def _sync_agent_reply(session_id: str, username: str, reply_text: str, is_internal: bool = False) -> dict | None:
    with SessionLocal() as db:
        conversation = db.query(Conversation).filter_by(session_id=session_id).first()
        if conversation is None:
            return None

        msg_sender = "agent_internal" if is_internal else "agent"
        msg = _save_message(db, conversation.id, sender=msg_sender, content=reply_text)

        if not is_internal and not conversation.handoff_active:
            conversation.handoff_active = True
            
        if not is_internal:
            conversation.handled_by = username
            
        db.commit()
        
        return {
            "handoff_active": conversation.handoff_active,
            "resolved": conversation.resolved,
            "message_id": msg.id
        }

# --- END SYNC WRAPPERS ---


TYPING_STOPPED_GRACE_SECONDS = 1.5
# Once the customer's typing indicator says they've stopped (or a message
# arrives with no typing signal at all — e.g. paste-and-send), wait this
# long before actually processing. If nothing else happens in that window,
# the AI turn fires. Mirrors the "1 second after typing stops" behavior
# requested — this is the ONLY fixed wait once typing has genuinely ended.

TYPING_ACTIVE_SAFETY_CAP_SECONDS = 20.0
# While the typing indicator says "still typing", we don't apply any fixed
# debounce at all — we simply wait for the next signal (more typing,
# stopped_typing, or an actual message). This cap exists purely as a
# defensive fallback: if a customer's "stopped_typing" is ever lost (flaky
# connection, tab killed mid-type, older cached widget.js) we don't want
# the AI to wait forever. It should essentially never be hit in normal use,
# since widget.js reliably fires stopped_typing 1.5s after the last
# keystroke as long as the tab is alive.


@router.websocket("/ws/customer/{session_id}")
async def customer_websocket(websocket: WebSocket, session_id: str, token: str | None = None):
    logger.info(f"Customer connected: {session_id}")

    # Accept BEFORE validating. Starlette/ASGI only delivers a real
    # WebSocket close FRAME (carrying our custom code) to the browser if
    # the handshake has already been accepted. Closing before accept()
    # instead makes uvicorn reject the opening HTTP upgrade request
    # outright — logged as "403 Forbidden" / "connection rejected" — and
    # the browser's onclose event never actually receives our code; it
    # just sees an abnormal closure (code 1006). That silently broke the
    # frontend's ability to tell "auth failed, don't retry" apart from any
    # other disconnect, no matter what the frontend checked for.
    await websocket.accept()

    if not token:
        logger.warning(f"Customer {session_id} rejected: missing token")
        await websocket.close(code=4401)
        return

    decoded = decode_session_token(token)
    if not decoded or decoded != session_id:
        logger.warning(f"Customer {session_id} rejected: invalid token")
        await websocket.close(code=4401)
        return

    await manager.connect_customer(session_id, websocket)

    # --- Debounce state for this connection ---
    # These are local to this function call, i.e. scoped per-connection —
    # no shared/global dict needed, since one customer_websocket() coroutine
    # already exists per connection.
    pending_event = asyncio.Event()
    latest_phase1_data: dict | None = None
    is_typing = False

    # --- Mid-turn interrupt/merge state ---
    # current_turn_task: the AI turn currently in flight, if any. Checked
    # by the receive loop to decide whether an incoming message should
    # interrupt-and-merge (see below) instead of going through the normal
    # pre-turn debounce.
    current_turn_task: asyncio.Task | None = None
    # turn_generation: a plain dict (not a bare int) so it can be read
    # consistently from both this coroutine and the worker thread
    # _sync_phase3 runs in — a simple counter comparison like this is safe
    # under the GIL without needing an explicit lock. This is the ONLY
    # reliable way to guarantee a superseded turn's reply never gets
    # written, even in the narrow race where cancellation lands exactly
    # while _sync_phase3's DB write is already running in a thread pool
    # worker (asyncio can't preempt an already-started synchronous call).
    turn_generation = {"value": 0}
    # mid_turn_typing_event: deliberately SEPARATE from pending_event.
    # pending_event is consumed by _debounce_worker's own pre-turn wait
    # loop; if the in-turn "hold before committing a reply" logic below
    # shared that same event, the two waiters would race for the same
    # wakeup and could steal ticks from each other. Both get set together
    # on every typing/stopped_typing signal, but each has its own
    # independent waiter.
    mid_turn_typing_event = asyncio.Event()

    async def _run_ai_turn(phase1_data: dict, my_generation: int):
        """Everything that used to run immediately after phase1 for a single
        message now runs once per debounce-settled batch, using the most
        up-to-date phase1 snapshot — which already reflects every message
        the customer sent during the quiet window, since each one was saved
        to the DB (and broadcast to agents) as soon as it arrived."""
        msg_start_time = time.time()
        customer_text = phase1_data["messages"][-1]["content"] if phase1_data["messages"] else ""

        state = initial_state(customer_email=phase1_data["customer_email"])

        if phase1_data["handoff_ticket_id"]:
            state["existing_ticket_id"] = phase1_data["handoff_ticket_id"]

        state["conversation_summary"] = phase1_data["summary"]
        state["active_topic"] = phase1_data["active_topic"]
        state["last_order_id"] = phase1_data["last_order_id"]
        state["turn_count"] = phase1_data["turn_count"]

        for msg in phase1_data["messages"]:
            if msg["sender"] == "human":
                state["messages"].append(HumanMessage(content=msg["content"]))
            elif msg["sender"] in ("ai", "agent"):
                state["messages"].append(AIMessage(content=msg["content"]))

        # Update rolling summary if conversation gets long (e.g., every 6 messages)
        if len(state["messages"]) > 0 and len(state["messages"]) % 6 == 0:
            new_summary = await update_conversation_summary(state["messages"][-6:], phase1_data["summary"])
            await asyncio.to_thread(_sync_update_summary, session_id, new_summary)
            state["conversation_summary"] = new_summary

        # Semantic Cache logic: Only check cache for early generic questions
        reply_text = None
        updated_state = None
        if len(state["messages"]) == 1:
            cached_reply = await get_cache(customer_text)
            if cached_reply:
                reply_text = cached_reply
                logger.info(f"Semantic Cache HIT for '{customer_text}'")

        # Phase 2: AI Processing (LangGraph)
        phase2_start = time.time()
        if not reply_text:
            updated_state = await _graph.ainvoke(state)
            reply_text = updated_state["messages"][-1].content

            # Store RAG/Generic questions in cache
            if updated_state.get("tool_call_history"):
                tool_names = [entry.split(":", 1)[0] for entry in updated_state["tool_call_history"]]
                if tool_names == ["search_knowledge_base"]:
                    await set_cache(customer_text, reply_text, ttl=3600)

        phase2_duration = time.time() - phase2_start
        logger.info(f"[TIMING] Phase 2 (AI Graph Execution) took {phase2_duration:.3f}s")

        # Give a currently-typing customer a brief moment before committing
        # this reply, in case they're about to send a follow-up that
        # should be merged in instead of receiving two separate answers.
        # If they actually send something, the receive loop cancels this
        # whole turn (see below) and this wait raises CancelledError,
        # which propagates normally — no special handling needed here. If
        # they stop typing without sending anything, this releases the
        # reply exactly as if nothing happened. If nobody was typing when
        # the reply became ready (the common case), this adds zero delay.
        if is_typing:
            hold_deadline = time.time() + TYPING_STOPPED_GRACE_SECONDS
            while is_typing:
                remaining = hold_deadline - time.time()
                if remaining <= 0:
                    break
                try:
                    await asyncio.wait_for(mid_turn_typing_event.wait(), timeout=remaining)
                    mid_turn_typing_event.clear()
                except asyncio.TimeoutError:
                    break

        # Defense-in-depth: cancellation should normally have already
        # stopped a superseded turn before it gets here. This only matters
        # if a follow-up message landed in the narrow window between the
        # hold-wait above resolving and this line. The REAL guarantee
        # against a stale reply being written is the matching check inside
        # _sync_phase3 itself (see its comment) — this one just avoids
        # doing the belt-and-suspenders connection check and the DB call
        # at all when we already know we've been superseded.
        if my_generation != turn_generation["value"]:
            logger.info(f"Dropping AI turn for {session_id}: superseded by a merged follow-up.")
            return

        # Belt-and-suspenders check: connect_customer() cancels a superseded
        # connection's debounce task, which should stop this turn before it
        # gets here — but that cancellation only takes effect at the next
        # await point. If a new connection for this session_id took over
        # while this turn's (slow) LLM calls were in flight, don't write a
        # second/duplicate reply for a conversation another connection is
        # now actively handling.
        if manager.get_customer_websocket(session_id) is not websocket:
            logger.warning(f"Dropping AI turn for {session_id}: superseded by a newer connection.")
            return

        # Phase 3: Post-processing & DB Save
        phase3_start = time.time()
        phase3_data = await asyncio.to_thread(
            _sync_phase3, session_id, reply_text, updated_state, my_generation, turn_generation
        )
        if not phase3_data:
            return

        # Broadcast AI messages to agent dashboard
        _t0 = time.time()
        await manager.broadcast_to_agents({
            "type": "new_message",
            "session_id": session_id,
            "sender": "ai",
            "content": reply_text,
            "is_resolved": phase3_data["resolved"],
            "message_id": phase3_data["message_id"]
        })
        logger.info(f"[TIMING] broadcast_to_agents (ai msg) dispatched in {time.time() - _t0:.3f}s")

        # Handle handoff/reopen events returned from sync_phase3
        for event in phase3_data["events"]:
            event["session_id"] = session_id
            _t0 = time.time()
            await manager.broadcast_to_agents(event)
            logger.info(f"[TIMING] broadcast_to_agents ({event['type']}) dispatched in {time.time() - _t0:.3f}s")

        phase3_duration = time.time() - phase3_start
        logger.info(f"[TIMING] Phase 3 (DB Post-processing) took {phase3_duration:.3f}s")

        await websocket.send_json({"reply": reply_text, "sender": "bot"})

        total_time = time.time() - msg_start_time
        logger.info(f"[TIMING] Total Message Turnaround Time: {total_time:.3f}s")

    async def _run_ai_turn_safe(phase1_data: dict, my_generation: int):
        try:
            await _run_ai_turn(phase1_data, my_generation)
        except asyncio.CancelledError:
            logger.info(f"AI turn for {session_id} cancelled (superseded by a merged follow-up).")
            raise
        except Exception as e:
            logger.error(f"Error processing AI turn for {session_id}: {e}", exc_info=True)

    def _start_turn(phase1_data: dict) -> asyncio.Task:
        nonlocal current_turn_task
        turn_generation["value"] += 1
        my_generation = turn_generation["value"]
        task = asyncio.create_task(_run_ai_turn_safe(phase1_data, my_generation))
        current_turn_task = task
        return task

    async def _wait_until_quiet():
        """Blocks until it's genuinely safe to process: the customer isn't
        (or is no longer) typing, AND nothing new has happened for
        TYPING_STOPPED_GRACE_SECONDS. Governed primarily by the real-time
        typing signal, not a fixed timer — a fixed grace period only
        applies once typing has actually stopped (or never started, e.g. a
        paste-and-send with no keystrokes)."""
        nonlocal is_typing
        while True:
            if is_typing:
                # Don't apply any fixed wait while the customer is actively
                # typing — just wait for the next signal (more typing,
                # stopped_typing, or a sent message). The safety cap is a
                # defensive fallback only, see the constant's docstring.
                try:
                    await asyncio.wait_for(pending_event.wait(), timeout=TYPING_ACTIVE_SAFETY_CAP_SECONDS)
                    pending_event.clear()
                    continue  # re-check is_typing — it may have just flipped
                except asyncio.TimeoutError:
                    logger.warning(
                        f"Typing indicator for {session_id} stayed active longer than "
                        f"{TYPING_ACTIVE_SAFETY_CAP_SECONDS}s with no stopped_typing — "
                        "treating as stopped."
                    )
                    is_typing = False
                    continue
            else:
                # Not typing (or just stopped) — short, fixed grace window.
                try:
                    await asyncio.wait_for(pending_event.wait(), timeout=TYPING_STOPPED_GRACE_SECONDS)
                    pending_event.clear()
                    continue  # something happened during the grace window — recheck from the top
                except asyncio.TimeoutError:
                    return  # genuinely quiet

    async def _debounce_worker():
        nonlocal latest_phase1_data
        while True:
            await pending_event.wait()
            pending_event.clear()

            await _wait_until_quiet()

            if latest_phase1_data is None:
                continue

            # Re-check handoff status right before firing — a human agent
            # may have claimed the conversation during the wait window,
            # even though it wasn't claimed when the last message arrived.
            recheck = await asyncio.to_thread(_sync_setup_conversation, session_id)
            if recheck["handoff_active"]:
                latest_phase1_data = None
                continue

            phase1_data, latest_phase1_data = latest_phase1_data, None
            task = _start_turn(phase1_data)
            try:
                await task
            except asyncio.CancelledError:
                # A follow-up message arrived while this turn was still in
                # flight and superseded it (see the interrupt-and-merge
                # branch in the receive loop below). The replacement turn
                # is already running independently via its own _start_turn
                # call — nothing more to do here, just loop back around.
                pass

    debounce_worker_task = asyncio.create_task(_debounce_worker())
    manager.register_customer_debounce_task(session_id, debounce_worker_task)

    try:
        # One-off connection for initial setup (non-blocking)
        init_data = await asyncio.to_thread(_sync_setup_conversation, session_id)
        if init_data["reopen_count"] > 0 and not init_data["handoff_active"]:
            await manager.broadcast_to_agents({
                "type": "reopen",
                "session_id": session_id,
                "reopen_count": init_data["reopen_count"],
                "is_resolved": init_data["resolved"],
            })

        while True:
            data = await websocket.receive_json()

            # Real-time typing signal from the customer. This drives the
            # debounce logic in _wait_until_quiet() directly, and is also
            # relayed to the agent dashboard so a human agent can see
            # "customer is typing" too, exactly like the existing
            # agent -> customer typing indicator, just in reverse.
            if data.get("type") in ("typing", "stopped_typing"):
                is_typing = data["type"] == "typing"
                asyncio.create_task(manager.broadcast_to_agents({
                    "type": data["type"],
                    "session_id": session_id,
                }))
                pending_event.set()
                mid_turn_typing_event.set()
                continue

            customer_text = data.get("message")
            if not customer_text:
                continue

            if len(customer_text) > 2000:
                logger.warning(f"Message from {session_id} exceeded max length. Truncating.")
                customer_text = customer_text[:2000]

            # Check for audio and transcribe it
            customer_text = await transcribe_audio_if_present(customer_text)

            # Auto-translate if not English (for the Agent Console)
            customer_text = await auto_translate_if_needed(customer_text)

            logger.info(f"Received message from customer {session_id}: {mask_pii(customer_text)}")

            # If a turn is already in flight for this conversation, cancel
            # it and restart immediately with the freshest data (fetched
            # just below via Phase 1, which always returns the FULL
            # up-to-date history) instead of going through the normal
            # quiet-period debounce. The customer already showed clear
            # intent by finishing and sending this message, so there's no
            # reason to make them wait further, and this produces exactly
            # ONE fully-informed reply instead of a stale one followed by a
            # corrected one. The cancelled turn's reply — whether it was
            # still generating or already sitting in the "hold, in case a
            # follow-up is coming" wait — is discarded entirely; nothing
            # from it is reused, only the plain conversation history (which
            # naturally includes both the old and new customer messages as
            # separate turns, exactly as they were sent) feeds the fresh one.
            interrupting_inflight_turn = current_turn_task is not None and not current_turn_task.done()
            if interrupting_inflight_turn:
                current_turn_task.cancel()

            # A message arriving always means typing has effectively ended
            # for debounce purposes, even if stopped_typing hasn't fired yet
            # (e.g. Enter pressed before the 1.5s client-side timeout) — the
            # grace period in _wait_until_quiet() still applies from here.
            is_typing = False

            # Rate Limiting (max 15 msgs / minute) — unchanged, still applies
            # per raw message regardless of debouncing, to guard against
            # socket flooding.
            try:
                r = get_redis()
                rate_key = f"rate_limit:{session_id}"
                _t0 = time.time()
                count = await r.incr(rate_key)
                logger.info(f"[TIMING] redis_incr took {time.time() - _t0:.3f}s")
                if count == 1:
                    await r.expire(rate_key, 60)
                if count > 15:
                    logger.warning(f"Rate limit exceeded for {session_id}")
                    await websocket.send_json({"reply": "You are sending messages too quickly. Please wait a minute."})
                    continue
            except Exception as e:
                logger.error(f"Rate limiting error: {e}")

            # Phase 1: Pre-processing & DB Save — unchanged, still runs
            # immediately per raw message so agents see live messages as
            # they're typed.
            phase1_start = time.time()
            phase1_data = await asyncio.to_thread(_sync_phase1, session_id, customer_text)
            if not phase1_data:
                continue
            logger.info(f"[TIMING] Phase 1 (DB Pre-processing) took {time.time() - phase1_start:.3f}s")

            # Broadcast ALL customer messages to the agent dashboard for real-time sync in background.
            _t0 = time.time()
            asyncio.create_task(manager.broadcast_to_agents({
                "type": "new_message",
                "session_id": session_id,
                "sender": "human",
                "content": customer_text,
                "is_resolved": phase1_data["resolved"],
                "message_id": phase1_data["message_id"]
            }))
            logger.info(f"[TIMING] broadcast_to_agents (human msg) dispatched in {time.time() - _t0:.3f}s")

            if phase1_data.get("handoff_active"):
                # A human agent already owns this conversation — the AI stays silent.
                continue

            if phase1_data["reopened"]:
                _t0 = time.time()
                asyncio.create_task(manager.broadcast_to_agents({
                    "type": "reopen",
                    "session_id": session_id,
                    "reopen_count": phase1_data["reopen_count"],
                    "is_resolved": phase1_data["resolved"],
                }))
                logger.info(f"[TIMING] broadcast_to_agents (reopen) dispatched in {time.time() - _t0:.3f}s")

            # Hand off appropriately: if we just interrupted an in-flight
            # turn above, restart immediately with this fresh data (no
            # additional debounce wait — the customer already completed
            # and sent a message, so there's nothing left to wait for).
            # Otherwise, defer to the normal debounce worker as before —
            # it'll fire once the customer actually pauses.
            if interrupting_inflight_turn:
                _start_turn(phase1_data)
            else:
                latest_phase1_data = phase1_data
                pending_event.set()

    except WebSocketDisconnect:
        logger.info(f"Customer disconnected: {session_id}")
        manager.disconnect_customer(session_id, websocket)
    except Exception as e:
        logger.error(f"Error in customer_websocket: {e}", exc_info=True)
        manager.disconnect_customer(session_id, websocket)
    finally:
        debounce_worker_task.cancel()
        if current_turn_task is not None and not current_turn_task.done():
            current_turn_task.cancel()


@router.websocket("/ws/agent")
async def agent_websocket(websocket: WebSocket, access_token: str | None = Cookie(None), token: str | None = None):
    # Accept BEFORE validating — see the matching comment in
    # customer_websocket() for the full explanation. In short: a
    # pre-accept close() can't carry a custom code to the browser, it just
    # shows up as an HTTP 403 during the handshake (exactly what the
    # "Agent connection rejected: unauthorized" / "403 Forbidden" log
    # pairing was) and the frontend has no way to distinguish it from any
    # other disconnect reason, so it kept retrying forever.
    await websocket.accept()

    raw_token = token or access_token
    if not raw_token:
        logger.warning("Agent connection rejected: missing token")
        await websocket.close(code=4401)
        return
        
    raw_token = raw_token.replace("Bearer ", "")
    token_data = decode_access_token(raw_token)
    if token_data is None or not token_data.get("sub"):
        logger.warning("Agent connection rejected: unauthorized")
        await websocket.close(code=4401)
        return

    username = token_data["sub"]

    try:
        # Validate agent once (non-blocking)
        agent_data = await asyncio.to_thread(_sync_validate_agent, username, token_data.get("pwd_frag"))
        if not agent_data:
            logger.warning("Agent connection rejected: invalid/revoked token or missing agent")
            await websocket.close(code=4401)
            return

        logger.info(f"Agent connected: {username}")
        await manager.connect_agent(websocket)
        
        while True:
            data = await websocket.receive_json()
            session_id = data.get("session_id")
            if data.get("type") in ["typing", "stopped_typing"]:
                if session_id:
                    await manager.send_to_customer(session_id, {"type": data["type"]})
                continue
                
            reply_text = data.get("message")
            is_internal = data.get("is_internal", False)
            
            if not session_id or not reply_text:
                continue
                
            logger.info(f"Agent {username} replied to conversation {session_id} (Internal: {is_internal})")

            reply_data = await asyncio.to_thread(_sync_agent_reply, session_id, username, reply_text, is_internal)
            if not reply_data:
                continue
                
            if not is_internal and reply_data["handoff_active"]:
                await manager.broadcast_to_agents({
                    "type": "handoff",
                    "session_id": session_id,
                    "ticket_id": "manual_intervention",
                    "is_resolved": reply_data["resolved"],
                })

            # SECURITY: Defense-in-depth — check both the is_internal flag
            # AND the actual stored sender. Even if is_internal is somehow
            # wrong, the sender check prevents internal notes from leaking.
            msg_sender = "agent_internal" if is_internal else "agent"
            if not is_internal and msg_sender != "agent_internal":
                # Customer receives same shape as AI reply — seamless handoff.
                await manager.send_to_customer(session_id, {
                    "reply": reply_text, 
                    "sender": "agent", 
                    "name": agent_data["full_name"]
                })
            
            # Broadcast to all agents so they stay in sync
            await manager.broadcast_to_agents({
                "type": "new_message",
                "session_id": session_id,
                "sender": "agent_internal" if is_internal else "agent",
                "content": reply_text,
                "is_resolved": reply_data["resolved"],
                "message_id": reply_data["message_id"]
            })

    except WebSocketDisconnect:
        manager.disconnect_agent(websocket)
    except Exception as e:
        logger.error(f"Error in agent_websocket: {e}", exc_info=True)
        manager.disconnect_agent(websocket)
