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
import json

MOCK_CUSTOMERS = [
    {
        "id": "CUST-1001",
        "name": "Eleanor Vance",
        "email": "eleanor.v@example.com",
        "phone": "+1-555-0198",
        "lifetime_value": "$195.00",
        "loyalty_tier": "Silver",
        "recent_order": "1001",
        "tags": [
            "New Customer"
        ]
    },
    {
        "id": "CUST-1002",
        "name": "Michael Chang",
        "email": "mchang.tech@example.com",
        "phone": "+1-555-0245",
        "lifetime_value": "$345.00",
        "loyalty_tier": "Silver",
        "recent_order": "1002",
        "tags": [
            "New Customer"
        ]
    },
    {
        "id": "CUST-1003",
        "name": "Sarah Jenkins",
        "email": "sjenkins88@example.com",
        "phone": "+1-555-0372",
        "lifetime_value": "$495.00",
        "loyalty_tier": "Silver",
        "recent_order": "1003",
        "tags": [
            "New Customer"
        ]
    },
    {
        "id": "CUST-1004",
        "name": "David Rodriguez",
        "email": "drodriguez@example.com",
        "phone": "+1-555-0411",
        "lifetime_value": "$645.00",
        "loyalty_tier": "Silver",
        "recent_order": "1004",
        "tags": [
            "New Customer"
        ]
    },
    {
        "id": "CUST-1005",
        "name": "Emily Chen",
        "email": "emily.c@example.com",
        "phone": "+1-555-0588",
        "lifetime_value": "$795.00",
        "loyalty_tier": "Silver",
        "recent_order": "1005",
        "tags": [
            "New Customer"
        ]
    },
    {
        "id": "CUST-1006",
        "name": "James Wilson",
        "email": "jwilson@example.com",
        "phone": "+1-555-0634",
        "lifetime_value": "$945.00",
        "loyalty_tier": "Gold",
        "recent_order": "1006",
        "tags": [
            "New Customer"
        ]
    },
    {
        "id": "CUST-1007",
        "name": "Olivia Martinez",
        "email": "omartinez99@example.com",
        "phone": "+1-555-0721",
        "lifetime_value": "$1095.00",
        "loyalty_tier": "Gold",
        "recent_order": "1007",
        "tags": [
            "New Customer"
        ]
    },
    {
        "id": "CUST-1008",
        "name": "William Taylor",
        "email": "wtaylor.biz@example.com",
        "phone": "+1-555-0899",
        "lifetime_value": "$1245.00",
        "loyalty_tier": "Gold",
        "recent_order": "1008",
        "tags": [
            "New Customer"
        ]
    },
    {
        "id": "CUST-1009",
        "name": "Sophia Anderson",
        "email": "sanderson@example.com",
        "phone": "+1-555-0956",
        "lifetime_value": "$1395.00",
        "loyalty_tier": "Gold",
        "recent_order": "1009",
        "tags": [
            "VIP"
        ]
    },
    {
        "id": "CUST-10010",
        "name": "Alexander Thomas",
        "email": "athomas.design@example.com",
        "phone": "+1-555-1042",
        "lifetime_value": "$1545.00",
        "loyalty_tier": "Gold",
        "recent_order": "1010",
        "tags": [
            "VIP"
        ]
    }
]


