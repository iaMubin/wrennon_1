import pytest
from fastapi.testclient import TestClient

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

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_login_success(setup_test_agent):
    response = client.post(
        "/api/agent/login",
        json={"username": "test_admin", "password": "SecureAdmin!123"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

def test_login_invalid_password(setup_test_agent):
    response = client.post(
        "/api/agent/login",
        json={"username": "test_admin", "password": "WrongPassword123!"}
    )
    assert response.status_code == 401
