"""At-rest encryption of 2FA secrets, DB transport security, and automatic retention."""
import datetime
import uuid

import pyotp
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.auth.security import hash_password
from app.config import Settings, settings
from app.db.models import Agent, AuditLog, Conversation, Message, RevokedSession
from app.db.session import SessionLocal, build_connect_args
from app.main import app
from app.security import secrets_box, totp_store
from app.services.retention import purge_resolved_conversations

client = TestClient(app)
BASE = dict(groq_api_key="t", cohere_api_key="t", pinecone_api_key="t", pinecone_host="t", _env_file=None, agent_password_hash="h")
PROD = dict(app_env="production", jwt_secret_key="x" * 40, redis_url="redis://localhost:6379", cors_allowed_origins="https://e.com")


@pytest.fixture
def key(monkeypatch):
    k = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "tenant_secrets_key", k)
    return k


# ---------------- 2FA secrets at rest ----------------
def test_totp_secret_is_encrypted_and_roundtrips(key):
    a = Agent(username="u", full_name="u", employee_id="e", password_hash="x")
    totp_store.write_secret(a, "JBSWY3DPEHPK3PXP")
    assert a.totp_secret.startswith("enc:v1:") and "JBSWY3DPEHPK3PXP" not in a.totp_secret
    assert totp_store.read_secret(a) == "JBSWY3DPEHPK3PXP"


def test_legacy_plaintext_still_works_and_is_upgraded(key):
    a = Agent(username="u", full_name="u", employee_id="e", password_hash="x", totp_secret="JBSWY3DPEHPK3PXP")
    assert totp_store.read_secret(a) == "JBSWY3DPEHPK3PXP"
    assert totp_store.upgrade_if_plaintext(a) is True and totp_store.is_encrypted(a.totp_secret)
    assert totp_store.upgrade_if_plaintext(a) is False                     # idempotent
    assert totp_store.read_secret(a) == "JBSWY3DPEHPK3PXP"


def test_wrong_or_missing_key_fails_closed(key, monkeypatch):
    a = Agent(username="u", full_name="u", employee_id="e", password_hash="x")
    totp_store.write_secret(a, "JBSWY3DPEHPK3PXP")
    monkeypatch.setattr(settings, "tenant_secrets_key", Fernet.generate_key().decode())
    assert totp_store.read_secret(a) is None                               # cannot decrypt -> no second factor accepted
    monkeypatch.setattr(settings, "tenant_secrets_key", None)
    assert totp_store.read_secret(a) is None


def test_key_rotation_new_key_encrypts_old_key_still_decrypts(monkeypatch):
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "tenant_secrets_key", old)
    token = secrets_box.encrypt("hello")
    monkeypatch.setattr(settings, "tenant_secrets_key", f"{new},{old}")
    assert secrets_box.decrypt(token) == "hello"                           # old data readable during rotation
    monkeypatch.setattr(settings, "tenant_secrets_key", new)
    assert secrets_box.decrypt(secrets_box.encrypt("x")) == "x"
    with pytest.raises(secrets_box.SecretsUnavailable):
        secrets_box.decrypt(token)                                         # once the old key is dropped, old tokens are unreadable


def test_login_with_encrypted_and_legacy_secret(key):
    db = SessionLocal()
    plain = pyotp.random_base32()
    legacy = Agent(username=f"leg_{uuid.uuid4().hex[:6]}", full_name="L", employee_id=f"E-{uuid.uuid4().hex[:6]}",
                   password_hash=hash_password("Passw0rd!x"), role="agent", totp_secret=plain, totp_enabled=True)
    enc = Agent(username=f"enc_{uuid.uuid4().hex[:6]}", full_name="E", employee_id=f"E-{uuid.uuid4().hex[:6]}",
                password_hash=hash_password("Passw0rd!x"), role="agent", totp_enabled=True)
    totp_store.write_secret(enc, plain)
    db.add_all([legacy, enc]); db.commit()
    try:
        for ag in (legacy, enc):
            r = client.post("/api/agent/login", data={"username": ag.username, "password": "Passw0rd!x", "totp_code": pyotp.TOTP(plain).now()})
            assert r.status_code == 200, (ag.username, r.text)
        db.expire_all()
        assert totp_store.is_encrypted(db.get(Agent, legacy.id).totp_secret)   # upgraded on first successful 2FA login
    finally:
        for ag in (legacy, enc):
            db.query(AuditLog).filter_by(actor_username=ag.username).delete()
            db.query(Agent).filter_by(id=ag.id).delete()
        db.commit(); db.close()


