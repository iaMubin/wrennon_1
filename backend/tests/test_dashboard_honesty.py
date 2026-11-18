"""The dashboard and analytics must report what happened, never what would look good.

Before this, both endpoints padded thin databases with invented numbers (a made-up team,
made-up SLA/CSAT figures, sample volume curves). These tests pin the opposite behaviour:
measured values are exact, and anything unmeasurable is null / empty.
"""
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth.security import hash_password
from app.db.models import Agent, Conversation, CSATResponse, Message
from app.db.session import SessionLocal
from app.main import app
from app.services import dashboard_stats as ds

client = TestClient(app)

# A calendar day far in the past, so these assertions only ever see the rows created here.
DAY = datetime(2001, 1, 1, 10, 0, 0)
NEXT_DAY = datetime(2001, 1, 2)
EMPTY_DAY, EMPTY_NEXT = datetime(2002, 1, 1), datetime(2002, 1, 2)

FABRICATED = [
    "Sarah Jenkins", "Michael Chang", "Elena Rostova", "Marcus Vance", "Wren Autonomous Copilot",
    "$12,480", "mock-risk", "Eleanor Vance", "James Wilson", "99.98",
]


@pytest.fixture(scope="module")
def seeded():
    db = SessionLocal()
    for u in ("honest_mgr", "honest_a", "honest_scope"):
        old = db.query(Agent).filter_by(username=u).first()
        if old:
            db.delete(old)
    db.commit()
    mgr = Agent(username="honest_mgr", full_name="Honest Manager", employee_id="HON-1", role="manager",
                password_hash=hash_password("SecureAdmin!123"))
    a = Agent(username="honest_a", full_name="Ada Agent", employee_id="HON-2", role="agent",
              password_hash=hash_password("SecureAdmin!123"))
    scoped = Agent(username="honest_scope", full_name="Scope Agent", employee_id="HON-3", role="agent",
                   password_hash=hash_password("SecureAdmin!123"))
    db.add_all([mgr, a, scoped])
    db.commit()

    # A: resolved by a human in 60 min, replied after 2 min, rated 5
    ca = Conversation(session_id="honest-a", customer_email="a@example.com", resolved=True, handled_by="honest_a",
                      created_at=DAY, resolved_at=DAY + timedelta(minutes=60), reopen_count=0, priority="normal",
                      intent_category="Shipping", sentiment="Happy")
    # B: resolved by the AI alone in 30 min, reopened once, rated 3
    cb = Conversation(session_id="honest-b", customer_email="b@example.com", resolved=True, handled_by=None,
                      created_at=DAY + timedelta(minutes=30), resolved_at=DAY + timedelta(minutes=60), reopen_count=1,
                      priority="normal", intent_category="Shipping", sentiment="Frustrated")
    # C: still open, urgent, first human reply took 20 min (urgent SLA is 15)
    cc = Conversation(session_id="honest-c", customer_email="c@example.com", resolved=False,
                      created_at=DAY + timedelta(hours=2), priority="urgent")
    # D: belongs to someone else, so honest_scope must not see it through the profile either
    cd = Conversation(session_id="honest-d", customer_email="scope@example.com", resolved=False, handled_by="someone_else",
                      assigned_agent="someone_else", handoff_active=True, created_at=datetime(2001, 2, 1, 10, 0, 0))
    db.add_all([ca, cb, cc, cd])
    db.commit()
    db.add_all([
        Message(conversation_id=ca.id, sender="agent", content="on it", created_at=DAY + timedelta(minutes=2)),
        Message(conversation_id=ca.id, sender="agent_internal", content="note", created_at=DAY + timedelta(minutes=1)),
        Message(conversation_id=cc.id, sender="agent", content="hello", created_at=DAY + timedelta(hours=2, minutes=20)),
        CSATResponse(conversation_id=ca.id, rating=5, created_at=DAY + timedelta(minutes=61)),
        CSATResponse(conversation_id=cb.id, rating=3, created_at=DAY + timedelta(minutes=61)),
    ])
    db.commit()
    yield db
    db.query(CSATResponse).filter(CSATResponse.conversation_id.in_([ca.id, cb.id])).delete(synchronize_session=False)
    db.query(Message).filter(Message.conversation_id.in_([ca.id, cb.id, cc.id, cd.id])).delete(synchronize_session=False)
    db.query(Conversation).filter(Conversation.id.in_([ca.id, cb.id, cc.id, cd.id])).delete(synchronize_session=False)
    for u in ("honest_mgr", "honest_a", "honest_scope"):
        row = db.query(Agent).filter_by(username=u).first()
        if row:
            db.delete(row)
    db.commit()
    db.close()