MOCK_ORDERS = {
    "1001": {
        "order_id": "1001",
        "email": "eleanor.v@example.com",
        "status": "delivered",
        "order_date": "2026-08-01",
        "total_amount": "$101.50",
        "payment_method": "Credit Card (Visa)",
        "shipping_method": "Express Shipping",
        "carrier": "FedEx",
        "eta": None,
        "tracking_url": "https://fedex.com/track/1001",
        "timeline": [
            {
                "status": "placed",
                "time": "2026-08-01T10:15:00Z",
                "label": "Order Placed"
            },
            {
                "status": "processing",
                "time": "2026-08-01T14:30:00Z",
                "label": "Processing"
            },
            {
                "status": "shipped",
                "time": "2026-08-02T09:45:00Z",
                "label": "Shipped"
            },
            {
                "status": "delivered",
                "time": "2026-08-03T16:20:00Z",
                "label": "Delivered"
            }
        ]
    },
    "1002": {
        "order_id": "1002",
        "email": "mchang.tech@example.com",
        "status": "shipped",
        "order_date": "2026-08-02",
        "total_amount": "$190.50",
        "payment_method": "PayPal",
        "shipping_method": "Standard Delivery",
        "carrier": "FedEx",
        "eta": "2026-08-05",
        "tracking_url": "https://fedex.com/track/1002",
        "timeline": [
            {
                "status": "placed",
                "time": "2026-08-02T10:15:00Z",
                "label": "Order Placed"
            },
            {
                "status": "processing",
                "time": "2026-08-02T14:30:00Z",
                "label": "Processing"
            },
            {
                "status": "shipped",
                "time": "2026-08-03T09:45:00Z",
                "label": "Shipped"
            }
        ]
    },
    "1003": {
        "order_id": "1003",
        "email": "sjenkins88@example.com",
        "status": "processing",
        "order_date": "2026-08-03",
        "total_amount": "$279.50",
        "payment_method": "Credit Card (Visa)",
        "shipping_method": "Express Shipping",
        "carrier": None,
        "eta": "2026-08-06",
        "tracking_url": None,
        "timeline": [
            {
                "status": "placed",
                "time": "2026-08-03T10:15:00Z",
                "label": "Order Placed"
            },
            {
                "status": "processing",
                "time": "2026-08-03T14:30:00Z",
                "label": "Processing"
            }
        ]
    },
    "1004": {
        "order_id": "1004",
        "email": "drodriguez@example.com",
        "status": "placed",
        "order_date": "2026-08-04",
        "total_amount": "$368.50",
        "payment_method": "PayPal",
        "shipping_method": "Standard Delivery",
        "carrier": None,
        "eta": "2026-08-07",
        "tracking_url": None,
        "timeline": [
            {
                "status": "placed",
                "time": "2026-08-04T10:15:00Z",
                "label": "Order Placed"
            }
        ]
    },
    "1005": {
        "order_id": "1005",
        "email": "emily.c@example.com",
        "status": "cancelled",
        "order_date": "2026-08-05",
        "total_amount": "$457.50",
        "payment_method": "Credit Card (Visa)",
        "shipping_method": "Express Shipping",
        "carrier": None,
        "eta": None,
        "tracking_url": None,
        "timeline": [
            {
                "status": "placed",
                "time": "2026-08-05T10:15:00Z",
                "label": "Order Placed"
            },
            {
                "status": "cancelled",
                "time": "2026-08-05T18:05:00Z",
                "label": "Cancelled"
            }
        ]
    },
    "1006": {
        "order_id": "1006",
        "email": "jwilson@example.com",
        "status": "delivered",
        "order_date": "2026-08-06",
        "total_amount": "$546.50",
        "payment_method": "PayPal",
        "shipping_method": "Standard Delivery",
        "carrier": "FedEx",
        "eta": None,
        "tracking_url": "https://fedex.com/track/1006",
        "timeline": [
            {
                "status": "placed",
                "time": "2026-08-06T10:15:00Z",
                "label": "Order Placed"
            },
            {
                "status": "processing",
                "time": "2026-08-06T14:30:00Z",
                "label": "Processing"
            },
            {
                "status": "shipped",
                "time": "2026-08-07T09:45:00Z",
                "label": "Shipped"
            },
            {
                "status": "delivered",
                "time": "2026-08-08T16:20:00Z",
                "label": "Delivered"
            }
        ]
    },
    "1007": {
        "order_id": "1007",
        "email": "omartinez99@example.com",
        "status": "shipped",
        "order_date": "2026-08-07",
        "total_amount": "$635.50",
        "payment_method": "Credit Card (Visa)",
        "shipping_method": "Express Shipping",
        "carrier": "FedEx",
        "eta": "2026-08-10",
        "tracking_url": "https://fedex.com/track/1007",
        "timeline": [
            {
                "status": "placed",
                "time": "2026-08-07T10:15:00Z",
                "label": "Order Placed"
            },
            {
                "status": "processing",
                "time": "2026-08-07T14:30:00Z",
                "label": "Processing"
            },
            {
                "status": "shipped",
                "time": "2026-08-08T09:45:00Z",
                "label": "Shipped"
            }
        ]
    },
    "1008": {
        "order_id": "1008",
        "email": "wtaylor.biz@example.com",
        "status": "processing",
        "order_date": "2026-08-08",
        "total_amount": "$724.50",
        "payment_method": "PayPal",
        "shipping_method": "Standard Delivery",
        "carrier": None,
        "eta": "2026-08-11",
        "tracking_url": None,
        "timeline": [
            {
                "status": "placed",
                "time": "2026-08-08T10:15:00Z",
                "label": "Order Placed"
            },
            {
                "status": "processing",
                "time": "2026-08-08T14:30:00Z",
                "label": "Processing"
            }
        ]
    },
    "1009": {
        "order_id": "1009",
        "email": "sanderson@example.com",
        "status": "placed",
        "order_date": "2026-08-09",
        "total_amount": "$813.50",
        "payment_method": "Credit Card (Visa)",
        "shipping_method": "Express Shipping",
        "carrier": None,
        "eta": "2026-08-12",
        "tracking_url": None,
        "timeline": [
            {
                "status": "placed",
                "time": "2026-08-09T10:15:00Z",
                "label": "Order Placed"
            }
        ]
    },
    "1010": {
        "order_id": "1010",
        "email": "athomas.design@example.com",
        "status": "cancelled",
        "order_date": "2026-08-10",
        "total_amount": "$902.50",
        "payment_method": "PayPal",
        "shipping_method": "Standard Delivery",
        "carrier": None,
        "eta": None,
        "tracking_url": None,
        "timeline": [
            {
                "status": "placed",
                "time": "2026-08-10T10:15:00Z",
                "label": "Order Placed"
            },
            {
                "status": "cancelled",
                "time": "2026-08-10T18:05:00Z",
                "label": "Cancelled"
            }
        ]
    }
}


