"""What a customer is allowed to learn about the human agent they're talking to."""
from __future__ import annotations


def public_agent_name(full_name: str | None) -> str | None:
    """First name only. Customers see "Sara", not an employee's full legal name
    (data minimisation); None falls back to the widget's generic "Support Agent"."""
    parts = (full_name or "").split()
    return parts[0][:30] if parts else None
