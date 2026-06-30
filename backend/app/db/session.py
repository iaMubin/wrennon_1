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

# check_same_thread=False is SQLite-specific: by default SQLite only
# allows the thread that created a connection to use it, which breaks
# under FastAPI's async request handling. This is safe here because
# SQLAlchemy's session handling still serializes access correctly.
_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=_connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a database session, always closed
    after the request finishes — even if the request raised an error."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
