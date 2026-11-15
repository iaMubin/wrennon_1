import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth.security import create_access_token, hash_password
from app.db.models import Agent, AuditLog, Conversation, Message, SavedView
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)
H = {"X-Wrennon-Client": "agent-dashboard"}


def _mk_agent(db, role="agent", perms=None):
    name = f"{role}_{uuid.uuid4().hex[:8]}"
    ag = Agent(username=name, full_name=name, employee_id=f"E-{uuid.uuid4().hex[:6]}", password_hash=hash_password("x"), role=role,
               permissions=json.dumps(perms or []))
    db.add(ag); db.commit()
    return name, {**H, "Authorization": f"Bearer {create_access_token(name, ag.token_version)}"}


@pytest.fixture
def world():
    db = SessionLocal()
    alice, ha = _mk_agent(db)
    bob, hb = _mk_agent(db)
    boss, hm = _mk_agent(db, role="manager")
    tag = uuid.uuid4().hex[:8]
    convs = {}
    for label, kw in {"queue": {}, "alice": {"handled_by": alice}, "bob": {"handled_by": bob}, "bob_assigned": {"assigned_agent": bob}}.items():
        c = Conversation(session_id=f"acl-{tag}-{label}", customer_email=f"{label}@x.test", handoff_active=True, **kw)
        db.add(c); db.flush()
        db.add(Message(conversation_id=c.id, sender="human", content=f"hello from {label}"))
        convs[label] = c.session_id
    db.commit()
    yield {"alice": (alice, ha), "bob": (bob, hb), "boss": (boss, hm), "convs": convs, "tag": tag}
    for u in (alice, bob, boss):
        db.query(AuditLog).filter_by(actor_username=u).delete()
        db.query(SavedView).filter_by(agent_username=u).delete()
    for sid in convs.values():
        c = db.query(Conversation).filter_by(session_id=sid).first()
        db.query(Message).filter_by(conversation_id=c.id).delete(); db.delete(c)
    for u in (alice, bob, boss):
        db.delete(db.query(Agent).filter_by(username=u).first())
    db.commit(); db.close()


def test_agent_cannot_open_someone_elses_conversation(world):
    _, ha = world["alice"]
    c = world["convs"]
    assert client.get(f"/api/agent/conversations/{c['bob']}", headers=ha).status_code == 404
    assert client.get(f"/api/agent/conversations/{c['bob']}/messages", headers=ha).status_code == 404
    assert client.get(f"/api/agent/conversations/{c['bob_assigned']}/order-context", headers=ha).status_code == 404
    assert client.post(f"/api/agent/conversations/{c['bob']}/resolve", headers=ha).status_code == 404
    assert client.patch(f"/api/agent/conversations/{c['bob']}/properties", headers=ha, json={"priority": "high"}).status_code == 404
    assert client.post("/api/copilot/suggest", headers=ha, json={"ticket_id": c["bob"]}).status_code == 404
    # own + queue are fine
    assert client.get(f"/api/agent/conversations/{c['alice']}", headers=ha).status_code == 200
    assert client.get(f"/api/agent/conversations/{c['queue']}", headers=ha).status_code == 200


def test_listings_are_scoped(world):
    _, ha = world["alice"]
    c = world["convs"]
    ids = {x["session_id"] for x in client.get("/api/agent/conversations", headers=ha).json()}
    assert c["alice"] in ids and c["queue"] in ids
    assert c["bob"] not in ids and c["bob_assigned"] not in ids


def test_manager_sees_everything(world):
    _, hm = world["boss"]
    c = world["convs"]
    for label in ("alice", "bob", "queue"):
        assert client.get(f"/api/agent/conversations/{c[label]}", headers=hm).status_code == 200