def get_customer_info(email: str = None, phone: str = None, customer_id: str = None) -> Optional[dict]:
    if email:
        email_lower = email.lower().strip()
        for c in MOCK_CUSTOMERS:
            if c["email"].lower() == email_lower:
                return c
    
    if phone:
        for c in MOCK_CUSTOMERS:
            if c["phone"] == phone:
                return c
                
    if customer_id:
        for c in MOCK_CUSTOMERS:
            if c["id"].lower() == customer_id.lower().strip():
                return c
                
    return None

def get_order_status(order_id: str) -> Optional[dict]:
    """Look up the current status of an order.
    Simulates:
    GET /admin/api/2024-01/orders/{order_id}.json
    
    Args:
        order_id: The e-commerce order ID (e.g. 1001)
        
    Returns:
        A dictionary containing order status, items, shipping,
        or None if no matching order is found.
    """
    # --- MOCK BODY ---
    order = MOCK_ORDERS.get(order_id)
    if order:
        result = order.copy()
        return result
    return None

def get_order_by_email(email: str) -> Optional[dict]:
    """Look up the most recent order by customer email.
    Simulates:
    GET /admin/api/2024-01/orders.json?email={email}&limit=1
    
    Args:
        email: The customer's email address
        
    Returns:
        A dictionary containing order status, or None if no match.
    """
    # --- MOCK BODY ---
    if not email:
        return None
    email_lower = email.lower().strip()
    matches = [
        order for order in MOCK_ORDERS.values()
        if order.get("email", "").lower() == email_lower
    ]
    if not matches:
        return None
    # Return the latest (highest order_id)
    latest = max(matches, key=lambda x: x["order_id"])
    result = latest.copy()
    if "email" in result:
        del result["email"]
    return result

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
        "created_at": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat(),
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
        "reopened_at": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat(),
    }


# NOTE: process_refund / update_subscription / recommend_product /
# track_purchase used to be defined here too, but nothing ever imported
# them from this module (grepped to confirm) — the graph's tool_executor
# calls the equivalent methods on MockEcommerceProvider in
# app/services/integrations/mock_provider.py instead, which is the real,
# actively-maintained catalog. Removed the dead duplicates here rather
# than let two divergent copies of "the product catalog" rot out of sync.
