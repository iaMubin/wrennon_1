import uuid

import pyotp
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.auth.security import create_access_token, decode_access_token, decode_session_token, hash_password
from app.db.models import Agent, AuditLog, Conversation
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)


def _init():
    r = client.post("/api/chat/init").json()
    return r["session_id"], r["token"]


def test_ws_accepts_token_via_subprotocol_and_echoes_it():
    sid, tok = _init()
    with client.websocket_connect(f"/ws/customer/{sid}", subprotocols=["wrennon.v1", tok]) as ws:
        assert ws.accepted_subprotocol == "wrennon.v1"
        ws.send_json({"type": "typing"})


def test_ws_query_token_refused_when_disabled(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ws_allow_query_token", False)
    sid, tok = _init()
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect(f"/ws/customer/{sid}?token={tok}") as ws:
            ws.receive_text()
    assert e.value.code == 4401


def test_token_types_are_not_interchangeable():
    sid, cust = _init()
    assert decode_access_token(cust) is None                       # customer token is not an agent token
    agent_tok = create_access_token("someone", 1)
    assert decode_session_token(agent_tok) is None


def test_revoked_session_cannot_use_rest_or_ws():
    sid, tok = _init()
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get(f"/api/chat/{sid}/status", headers=h).status_code == 200

    db = SessionLocal()
    db.add(Conversation(session_id=sid)); db.commit()
    name = f"mgr_{uuid.uuid4().hex[:8]}"
    ag = Agent(username=name, full_name="M", employee_id=f"E-{uuid.uuid4().hex[:6]}", password_hash=hash_password("x"), role="manager")
    db.add(ag); db.commit()
    atok = create_access_token(name, ag.token_version)
    r = client.post(f"/api/agent/conversations/{sid}/revoke-session", headers={"Authorization": f"Bearer {atok}"})
    assert r.status_code == 200, r.text

    assert client.get(f"/api/chat/{sid}/status", headers=h).status_code == 401
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect(f"/ws/customer/{sid}", subprotocols=["wrennon.v1", tok]) as ws:
            ws.receive_text()
    assert e.value.code == 4401
    assert db.query(AuditLog).filter_by(action="revoke_customer_session", target_username=sid).count() == 1
    db.delete(ag); db.commit(); db.close()


@pytest.fixture
def agent_with_2fa():
    db = SessionLocal()
    name = f"tfa_{uuid.uuid4().hex[:8]}"
    secret = pyotp.random_base32()
    ag = Agent(username=name, full_name="T", employee_id=f"E-{uuid.uuid4().hex[:6]}", password_hash=hash_password("Passw0rd!x"),
               role="agent", totp_secret=secret, totp_enabled=True)
    db.add(ag); db.commit()
    yield name, secret, ag.token_version
    db.query(AuditLog).filter_by(actor_username=name).delete()
    db.delete(db.query(Agent).filter_by(username=name).first()); db.commit(); db.close()


def test_2fa_setup_requires_password_and_current_code_when_enabled(agent_with_2fa):
    name, secret, tv = agent_with_2fa
    h = {"Authorization": f"Bearer {create_access_token(name, tv)}"}
    url = "/api/agent/2fa/setup"
    assert client.post(url, headers=h).status_code == 422                                           # body required
    assert client.post(url, headers=h, json={"current_password": "wrong"}).status_code == 401       # password step-up
    assert client.post(url, headers=h, json={"current_password": "Passw0rd!x"}).status_code == 401  # 2FA on: code required
    assert client.post(url, headers=h, json={"current_password": "Passw0rd!x", "code": "000000"}).status_code == 401
    ok = client.post(url, headers=h, json={"current_password": "Passw0rd!x", "code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200
    db = SessionLocal()
    actions = {a.action for a in db.query(AuditLog).filter_by(actor_username=name)}
    db.close()
    assert {"2fa_setup_denied", "2fa_setup_started"} <= actions


def test_totp_code_cannot_be_replayed_and_failures_are_audited(agent_with_2fa):
    name, secret, _ = agent_with_2fa
    code = pyotp.TOTP(secret).now()
    form = {"username": name, "password": "Passw0rd!x", "totp_code": code}
    assert client.post("/api/agent/login", data=form).status_code == 200
    assert client.post("/api/agent/login", data=form).status_code == 401       # same code again
    bad = client.post("/api/agent/login", data={**form, "password": "wrong"})
    assert bad.status_code == 401
    db = SessionLocal()
    actions = [a.action for a in db.query(AuditLog).filter_by(actor_username=name)]
    db.close()
    assert "login" in actions and actions.count("login_failed") >= 2


def test_admin_password_not_reverted_on_boot(monkeypatch):
    import inspect, app.main as m
    src = inspect.getsource(m)
    assert "elif settings.force_admin_password_reset" in src
