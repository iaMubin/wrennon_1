import pytest
from fastapi.testclient import TestClient

from unittest.mock import AsyncMock, patch

from app.main import app
from app.db.session import SessionLocal
from app.db.models import Agent
from app.auth.security import hash_password

client = TestClient(app)

@pytest.fixture(scope="module")
def setup_test_agent():
    db = SessionLocal()
    # Ensure test agent does not exist
    agent = db.query(Agent).filter_by(username="test_admin").first()
    if agent:
        db.delete(agent)
        db.commit()

    hashed_pw = hash_password("SecureAdmin!123")
    new_agent = Agent(
        username="test_admin",
        full_name="Test Admin",
        employee_id="TEST-1234",
        role="manager",
        password_hash=hashed_pw
    )
    db.add(new_agent)
    db.commit()
    yield
    # Cleanup
    db.delete(new_agent)
    db.commit()
    db.close()

@pytest.fixture(autouse=True)
def mock_redis():
    with patch("app.api.agent.get_redis") as mock_get_redis:
        mock_r = AsyncMock()
        mock_r.get.return_value = None
        mock_get_redis.return_value = mock_r
        yield mock_r

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_login_success(setup_test_agent):
    response = client.post(
        "/api/agent/login",
        data={"username": "test_admin", "password": "SecureAdmin!123"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

def test_login_invalid_password(setup_test_agent):
    response = client.post(
        "/api/agent/login",
        data={"username": "test_admin", "password": "WrongPassword123!"}
    )
    assert response.status_code == 401

def test_session_token_creation_and_decoding():
    from app.auth.security import create_session_token, decode_session_token
    session_id = "test-session-123"
    token = create_session_token(session_id)
    
    assert token is not None
    assert type(token) == str

    decoded_session_id = decode_session_token(token)
    assert decoded_session_id == session_id

def test_expired_session_token_fails():
    import datetime
    from jose import jwt
    from app.config import settings
    from app.auth.security import decode_session_token

    # Create a manually expired token
    expire = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    to_encode = {"session_id": "expired-session", "exp": expire}
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    result = decode_session_token(encoded_jwt)
    assert result is None

def test_invalid_session_token_fails():
    from app.auth.security import decode_session_token
    
    result = decode_session_token("invalid.token.here")
    assert result is None
