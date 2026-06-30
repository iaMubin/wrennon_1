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

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _new_uuid() -> str:
    return str(uuid.uuid4())


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    session_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    customer_email: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- Handoff / resolution tracking ---
    # handoff_active: True the moment the AI escalates. Stays True until
    # an agent explicitly resolves it — this is the field that decides
    # whether the conversation shows up in the agent widget's "needs
    # attention" section (see Mubin's decision: stays there until agent
    # marks resolved, NOT until agent just replies once).
    handoff_active: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    handoff_ticket_id: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)

    # "human" = customer typed this. "ai" = bot generated this.
    # "agent" = a human support agent typed this. Kept distinct in storage
    # even though the customer-facing widget deliberately does not show
    # this distinction (per Mubin's design decision — the customer
    # should never be able to tell whether AI or a human is replying).
    sender: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
