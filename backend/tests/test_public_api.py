import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.db.models import Agent, ApiKey, Conversation, Message
from app.auth.security import hash_password

client = TestClient(app)

@pytest.fixture
def db_session():
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture
def api_key(db_session: Session):
    raw_key = "wk_live_testkey123"
    key_hash = hash_password(raw_key)
    api_key = ApiKey(
        name="Test API Key",
        key_hash=key_hash,
        prefix=raw_key[:16],
        created_by_username="testadmin"
    )
    db_session.add(api_key)
    db_session.commit()
    db_session.refresh(api_key)
    return {"raw_key": raw_key, "id": api_key.id}

import uuid

@pytest.fixture
def conversation(db_session: Session):
    conv = Conversation(
        session_id=f"test-public-api-{uuid.uuid4()}"
    )
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)
    return conv

def test_list_conversations_unauthorized():
    response = client.get("/api/v1/conversations")
    assert response.status_code == 403 or response.status_code == 401

def test_list_conversations_authorized(api_key):
    headers = {"Authorization": f"Bearer {api_key['raw_key']}"}
    response = client.get("/api/v1/conversations", headers=headers)
    assert response.status_code == 200
    assert "data" in response.json()

def test_get_conversation_details(api_key, conversation):
    headers = {"Authorization": f"Bearer {api_key['raw_key']}"}
    response = client.get(f"/api/v1/conversations/{conversation.short_id}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == conversation.id

def test_add_message(api_key, conversation, db_session: Session):
    headers = {"Authorization": f"Bearer {api_key['raw_key']}"}
    payload = {"content": "Hello from API"}
    response = client.post(f"/api/v1/conversations/{conversation.short_id}/messages", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["content"] == "Hello from API"
    
    # Check DB
    msg = db_session.query(Message).filter_by(id=data["id"]).first()
    assert msg is not None
    assert msg.content == "Hello from API"

def test_resolve_conversation(api_key, conversation, db_session: Session):
    headers = {"Authorization": f"Bearer {api_key['raw_key']}"}
    response = client.post(f"/api/v1/conversations/{conversation.short_id}/resolve", headers=headers)
    assert response.status_code == 200
    
    db_session.refresh(conversation)
    assert conversation.resolved == True
