"""
Database engine and session setup.

SQLite for now (a single file, zero extra setup — matches Mubin's
choice for this build phase). Moving to PostgreSQL later means changing
DATABASE_URL in .env and this file's connect_args line — the rest of
the codebase (models.py, every route that uses get_db) does not change,
because SQLAlchemy's ORM abstracts the actual database engine away.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.tenancy import TenantSession

# check_same_thread=False is SQLite-specific: by default SQLite only
# allows the thread that created a connection to use it, which breaks
# under FastAPI's async request handling. This is safe here because
# SQLAlchemy's session handling still serializes access correctly.
def build_connect_args(url: str, sslmode: str | None, app_env: str) -> dict:
    """Driver arguments for the database connection.

    Postgres: TLS is requested explicitly (``require`` in production) unless the URL already carries its own
    ``sslmode``. Without this, psycopg2 defaults to ``prefer``, which silently falls back to an UNENCRYPTED
    connection, so a misconfigured server or a network attacker downgrades it with no error. The conversation
    text, emails, phones and addresses in this database must not cross the network in clear."""
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    if "sslmode=" in url:
        return {}
    mode = sslmode or ("require" if app_env == "production" else None)
    return {"sslmode": mode} if mode else {}


_connect_args = build_connect_args(settings.database_url, settings.database_sslmode, settings.app_env)

# pool_pre_ping: transparently replace connections the server/proxy has dropped (idle timeouts on PaaS
# Postgres otherwise surface as random 500s).
engine = create_engine(settings.database_url, connect_args=_connect_args,
                       pool_pre_ping=not settings.database_url.startswith("sqlite"))

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=TenantSession)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a database session, always closed
    after the request finishes — even if the request raised an error."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
