import os

from fastapi.testclient import TestClient
import pytest
from app.main import app
from app.db.session import SessionLocal

client = TestClient(app)

def test_websocket_connection_and_length_limit():
    # 1. Get token
    init_resp = client.post("/api/chat/init")
    assert init_resp.status_code == 200
    session_id = init_resp.json()["session_id"]
    token = init_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. Test status endpoint with token
    response = client.get(f"/api/chat/{session_id}/status", headers=headers)
    # Should return status='not_found' since it doesn't exist in DB yet (init just generates token)
    assert response.status_code == 200
    assert response.json() == {"status": "not_found"}
    
    # Test rate limiter on status endpoint
    for _ in range(101):
        resp = client.get(f"/api/chat/{session_id}/status", headers=headers)
        
    assert resp.status_code == 429 # Too Many Requests

def test_chat_auth_rejection():
    # Test that missing token rejects
    resp = client.get("/api/chat/fake-session/status")
    assert resp.status_code == 401
    
    # Test that cross-session token rejects
    init_resp = client.post("/api/chat/init")
    token = init_resp.json()["token"]
    resp = client.get("/api/chat/other-session/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401

def test_websocket_connection_success():
    init_resp = client.post("/api/chat/init")
    session_id = init_resp.json()["session_id"]
    token = init_resp.json()["token"]
    
    with client.websocket_connect(f"/ws/customer/{session_id}?token={token}") as websocket:
        # Test basic connection. It shouldn't be immediately closed.
        # Send a message and wait for an ack or something, but we don't need to wait for full LLM.
        # The main thing is that we successfully connect.
        websocket.send_text("Hello")
        # We might receive some message back from the LLM, or we can just exit the context cleanly.
        pass

def test_websocket_connection_missing_token_rejected():
    from starlette.websockets import WebSocketDisconnect
    init_resp = client.post("/api/chat/init")
    session_id = init_resp.json()["session_id"]

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"/ws/customer/{session_id}") as websocket:
            # The connection is accepted first (necessary so the 4401 close
            # code below can actually reach the client instead of becoming
            # an opaque HTTP-level rejection — see the comment in
            # customer_websocket()), then immediately closed since no token
            # was provided. The disconnect surfaces on the next receive.
            websocket.receive_json()
    assert excinfo.value.code == 4401

def test_websocket_connection_invalid_token_rejected():
    from starlette.websockets import WebSocketDisconnect
    init_resp = client.post("/api/chat/init")
    session_id = init_resp.json()["session_id"]

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"/ws/customer/{session_id}?token=invalid.token.here") as websocket:
            websocket.receive_json()
    assert excinfo.value.code == 4401


def test_agent_websocket_missing_token_delivers_real_close_code():
    """This is the endpoint from the actual production bug report: an
    agent dashboard with a missing/expired/invalid token kept retrying
    forever because the close code never reached the browser. Root cause
    was calling websocket.close(code=4401) BEFORE websocket.accept() —
    ASGI/Starlette can only deliver a real close code to the client if the
    handshake was already accepted; closing before accept() instead
    surfaces as a bare HTTP-level rejection with no code the client can
    read. This test would have caught that: without the accept()-first
    fix, this assertion fails because no real WebSocketDisconnect with
    code 4401 is ever observable by the client."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/ws/agent") as websocket:
            websocket.receive_json()
    assert excinfo.value.code == 4401


def test_agent_websocket_invalid_token_delivers_real_close_code():
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/ws/agent?token=invalid.token.here") as websocket:
            websocket.receive_json()
    assert excinfo.value.code == 4401
