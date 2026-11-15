import io
import os
import time
import uuid

from fastapi.testclient import TestClient

from app.auth.security import create_access_token, hash_password
from app.db.models import Agent
from app.db.session import SessionLocal
from app.main import app
from app.services import ratelimit, uploads

client = TestClient(app)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _session():
    r = client.post("/api/chat/init").json()
    return r["session_id"], {"Authorization": f"Bearer {r['token']}"}


def _upload(sid, headers, data=PNG, name="a.png", ctype="image/png"):
    return client.post(f"/api/chat/upload/{sid}", headers=headers, files={"file": (name, io.BytesIO(data), ctype)})


def test_upload_returns_signed_url_and_serves_only_with_signature():
    sid, h = _session()
    r = _upload(sid, h)
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert f"/uploads/{sid}/" in url and "sig=" in url and "exp=" in url
    path = url.split("://", 1)[1].split("/", 1)[1]            # strip scheme+host
    assert client.get("/" + path).status_code == 200
    assert client.get("/" + path.split("?")[0]).status_code == 403          # no signature
    assert client.get("/" + path.replace("sig=", "sig=0")).status_code == 403  # tampered
    # expired signature
    key = path.split("?")[0].replace("uploads/", "", 1)
    exp = int(time.time()) - 5
    assert client.get(f"/uploads/{key}?exp={exp}&sig={uploads._sig(key, exp)}").status_code == 403


def test_signature_does_not_transfer_between_files():
    key_a = f"{uuid.uuid4().hex[:12]}/{uuid.uuid4().hex}.png"
    key_b = f"{uuid.uuid4().hex[:12]}/{uuid.uuid4().hex}.png"
    exp = int(time.time()) + 100
    assert uploads.verify_signature(key_a, str(exp), uploads._sig(key_a, exp))
    assert not uploads.verify_signature(key_b, str(exp), uploads._sig(key_a, exp))


def test_magic_bytes_must_match_extension():
    sid, h = _session()
    assert _upload(sid, h, data=b"<html><script>alert(1)</script>", name="x.png").status_code == 415
    assert _upload(sid, h, data=b"MZ\x90\x00", name="x.pdf", ctype="application/pdf").status_code == 415


def test_oversize_rejected():
    sid, h = _session()
    assert _upload(sid, h, data=PNG + b"0" * (uploads.MAX_FILE_SIZE + 10)).status_code == 413


def test_other_sessions_token_cannot_upload():
    sid, _ = _session()
    _, other = _session()
    assert _upload(sid, other).status_code == 401


def test_path_traversal_session_id_rejected():
    _, h = _session()
    assert client.post("/api/chat/upload/..%2f..%2fetc", headers=h, files={"file": ("a.png", PNG, "image/png")}).status_code in (400, 401, 404, 405)
    assert uploads.resolve_path("../x", "aaaaaaaa.png") is None
    assert uploads.resolve_path("abc", "../../etc/passwd") is None


def test_per_session_file_quota(monkeypatch):
    monkeypatch.setattr(uploads.settings, "upload_max_files_per_session", 2)
    sid, h = _session()
    assert _upload(sid, h).status_code == 200
    assert _upload(sid, h).status_code == 200
    assert _upload(sid, h).status_code == 429


def test_global_disk_cap(monkeypatch):
    monkeypatch.setattr(uploads.settings, "upload_max_total_bytes", 1)
    monkeypatch.setattr(uploads, "_disk_cache", (0.0, 0))
    sid, h = _session()
    assert _upload(sid, h).status_code == 429
    monkeypatch.setattr(uploads, "_disk_cache", (0.0, 0))


def test_revoked_agent_token_cannot_upload():
    db = SessionLocal()
    name = f"up_{uuid.uuid4().hex[:8]}"
    agent = Agent(username=name, full_name="U", employee_id=f"E-{uuid.uuid4().hex[:6]}", password_hash=hash_password("x"), role="agent")
    db.add(agent); db.commit()
    token = create_access_token(name, agent.token_version)
    sid = f"agent-up-{uuid.uuid4().hex[:8]}"
    h = {"Authorization": f"Bearer {token}"}
    assert _upload(sid, h).status_code == 200
    agent.token_version += 1; db.commit()                       # logout / password change
    assert _upload(sid, h).status_code == 401
    db.delete(agent); db.commit(); db.close()


def test_resign_text_refreshes_links():
    old = "see https://api.x.io/uploads/abc123def456/aaaaaaaaaaaa.png?exp=1&sig=dead and ![Image](/uploads/aaaaaaaaaaaa.png)"
    new = uploads.resign_text(old)
    assert "sig=dead" not in new and new.count("sig=") == 2 and "exp=1&" not in new


def test_llm_readers_only_open_own_session_files():
    assert uploads.resolve_own_upload("http://h/uploads/sessA/aaaaaaaaaaaa.png?exp=1&sig=x", "sessB") is None
    assert uploads.resolve_own_upload("http://evil/other.png", "sessA") is None
    assert uploads.resolve_own_upload("http://h/uploads/sessA/aaaaaaaaaaaa.png", "sessA").endswith(os.path.join("sessA", "aaaaaaaaaaaa.png"))


def test_purge_removes_old_files(tmp_path, monkeypatch):
    monkeypatch.setattr(uploads, "UPLOAD_DIR", str(tmp_path))
    d = tmp_path / "s1"; d.mkdir()
    old, new = d / "old00000000.png", d / "new00000000.png"
    old.write_bytes(b"x"); new.write_bytes(b"x")
    os.utime(old, (1, 1))
    assert uploads.purge_expired_uploads(30) == 1
    assert new.exists() and not old.exists()


def test_ratelimit_memory_fallback():
    import asyncio

    async def run():
        k = f"t:{uuid.uuid4()}"
        assert await ratelimit.hit(k, 60) == 1
        assert await ratelimit.hit(k, 60, 4) == 5

    asyncio.run(run())
