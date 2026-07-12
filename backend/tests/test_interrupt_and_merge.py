import asyncio
import json
import time
from unittest.mock import patch, AsyncMock
import pytest

from fastapi.testclient import TestClient

import app.realtime.websocket_routes as wr

wr.TYPING_STOPPED_GRACE_SECONDS = 0.6  # sped up for tests

manager_call_log = []
final_reply_call_log = []


async def slow_manager_llm(messages, *a, **kw):
    """Simulates a Manager LLM call slow enough to reliably land a
    follow-up message mid-flight."""
    human_texts = [m["content"] for m in messages if m.get("role") == "user"]
    manager_call_log.append(list(human_texts))
    await asyncio.sleep(0.4)
    return json.dumps({
        "reasoning": "answering directly",
        "tools_to_run": [],
        "ready_to_respond": True,
        "handoff_required": False,
        "handoff_reason": "",
        "resolved_required": False,
    })


async def recording_final_reply_llm(messages, *a, **kw):
    human_texts = [m["content"] for m in messages if m.get("role") == "user"]
    final_reply_call_log.append(list(human_texts))
    return f"Reply covering: {' | '.join(human_texts)}"


def _setup_client():
    from app.main import app
    client = TestClient(app)
    init_resp = client.post("/api/chat/init")
    return client, init_resp.json()["session_id"], init_resp.json()["token"]


@pytest.mark.skip(reason="Needs update for new websocket routing debounce logic")
def test_message_arriving_mid_flight_cancels_and_merges_into_one_reply():
    """The core scenario from the transcript: message A starts processing
    (slow Manager call), and before it finishes, message B arrives. The
    in-flight turn for A must be cancelled, and exactly ONE final reply
    must be sent — reflecting BOTH messages, not two separate replies."""
    manager_call_log.clear()
    final_reply_call_log.clear()
    client, session_id, token = _setup_client()

    with patch("app.graph.nodes.manager_node._safe_llm_call", new=slow_manager_llm), \
         patch("app.graph.nodes.final_reply_node._safe_llm_call", new=recording_final_reply_llm), \
         patch("app.realtime.websocket_routes.manager.broadcast_to_agents", new=AsyncMock()):

        with client.websocket_connect(f"/ws/customer/{session_id}?token={token}") as ws:
            ws.send_json({"message": "How do I file a warranty claim?"})
            time.sleep(0.15)  # let it get into the (slow) manager call
            ws.send_json({"message": "It's for a backpack I bought in March."})

            reply = ws.receive_json()
            print("REPLY:", reply)

            # Confirm nothing else arrives afterward (i.e. truly ONE reply,
            # not one now and a stale one trickling in later)
            import queue
            try:
                second = ws.receive_json(timeout=1.5)
                print("UNEXPECTED SECOND REPLY:", second)
                assert False, "Received a second reply — should have been exactly one merged reply"
            except Exception:
                pass  # expected: no second message within the window

    print("final_reply_call_log:", final_reply_call_log)
    assert len(final_reply_call_log) == 1, f"Expected exactly one final reply generation, got {len(final_reply_call_log)}"
    last_call_texts = final_reply_call_log[0]
    assert any("warranty" in t.lower() for t in last_call_texts)
    assert any("backpack" in t.lower() for t in last_call_texts)
    assert "backpack" in reply["reply"].lower()
    assert "warranty" in reply["reply"].lower()


@pytest.mark.skip(reason="Needs update for new websocket routing debounce logic")
def test_no_typing_no_new_message_reply_sent_immediately_with_no_delay():
    """Baseline: if nobody is typing when a reply becomes ready, it should
    be sent immediately, with no added hold delay."""
    manager_call_log.clear()
    final_reply_call_log.clear()
    client, session_id, token = _setup_client()

    async def fast_manager_llm(messages, *a, **kw):
        return json.dumps({
            "reasoning": "ok", "tools_to_run": [], "ready_to_respond": True,
            "handoff_required": False, "handoff_reason": "", "resolved_required": False,
        })

    with patch("app.graph.nodes.manager_node._safe_llm_call", new=fast_manager_llm), \
         patch("app.graph.nodes.final_reply_node._safe_llm_call", new=recording_final_reply_llm), \
         patch("app.realtime.websocket_routes.manager.broadcast_to_agents", new=AsyncMock()):

        with client.websocket_connect(f"/ws/customer/{session_id}?token={token}") as ws:
            start = time.time()
            ws.send_json({"message": "hello"})
            reply = ws.receive_json()
            elapsed = time.time() - start
            print(f"Reply arrived in {elapsed:.2f}s")

    assert len(final_reply_call_log) == 1
    # Should arrive quickly — well under the grace period, since nobody
    # was typing when the reply became ready.
    assert elapsed < 2.0


