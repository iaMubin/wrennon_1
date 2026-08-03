import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
from datetime import datetime
import pytz

from app.main import app
from app.db.session import SessionLocal
from app.db.models import Agent, Conversation
from app.auth.security import hash_password

client = TestClient(app)

@pytest.fixture(scope="module")
def setup_test_data():
    db = SessionLocal()
    agent = db.query(Agent).filter_by(username="dash_admin").first()
    if agent:
        db.delete(agent)
        db.commit()

    hashed_pw = hash_password("SecureAdmin!123")
    new_agent = Agent(
        username="dash_admin",
        full_name="Dashboard Admin",
        employee_id="DASH-1234",
        role="manager",
        password_hash=hashed_pw
    )
    db.add(new_agent)
    db.commit()
    
    # Create some conversations
    tz = pytz.timezone('Asia/Dhaka')
    now = datetime.now(tz)
    
    c1 = Conversation(session_id="session1", resolved=False, customer_email="alice@example.com")
    c2 = Conversation(session_id="session2", resolved=False, assigned_agent="dash_admin", customer_email="bob@example.com")
    c3 = Conversation(session_id="session3", resolved=True, resolved_at=now, customer_email="alice@example.com")
    
    db.add_all([c1, c2, c3])
    db.commit()
    
    yield new_agent
    
    # Cleanup
    db.query(Conversation).filter(Conversation.session_id.in_(["session1", "session2", "session3"])).delete(synchronize_session=False)
    db.delete(new_agent)
    db.commit()
    db.close()

@pytest.fixture(autouse=True)
def mock_redis():
    with patch("app.api.agent.get_redis") as mock_get_redis:
        mock_redis_instance = AsyncMock()
        mock_redis_instance.get.return_value = b'0'
        mock_get_redis.return_value = mock_redis_instance
        yield mock_redis_instance

def test_dashboard_summary(setup_test_data):
    # Login to get token
    response = client.post(
        "/api/agent/login",
        data={"username": "dash_admin", "password": "SecureAdmin!123"}
    )
    assert response.status_code == 200
    token = response.json().get("access_token")
    
    # Now get dashboard summary
    response = client.get(
        "/api/agent/dashboard-summary",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "open_tickets" in data
    assert "unassigned" in data
    assert "solved_today" in data
    assert "csat_score" in data
    assert "agent_chat_counts" in data
    assert "hourly_volume" in data
    assert len(data["hourly_volume"]) == 24
    
    # Check logic matches what we seeded
    assert data["unassigned"] >= 1
    assert data["solved_today"] >= 1
    assert "dash_admin" in data["agent_chat_counts"]

def test_analytics_dashboard_metrics(setup_test_data):
    # Login to get token
    response = client.post(
        "/api/agent/login",
        data={"username": "dash_admin", "password": "SecureAdmin!123"}
    )
    assert response.status_code == 200
    token = response.json().get("access_token")
    
    # Now get analytics dashboard metrics
    response = client.get(
        "/api/analytics/dashboard-metrics",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "avg_resolution_time_seconds" in data
    assert "one_touch_resolutions_pct" in data
    assert "first_response_time_seconds" in data
    assert "csat_distribution" in data
    assert len(data["csat_distribution"]) == 5
    assert "hourly_volume" in data
    assert len(data["hourly_volume"]) == 24

def test_agent_customers(setup_test_data):
    # Login to get token
    response = client.post(
        "/api/agent/login",
        data={"username": "dash_admin", "password": "SecureAdmin!123"}
    )
    assert response.status_code == 200
    token = response.json().get("access_token")
    
    # Now get customers
    response = client.get(
        "/api/agent/customers",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    
    # We seeded some conversations with customer_email
    assert len(data) > 0
    cust = data[0]
    assert "email" in cust
    assert "total_tickets" in cust
    assert "last_active" in cust
    assert "resolved_ratio" in cust
    assert "avg_csat" in cust

def test_agent_saved_views(setup_test_data):
    # Login to get token
    response = client.post(
        "/api/agent/login",
        data={"username": "dash_admin", "password": "SecureAdmin!123"}
    )
    assert response.status_code == 200
    token = response.json().get("access_token")
    
    # POST a saved view
    response = client.post(
        "/api/agent/saved-views",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "High Priority", "filter_json": '{"priority": "urgent"}'}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "High Priority"
    assert "id" in data
    view_id = data["id"]
    
    # GET saved views
    response = client.get(
        "/api/agent/saved-views",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert any(v["id"] == view_id for v in data)
    
    # DELETE saved view
    response = client.delete(
        f"/api/agent/saved-views/{view_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    
    # Verify deletion
    response = client.get(
        "/api/agent/saved-views",
        headers={"Authorization": f"Bearer {token}"}
    )
    data = response.json()
    assert not any(v["id"] == view_id for v in data)