def test_bulk_and_merge_cannot_touch_inaccessible_conversations(world):
    _, ha = world["alice"]
    c = world["convs"]
    r = client.patch("/api/agent/conversations/bulk", headers=ha, json={"session_ids": [c["bob"], c["alice"]], "action": "priority", "value": "high"})
    assert r.status_code == 200 and r.json()["updated"] == 1
    r = client.post(f"/api/agent/conversations/{c['alice']}/merge", headers=ha, json={"target_session_id": c["bob"]})
    assert r.status_code == 404


def test_mention_grants_access(world):
    alice, ha = world["alice"]
    c = world["convs"]
    db = SessionLocal()
    conv = db.query(Conversation).filter_by(session_id=c["bob"]).first()
    db.add(Message(conversation_id=conv.id, sender="agent_internal", content=f"@{alice} can you look?", author_username="x")); db.commit(); db.close()
    assert client.get(f"/api/agent/conversations/{c['bob']}", headers=ha).status_code == 200


def test_customer_directory_and_analytics_need_permissions(world):
    _, ha = world["alice"]
    _, hm = world["boss"]
    assert client.get("/api/agent/customers", headers=ha).status_code == 403
    assert client.get("/api/analytics/stats", headers=ha).status_code == 403
    assert client.get("/api/analytics/dashboard-metrics", headers=ha).status_code == 403
    assert client.get("/api/agent/customers", headers=hm).status_code == 200
    assert client.get("/api/analytics/stats", headers=hm).status_code == 200


def test_saved_views_are_private(world):
    _, ha = world["alice"]
    _, hb = world["bob"]
    vid = client.post("/api/agent/saved-views", headers=ha, json={"name": "mine", "filter_json": "{}"}).json()["id"]
    assert all(v["id"] != vid for v in client.get("/api/agent/saved-views", headers=hb).json())
    assert client.delete(f"/api/agent/saved-views/{vid}", headers=hb).status_code == 404
    assert client.delete(f"/api/agent/saved-views/{vid}", headers=ha).status_code == 200


def test_ws_events_are_not_delivered_to_agents_without_access(world):
    import asyncio
    from app.realtime.connection_manager import ConnectionManager

    class FakeWS:
        def __init__(self): self.got = []
        async def send_json(self, p): self.got.append(p)

    alice, _ = world["alice"]; bob, _ = world["bob"]; boss, _ = world["boss"]
    m = ConnectionManager()
    wa, wb, wm = FakeWS(), FakeWS(), FakeWS()
    m._agent_connections = {wa: alice, wb: bob, wm: boss}
    m._agent_view_all = {wa: False, wb: False, wm: True}
    ev = {"type": "new_message", "session_id": world["convs"]["alice"], "content": "secret"}
    asyncio.run(m._deliver_to_agents(ev))
    assert wa.got and wm.got and not wb.got
    q = {"type": "new_message", "session_id": world["convs"]["queue"], "content": "queue"}
    asyncio.run(m._deliver_to_agents(q))
    assert len(wa.got) == 2 and len(wb.got) == 1


def test_manager_cannot_create_or_modify_admin(world):
    boss, hm = world["boss"]
    r = client.post("/api/admin/agents", headers=hm, json={"username": f"adm_{uuid.uuid4().hex[:6]}", "full_name": "X", "employee_id": f"E-{uuid.uuid4().hex[:6]}",
                                                         "password": "Str0ng!Passw", "role": "admin"})
    assert r.status_code == 403
    db = SessionLocal()
    adm = Agent(username=f"adm_{uuid.uuid4().hex[:6]}", full_name="A", employee_id=f"E-{uuid.uuid4().hex[:6]}", password_hash=hash_password("x"), role="admin")
    db.add(adm); db.commit()
    assert client.put(f"/api/admin/agents/{adm.username}/reset-password", headers=hm, json={"new_password": "Str0ng!Passw"}).status_code == 403
    assert client.delete(f"/api/admin/agents/{adm.username}", headers=hm).status_code == 403
    db.delete(adm); db.commit(); db.close()
