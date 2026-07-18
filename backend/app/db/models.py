"""
Database models for persistent conversation storage.

Replaces the in-memory SESSION_STORE (app/api/chat.py) with real,
durable storage. Two tables:

- Conversation: one row per chat session. Tracks handoff/resolved state.
- Message: one row per message, linked to a conversation.

Using SQLAlchemy's ORM (not raw SQL) means the eventual move from
SQLite to PostgreSQL is mostly a one-line change in db/session.py —
these model definitions don't need to change.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _generate_short_id() -> str:
    return f"CUST-{uuid.uuid4().hex[:6].upper()}"


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    session_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    customer_email: Mapped[str | None] = mapped_column(String, nullable=True)
    short_id: Mapped[str] = mapped_column(String, default=_generate_short_id)

    # --- Handoff / resolution tracking ---
    # handoff_active: True the moment the AI escalates. Stays True until
    # an agent explicitly resolves it — this is the field that decides
    # whether the conversation shows up in the agent widget's "needs
    # attention" section (see Mubin's decision: stays there until agent
    # marks resolved, NOT until agent just replies once).
    handoff_active: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    reopen_count: Mapped[int] = mapped_column(Integer, default=0)
    handled_by: Mapped[str | None] = mapped_column(String, nullable=True)
    handoff_ticket_id: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String, nullable=True)
    intent_category: Mapped[str | None] = mapped_column(String, nullable=True)
    language: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    )

    # --- Conversation State ---
    active_topic: Mapped[str | None] = mapped_column(String, nullable=True)
    last_order_id: Mapped[str | None] = mapped_column(String, nullable=True)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    pinned_message_id: Mapped[str | None] = mapped_column(String, nullable=True)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)

    # "human" = customer typed this. "ai" = bot generated this.
    # "agent" = a human support agent typed this. Kept distinct in storage.
    sender: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    author_username: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    employee_id: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)
    full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default="agent")
    totp_secret: Mapped[str | None] = mapped_column(String, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    actor_username: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String)  # e.g., "login", "create_agent", "delete_agent", "reset_password"
    target_username: Mapped[str | None] = mapped_column(String, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None), index=True
    )
