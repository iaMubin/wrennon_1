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

    # --- Ticket properties (agent-facing triage metadata) ---
    # priority: "low" | "normal" | "high" | "urgent" — agent-set, drives
    # the priority badge in the dashboard. Distinct from `sentiment`
    # (AI-inferred) and `handoff_active`/`resolved` (workflow state).
    priority: Mapped[str] = mapped_column(String, default="normal", server_default="normal")
    # tags: JSON-encoded list of strings, e.g. '["vip","refund-dispute"]'.
    # Stored as Text rather than a separate table — ticket tags here are
    # simple labels, not a shared/managed taxonomy. Always read via
    # json.loads with a [] fallback.
    tags: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    # assigned_agent: the *owning* agent's username, distinct from
    # `handled_by` (set automatically on resolve) — this is an explicit,
    # agent-facing "who owns this ticket" assignment editable at any time,
    # independent of resolution state.
    assigned_agent: Mapped[str | None] = mapped_column(String, nullable=True)
    merged_into_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", order_by="Message.created_at"
    )
    csat_response: Mapped["CSATResponse | None"] = relationship(viewonly=True, uselist=False)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)

    # "human" = customer typed this. "ai" = bot generated this.
    # "agent" = a human support agent typed this. Kept distinct in storage.
    sender: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    author_username: Mapped[str | None] = mapped_column(String, nullable=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)

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
    dp_url: Mapped[str | None] = mapped_column(String, nullable=True)
    totp_secret: Mapped[str | None] = mapped_column(String, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    permissions: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    # Bumped whenever the password changes (or the account needs its
    # sessions force-revoked). The JWT carries the token_version that was
    # current when it was issued ("tv" claim); get_current_agent rejects
    # any token whose "tv" doesn't match the current value. Replaces an
    # earlier approach that embedded a fragment of the password hash
    # itself into the JWT payload — JWTs are signed, not encrypted, so
    # that fragment was readable by anyone holding the token. A plain
    # counter carries no information about the password at all.

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    )

    def has_permission(self, permission_name: str) -> bool:
        if self.role == "admin":
            return True
            
        import json
        try:
            perms = json.loads(self.permissions)
        except:
            perms = []
            
        if not perms:
            # Fallback for backwards compatibility with existing rows that haven't been updated
            if self.role == "manager":
                perms = ["manage_agents", "view_analytics", "manage_canned_responses"]
            else:
                perms = []
                
        return permission_name in perms


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


class KnowledgeGap(Base):
    __tablename__ = "knowledge_gaps"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    draft_article: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending, approved, rejected

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    )


class AnalyticsScorecard(Base):
    __tablename__ = "analytics_scorecards"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), unique=True)
    empathy_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accuracy_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolution_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    csat_prediction: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    )


class CSATResponse(Base):
    __tablename__ = "csat_responses"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    # unique: one real customer rating per conversation — this is the actual
    # submitted score, distinct from AnalyticsScorecard.csat_prediction
    # (an internal AI guess used for QA before the customer ever responds).
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), unique=True)
    rating: Mapped[int] = mapped_column(Integer)  # 1-5
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    )


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    key: Mapped[str] = mapped_column(String, unique=True, index=True)
    value: Mapped[str] = mapped_column(Text)

    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    )

class CannedResponse(Base):
    __tablename__ = "canned_responses"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    shortcut: Mapped[str] = mapped_column(String, unique=True)  # e.g., "/refund"
    title: Mapped[str] = mapped_column(String)                  # Dropdown description
    body: Mapped[str] = mapped_column(Text)                     # Actual text inserted
    created_by: Mapped[str] = mapped_column(String)             # Username of the creator
    
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    )

class SavedView(Base):
    __tablename__ = "saved_views"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    agent_username: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    filter_json: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    )
