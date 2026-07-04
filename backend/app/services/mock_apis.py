"""
Mock implementations of external API calls used by the L2 nodes.

Pattern: every function here keeps the exact name and return shape that
the real integration will use later. The body is the only thing that
changes when a real API is wired in — callers in the graph nodes never
need to change.

When upgrading to a real integration, replace the body of each function
below the `--- MOCK BODY ---` marker. Leave the signature and the
docstring's "Returns" shape untouched, or downstream nodes will break.
"""

from __future__ import annotations

from typing import Optional


def get_order_status(order_id: str, customer_email: str) -> Optional[dict]:
    """Look up the current status of an order.

    Real integration target: Shopify REST Admin API
    GET /admin/api/2024-01/orders/{order_id}.json
    (filtered/validated against customer_email before returning)

    Returns:
        dict shaped like:
        {
            "order_id": str,
            "status": "processing" | "shipped" | "delivered" | "cancelled",
            "carrier": str,
            "eta": str,          # ISO date
            "tracking_url": str,
        }
        or None if no matching order is found for that email.
    """
    # --- MOCK BODY ---
    mock_orders = {
        "1001": {
            "order_id": "1001",
            "status": "shipped",
            "carrier": "Pathao Courier",
            "eta": "2026-06-27",
            "tracking_url": "https://example.com/track/1001",
        },
        "1002": {
            "order_id": "1002",
            "status": "processing",
            "carrier": None,
            "eta": "2026-06-30",
            "tracking_url": None,
        },
        "1003": {
            "order_id": "1003",
            "status": "delivered",
            "carrier": "Sundarban Courier",
            "eta": "2026-06-20",
            "tracking_url": "https://example.com/track/1003",
        },
        "1004": {
            "order_id": "1004",
            "status": "cancelled",
            "carrier": None,
            "eta": None,
            "tracking_url": None,
        },
        "1005": {
            "order_id": "1005",
            "status": "processing",
            "carrier": None,
            "eta": "2026-07-15",
            "tracking_url": None,
        },
        "1006": {
            "order_id": "1006",
            "status": "shipped",
            "carrier": "DHL",
            "eta": "2026-07-08",
            "tracking_url": "https://dhl.com/track/1006",
        },
        "1007": {
            "order_id": "1007",
            "status": "delivered",
            "carrier": "FedEx",
            "eta": "2026-06-05",
            "tracking_url": "https://fedex.com/track/1007",
        },
    }
    return mock_orders.get(order_id)


def create_support_ticket(
    customer_email: str,
    conversation_summary: str,
    order_id: Optional[str] = None,
) -> dict:
    """Create a human-handoff ticket once the agent decides to escalate.

    Real integration target: Gorgias or Zendesk API
    POST /api/tickets

    Returns:
        dict shaped like:
        {
            "ticket_id": str,
            "status": "open",
            "created_at": str,   # ISO timestamp
        }
    """
    # --- MOCK BODY ---
    import datetime
    import uuid

    return {
        "ticket_id": f"TICKET-{uuid.uuid4().hex[:8].upper()}",
        "status": "open",
        "created_at": datetime.datetime.utcnow().isoformat(),
    }


def reopen_support_ticket(
    ticket_id: str,
    conversation_summary: str,
) -> dict:
    """Reopen a previously resolved ticket.

    Real integration target: Gorgias or Zendesk API
    PUT /api/tickets/{ticket_id}/reopen

    Returns:
        dict shaped like:
        {
            "ticket_id": str,
            "status": "reopened",
            "reopened_at": str,   # ISO timestamp
        }
    """
    # --- MOCK BODY ---
    import datetime

    return {
        "ticket_id": ticket_id,  # Same ticket ID — not a new one
        "status": "reopened",
        "reopened_at": datetime.datetime.utcnow().isoformat(),
    }