@pytest.fixture(autouse=True)
def mock_redis():
    with patch("app.api.agent.get_redis") as m:
        inst = AsyncMock()
        inst.get.return_value = b"0"
        m.return_value = inst
        yield inst


def _token(user="honest_mgr"):
    r = client.post("/api/agent/login", data={"username": user, "password": "SecureAdmin!123"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ------------------------------------------------------------ exact values
def test_period_kpis_are_exact(seeded):
    k = ds.compute_period(seeded, None, DAY - timedelta(hours=1), NEXT_DAY)
    assert k["volume"] == 3
    assert k["resolved"] == 2
    assert k["mttr_seconds"] == pytest.approx((3600 + 1800) / 2)
    assert k["one_touch_pct"] == pytest.approx(50.0)          # B was reopened
    assert k["ai_resolution_pct"] == pytest.approx(50.0)      # only B had no human
    assert k["ai_resolved"] == 1
    # internal notes are not replies: A's first reply is the 2-minute one
    assert k["first_response_seconds"] == pytest.approx((120 + 1200) / 2)
    assert k["sla_compliance_pct"] == pytest.approx(50.0)     # A in SLA, C (20 min vs 15) not
    assert k["csat_avg"] == pytest.approx(4.0)
    assert k["csat_distribution"][5] == 1 and k["csat_distribution"][3] == 1


def test_nothing_measured_means_none_not_a_made_up_number():
    db = SessionLocal()
    try:
        k = ds.compute_period(db, None, EMPTY_DAY, EMPTY_NEXT)
    finally:
        db.close()
    assert k["volume"] == 0 and k["resolved"] == 0
    for key in ("mttr_seconds", "one_touch_pct", "ai_resolution_pct", "first_response_seconds",
                "p95_first_response_seconds", "sla_compliance_pct", "csat_avg"):
        assert k[key] is None, key
    assert sum(k["csat_distribution"].values()) == 0
    assert all(v is None for v in ds.deltas(k, None).values())


def test_deltas_need_both_periods():
    cur = {"volume": 110, "first_response_seconds": 60.0, "mttr_seconds": 600.0, "csat_avg": 4.5,
           "one_touch_pct": 80.0, "sla_compliance_pct": 90.0}
    prev = {"volume": 100, "first_response_seconds": 80.0, "mttr_seconds": 660.0, "csat_avg": 4.2,
            "one_touch_pct": 75.0, "sla_compliance_pct": None}
    d = ds.deltas(cur, prev)
    assert d["volume_delta"] == "+10.0%" and d["frt_delta"] == "-20s" and d["mttr_delta"] == "-1.0m"
    assert d["csat_delta"] == "+0.3" and d["fcr_delta"] == "+5.0%"
    assert d["sla_delta"] is None                              # no previous SLA figure -> no delta


def test_sentiment_classification():
    assert ds.classify_sentiment("Frustrated") == "negative"
    assert ds.classify_sentiment("Happy") == "positive"
    assert ds.classify_sentiment("Curious") == "neutral"
    assert ds.classify_sentiment(None) is None


# ------------------------------------------------------------ endpoints
def test_analytics_endpoint_has_no_invented_content(seeded):
    h = _token()
    for rng in ("today", "7d", "30d", "ytd", "all"):
        r = client.get("/api/analytics/dashboard-metrics", params={"range": rng}, headers=h)
        assert r.status_code == 200, rng
        data = r.json()
        blob = json.dumps(data)
        for needle in FABRICATED:
            assert needle not in blob, (rng, needle)
        assert data["channel_breakdown"] == []                 # no channel is recorded, so none is shown
        assert len(data["csat_distribution"]) == 5
        assert len(data["hourly_volume"]) == len(data["volume_labels"]) == len(data["resolved_volume"]) > 0
        assert data["csat_distribution"] != [3, 6, 18, 84, 312]
        for row in data["agent_leaderboard"]:
            assert row["ai_assisted_pct"] is None


def test_analytics_leaderboard_names_real_people(seeded):
    r = client.get("/api/analytics/dashboard-metrics", params={"range": "all"}, headers=_token())
    names = {row["handled_by"] for row in r.json()["agent_leaderboard"]}
    assert "Ada Agent" in names and ds.AI_NAME in names
    ada = next(x for x in r.json()["agent_leaderboard"] if x["handled_by"] == "Ada Agent")
    assert ada["role"] == "Agent" and ada["csat"] == 5.0 and ada["resolved_count"] == 1


def test_dashboard_summary_roster_and_stream_are_real(seeded):
    r = client.get("/api/agent/dashboard-summary", headers=_token())
    assert r.status_code == 200
    data = r.json()
    blob = json.dumps(data)
    for needle in FABRICATED:
        assert needle not in blob, needle
    for removed in ("channel_distribution", "queue_tier_distribution"):
        assert removed not in data
    assert set(data["operational_telemetry"]) == {"open_now", "ai_handling", "awaiting_human", "handoff_open", "p95_first_response_seconds"}
    assert len(data["hourly_volume"]) == len(data["hourly_ai_resolved"]) == len(data["hourly_volume_yesterday"]) == 24

    people = {m["name"] for m in data["live_team_status"]}
    assert {"Ada Agent", "Honest Manager", ds.AI_NAME} <= people
    assert all(m["name"] in people for m in data["live_team_status"])

    db = SessionLocal()
    try:
        real_sessions = {s for (s,) in db.query(Conversation.session_id).all()}
    finally:
        db.close()
    for ev in data["copilot_stream"]:
        assert ev["session_id"] in real_sessions
    for risk in data["sla_risks"]:
        assert risk["session_id"] in real_sessions and "customer_tier" not in risk


def test_kb_random_article_endpoint_is_gone():
    r = client.post("/api/kb/suggest", headers=_token())
    assert r.status_code in (404, 405)


def test_customers_have_no_invented_contact_details(seeded):
    """Phone, location, plan and spend used to be derived from an MD5 of the email address."""
    r = client.get("/api/agent/customers", headers=_token())
    assert r.status_code == 200
    rec = next(c for c in r.json() if c["email"] == "a@example.com")
    assert rec["phone"] is None and rec["location"] is None
    assert rec["tier"] is None and rec["lifetime_value"] is None and rec["total_orders"] is None
    assert rec["total_tickets"] == 1 and rec["resolved_ratio"] == 1.0
    assert rec["avg_csat"] == 5.0                      # the one real rating
    assert rec["health_score"] is not None             # measurable, so present
    none_yet = next(c for c in r.json() if c["email"] == "c@example.com")
    assert none_yet["avg_csat"] is None and none_yet["health_score"] is None and none_yet["sentiment"] is None


def test_customer_profile_is_exact_and_cheap(seeded):
    r = client.get("/api/agent/customers/profile", params={"email": "A@Example.com"}, headers=_token())
    assert r.status_code == 200
    p = r.json()
    assert p["total_tickets"] == 1 and p["resolved_ratio"] == 1.0 and p["avg_csat"] == 5.0 and p["csat_count"] == 1
    assert p["health_score"] is not None and p["health_label"] == "Healthy"
    assert p["phone"] is None and p["tier"] is None and p["lifetime_value"] is None
    assert [c["session_id"] for c in p["recent_conversations"]] == ["honest-a"]
    assert p["first_seen"] and p["last_active"]


def test_customer_profile_for_an_unknown_email_is_empty_not_invented(seeded):
    p = client.get("/api/agent/customers/profile", params={"email": "nobody-at-all@example.com"}, headers=_token()).json()
    assert p["total_tickets"] == 0 and p["recent_conversations"] == []
    for k in ("resolved_ratio", "avg_csat", "health_score", "sentiment", "first_seen", "last_active", "phone", "tier"):
        assert p[k] is None, k


def test_customer_profile_respects_what_the_agent_may_see(seeded):
    url, q = "/api/agent/customers/profile", {"email": "scope@example.com"}
    manager = client.get(url, params=q, headers=_token("honest_mgr")).json()
    assert manager["total_tickets"] == 1
    other = client.get(url, params=q, headers=_token("honest_scope")).json()
    assert other["total_tickets"] == 0 and other["recent_conversations"] == []


def test_customer_profile_requires_login():
    assert client.get("/api/agent/customers/profile", params={"email": "a@example.com"}).status_code in (401, 403)
