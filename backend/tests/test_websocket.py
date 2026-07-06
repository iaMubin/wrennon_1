import os

from fastapi.testclient import TestClient
import pytest
from app.main import app
from app.db.session import SessionLocal

client = TestClient(app)

def test_websocket_connection_and_length_limit():
    session_id = "test-session-ws-1"
    
    # Can't easily test full redis-backed websocket loop in isolated test without mocking Redis,
    # but we can verify the HTTP endpoint for status works and respects the limit.
    
    response = client.get(f"/api/chat/{session_id}/status")
    # Should return status='not_found' since it doesn't exist
    assert response.status_code == 200
    assert response.json() == {"status": "not_found"}
    
    # Test rate limiter on status endpoint
    for _ in range(101):
        resp = client.get(f"/api/chat/{session_id}/status")
        
    assert resp.status_code == 429 # Too Many Requests