# ---------------- DB transport security ----------------
def test_postgres_requires_tls_in_production_by_default():
    assert build_connect_args("postgresql://u:p@h/db", None, "production") == {"sslmode": "require"}
    assert build_connect_args("postgresql://u:p@h/db", "verify-full", "production") == {"sslmode": "verify-full"}
    assert build_connect_args("postgresql://u:p@h/db?sslmode=verify-ca", None, "production") == {}      # URL wins
    assert build_connect_args("postgresql://u:p@h/db", None, "development") == {}                        # dev: driver default
    assert build_connect_args("sqlite:///./x.db", None, "production") == {"check_same_thread": False}


def test_production_refuses_unencrypted_database_connection():
    for url, mode in (("postgresql://u:p@h/db?sslmode=disable", None), ("postgresql://u:p@h/db", "disable"), ("postgresql://u:p@h/db", "allow")):
        with pytest.raises(ValueError, match="TLS"):
            Settings(**BASE, **PROD, database_url=url, database_sslmode=mode)
    Settings(**BASE, **PROD, database_url="postgresql://u:p@h/db")                     # default is fine (require is applied)
    with pytest.raises(ValueError, match="DATABASE_SSLMODE"):
        Settings(**BASE, database_sslmode="bogus")


def test_retention_window_must_be_off_or_at_least_30_days():
    assert Settings(**BASE).conversation_retention_days == 0
    assert Settings(**BASE, conversation_retention_days=90).conversation_retention_days == 90
    for bad in (1, 7, 29, 4000):
        with pytest.raises(ValueError, match="CONVERSATION_RETENTION_DAYS"):
            Settings(**BASE, conversation_retention_days=bad)


# ---------------- automatic retention ----------------
def _conv(db, tag, *, resolved, age_days, handoff=False):
    when = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(days=age_days)
    c = Conversation(session_id=f"ret-{tag}-{resolved}-{age_days}-{handoff}", resolved=resolved, handoff_active=handoff, customer_email=f"{tag}@x.test")
    db.add(c); db.flush()
    c.updated_at = when
    db.add(Message(conversation_id=c.id, sender="human", content="my number is 01712345678"))
    db.commit()
    return c.session_id


def test_retention_deletes_only_old_resolved_conversations():
    tag = uuid.uuid4().hex[:6]
    with SessionLocal() as db:
        old = _conv(db, tag, resolved=True, age_days=200)
        recent = _conv(db, tag, resolved=True, age_days=5)
        open_old = _conv(db, tag, resolved=False, age_days=400)
        handoff_old = _conv(db, tag, resolved=True, age_days=400, handoff=True)
    assert purge_resolved_conversations(90, dry_run=True) >= 1                       # dry run reports ...
    with SessionLocal() as db:
        assert db.query(Conversation).filter_by(session_id=old).count() == 1         # ... but deletes nothing
    n = purge_resolved_conversations(90)
    assert n >= 1
    with SessionLocal() as db:
        left = {c.session_id for c in db.query(Conversation).filter(Conversation.session_id.like(f"ret-{tag}-%"))}
        assert left == {recent, open_old, handoff_old}
        assert db.query(Message).join(Conversation).filter(Conversation.session_id == old).count() == 0
        assert db.get(RevokedSession, old) is not None                               # the customer's token can't re-create it
        assert db.query(AuditLog).filter_by(action="retention_purge", actor_username="system:retention").count() >= 1
        for sid in (recent, open_old, handoff_old):
            c = db.query(Conversation).filter_by(session_id=sid).first()
            db.query(Message).filter_by(conversation_id=c.id).delete(); db.delete(c)
        db.query(RevokedSession).filter(RevokedSession.session_id.like(f"ret-{tag}-%")).delete(synchronize_session=False)
        db.query(AuditLog).filter_by(action="retention_purge").delete()
        db.commit()


def test_retention_refuses_a_dangerously_short_window():
    with pytest.raises(ValueError):
        purge_resolved_conversations(7)
