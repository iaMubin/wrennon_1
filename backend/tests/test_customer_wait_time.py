import datetime
import pytest
from unittest.mock import MagicMock
from app.api.agent import _calculate_customer_wait, _conversation_summary
from app.db.models import Conversation, Message

def test_calculate_customer_wait_resolved():
    c = Conversation(session_id="s_res", resolved=True)
    c.messages = [Message(sender="human", content="Hello", created_at=datetime.datetime.now(datetime.timezone.utc))]
    is_waiting, waiting_since, wait_mins = _calculate_customer_wait(c)
    assert is_waiting is False
    assert waiting_since is None
    assert wait_mins == 0

def test_calculate_customer_wait_no_messages():
    c = Conversation(session_id="s_empty", resolved=False)
    c.messages = []
    is_waiting, waiting_since, wait_mins = _calculate_customer_wait(c)
    assert is_waiting is False
    assert waiting_since is None
    assert wait_mins == 0

def test_calculate_customer_wait_waiting_human():
    now = datetime.datetime.now(datetime.timezone.utc)
    ten_mins_ago = now - datetime.timedelta(minutes=10)
    c = Conversation(session_id="s_wait", resolved=False, handoff_active=True)
    c.messages = [
        Message(sender="human", content="Where is my package?", created_at=ten_mins_ago)
    ]
    is_waiting, waiting_since, wait_mins = _calculate_customer_wait(c)
    assert is_waiting is True
    assert waiting_since is not None
    assert 9 <= wait_mins <= 11

def test_calculate_customer_wait_agent_already_replied():
    now = datetime.datetime.now(datetime.timezone.utc)
    ten_mins_ago = now - datetime.timedelta(minutes=10)
    five_mins_ago = now - datetime.timedelta(minutes=5)
    c = Conversation(session_id="s_replied", resolved=False, handoff_active=True)
    c.messages = [
        Message(sender="human", content="Where is my package?", created_at=ten_mins_ago),
        Message(sender="agent", content="Checking your order now!", created_at=five_mins_ago)
    ]
    is_waiting, waiting_since, wait_mins = _calculate_customer_wait(c)
    assert is_waiting is False
    assert waiting_since is None
    assert wait_mins == 0

def test_calculate_customer_wait_followup_after_agent_reply():
    now = datetime.datetime.now(datetime.timezone.utc)
    twenty_mins_ago = now - datetime.timedelta(minutes=20)
    fifteen_mins_ago = now - datetime.timedelta(minutes=15)
    two_mins_ago = now - datetime.timedelta(minutes=2)
    c = Conversation(session_id="s_followup", resolved=False, handoff_active=True)
    c.messages = [
        Message(sender="human", content="Where is my package?", created_at=twenty_mins_ago),
        Message(sender="agent", content="It was shipped yesterday.", created_at=fifteen_mins_ago),
        Message(sender="human", content="Can you provide the tracking link?", created_at=two_mins_ago)
    ]
    is_waiting, waiting_since, wait_mins = _calculate_customer_wait(c)
    assert is_waiting is True
    assert waiting_since is not None
    assert 1 <= wait_mins <= 3

def test_conversation_summary_includes_wait_fields():
    now = datetime.datetime.now(datetime.timezone.utc)
    six_mins_ago = now - datetime.timedelta(minutes=6)
    c = Conversation(
        session_id="s_summary",
        customer_email="test@example.com",
        resolved=False,
        handoff_active=True,
        updated_at=now
    )
    c.messages = [
        Message(sender="human", content="Help please", created_at=six_mins_ago)
    ]
    summary = _conversation_summary(c)
    assert "customer_waiting" in summary
    assert "waiting_since" in summary
    assert "wait_time_minutes" in summary
    assert summary["customer_waiting"] is True
    assert 5 <= summary["wait_time_minutes"] <= 7
