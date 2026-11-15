"""Regression tests for the Low/Privacy review items (CORS, CSP, Sentry, identity)."""
from fastapi.testclient import TestClient

from app.main import app, _scrub_sentry_event, _drop_app_log_breadcrumbs
from app.db.session import SessionLocal
from app.db.models import Agent, Conversation, Message
from app.auth.security import create_session_token, hash_password
from app.services.public_identity import public_agent_name

client = TestClient(app)


def test_wildcard_cors_never_allows_credentials():
    r = client.get("/health", headers={"Origin": "https://evil.example"})
    assert r.headers.get("access-control-allow-credentials") != "true"


def test_csp_connect_src_is_pinned_not_wildcard():
    csp = client.get("/health").headers["content-security-policy"]
    assert "connect-src 'self'" in csp
    assert "https: wss:" not in csp  # the old any-host exfiltration channel
    assert "object-src 'none'" in csp


def test_sentry_scrubber_drops_bodies_cookies_tokens():
    ev = {"request": {"data": {"message": "my card is ..."}, "cookies": {"access_token": "x"},
                      "query_string": "token=secret",
                      "headers": {"Authorization": "Bearer abc", "Cookie": "a=b", "User-Agent": "ok"}}}
    out = _scrub_sentry_event(ev, {})["request"]
    assert "data" not in out and "cookies" not in out and "query_string" not in out
    assert out["headers"]["Authorization"] == "[Filtered]" and out["headers"]["Cookie"] == "[Filtered]"
    assert out["headers"]["User-Agent"] == "ok"
    assert _drop_app_log_breadcrumbs({"category": "wrennon"}, {}) is None
    assert _drop_app_log_breadcrumbs({"category": "http"}, {}) is not None


def test_public_agent_name_is_first_name_only():
    assert public_agent_name("Sara Khan") == "Sara"
    assert public_agent_name("  ") is None and public_agent_name(None) is None


def test_history_labels_humans_as_agents_not_bot_and_hides_internal_notes():
    db = SessionLocal()
    for u in ("priv_sara",):
        x = db.query(Agent).filter_by(username=u).first()
        if x:
            db.delete(x)
    db.commit()
    db.add(Agent(username="priv_sara", full_name="Sara Khan", employee_id="PRIV-1", role="agent",
                 password_hash=hash_password("SecureAdmin!123")))
    c = Conversation(session_id="priv-sess-1")
    db.add(c); db.commit(); db.refresh(c)
    for sender, content, author in [("human", "hi", None), ("ai", "Hello! I'm the assistant", None),
                                    ("agent", "Sara here", "priv_sara"),
                                    ("agent_internal", "SECRET NOTE", "priv_sara")]:
        db.add(Message(conversation_id=c.id, sender=sender, content=content, author_username=author))
    db.commit(); conv_id = c.id; db.close()

    tok = create_session_token("priv-sess-1")
    r = client.get("/api/chat/priv-sess-1/history", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    body = r.json()
    assert [m["sender"] for m in body] == ["user", "bot", "agent"]
    assert body[2]["name"] == "Sara" and body[1]["name"] is None
    assert "SECRET NOTE" not in str(body)

    db = SessionLocal()
    db.query(Message).filter_by(conversation_id=conv_id).delete()
    db.query(Conversation).filter_by(id=conv_id).delete()
    db.query(Agent).filter_by(username="priv_sara").delete()
    db.commit(); db.close()