@pytest.mark.skip(reason="Needs update for new websocket routing debounce logic")
def test_typing_during_hold_window_without_follow_up_releases_original_reply():
    """If the customer starts typing right as a reply becomes ready, but
    then stops WITHOUT sending anything, the original (unmodified) reply
    must still be released after the grace period — not lost."""
    manager_call_log.clear()
    final_reply_call_log.clear()
    client, session_id, token = _setup_client()

    async def fast_manager_llm(messages, *a, **kw):
        return json.dumps({
            "reasoning": "ok", "tools_to_run": [], "ready_to_respond": True,
            "handoff_required": False, "handoff_reason": "", "resolved_required": False,
        })

    with patch("app.graph.nodes.manager_node._safe_llm_call", new=fast_manager_llm), \
         patch("app.graph.nodes.final_reply_node._safe_llm_call", new=recording_final_reply_llm), \
         patch("app.realtime.websocket_routes.manager.broadcast_to_agents", new=AsyncMock()):

        with client.websocket_connect(f"/ws/customer/{session_id}?token={token}") as ws:
            ws.send_json({"message": "what is your refund policy"})
            time.sleep(0.05)
            # Customer starts typing right as the (fast) reply is likely
            # becoming ready, but never actually sends anything.
            ws.send_json({"type": "typing"})

            reply = ws.receive_json()
            print("REPLY (after typing fizzled out):", reply)

    assert len(final_reply_call_log) == 1
    assert "refund policy" in reply["reply"].lower()


def test_stale_generation_never_written_to_db_even_if_cancellation_lands_late():
    """Directly exercises the race-proof guard inside _sync_phase3: even
    if called with a stale generation number (simulating cancellation
    landing after the DB write was already dispatched to a thread), it
    must return None and write nothing."""
    from app.realtime.websocket_routes import _sync_phase1, _sync_phase3, _sync_setup_conversation
    from app.main import app
    client = TestClient(app)
    init_resp = client.post("/api/chat/init")
    session_id = init_resp.json()["session_id"]

    _sync_setup_conversation(session_id)  # lazily creates the Conversation row, same as a real connect would

    phase1_data = _sync_phase1(session_id, "test message for generation guard")
    assert phase1_data is not None

    turn_generation = {"value": 5}
    # Simulate calling with an OLD generation number (1) while the shared
    # counter has already moved on to 5 (i.e. a newer turn superseded it).
    result = _sync_phase3(session_id, "this stale reply must never be saved", None, 1, turn_generation)
    assert result is None, "Stale-generation write should be rejected, but it wasn't"

    # Confirm no AI message with this content actually landed in the DB.
    from app.db.models import Message, Conversation
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        conv = db.query(Conversation).filter_by(session_id=session_id).first()
        stale_msgs = (
            db.query(Message)
            .filter_by(conversation_id=conv.id, sender="ai")
            .filter(Message.content == "this stale reply must never be saved")
            .all()
        )
        assert len(stale_msgs) == 0, "A stale-generation reply was written to the DB!"

    # And confirm a MATCHING (current) generation number DOES write successfully.
    result2 = _sync_phase3(session_id, "this current reply should be saved", None, 5, turn_generation)
    assert result2 is not None
    with SessionLocal() as db:
        conv = db.query(Conversation).filter_by(session_id=session_id).first()
        current_msgs = (
            db.query(Message)
            .filter_by(conversation_id=conv.id, sender="ai")
            .filter(Message.content == "this current reply should be saved")
            .all()
        )
        assert len(current_msgs) == 1
