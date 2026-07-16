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
    "id": "CUST-089",
    "name": "Alex Rivera",
    "email": "customer1@example.com",
    "phone": "555-0198",
    "lifetime_value": "$1,240.50",
    "loyalty_tier": "Gold",
    "recent_order": "1001",
    "tags": ["Frequent Buyer", "Tech Gadgets"]
  },
  {
    "id": "CUST-102",
    "name": "Sam Chen",
    "email": "demo@example.com",
    "phone": "555-0211",
    "lifetime_value": "$450.00",
    "loyalty_tier": "Silver",
    "recent_order": "1002",
    "tags": ["New Customer"]
  },
  {
    "id": "CUST-103",
    "name": "Jordan Lee",
    "email": "customer3@example.com",
    "phone": "555-0311",
    "lifetime_value": "$890.00",
    "loyalty_tier": "Silver",
    "recent_order": "1003",
    "tags": ["Apparel"]
  },
  {
    "id": "CUST-106",
    "name": "Casey Smith",
    "email": "customer6@example.com",
    "phone": "555-0611",
    "lifetime_value": "$210.00",
    "loyalty_tier": "Bronze",
    "recent_order": "1006",
    "tags": []
  },
  {
    "id": "CUST-107",
    "name": "Taylor Swift",
    "email": "customer7@example.com",
    "phone": "555-0711",
    "lifetime_value": "$5,450.00",
    "loyalty_tier": "Platinum",
    "recent_order": "1007",
    "tags": ["VIP"]
  },
  {
    "id": "CUST-999",
    "name": "Test User",
    "email": "test@example.com",
    "phone": "555-9999",
    "lifetime_value": "$150.00",
    "loyalty_tier": "Bronze",
    "recent_order": "1005",
    "tags": ["Test"]
  }
]

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


from typing import Optional


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
    mock_orders = {
        "1001": {
            "order_id": "1001",
            "email": "customer1@example.com",
            "status": "shipped",
            "carrier": "Pathao Courier",
            "eta": "2026-06-27",
            "tracking_url": "https://example.com/track/1001",
        },
        "1002": {
            "order_id": "1002",
            "email": "test@example.com",
            "status": "processing",
            "carrier": None,
            "eta": "2026-06-30",
            "tracking_url": None,
        },
        "1003": {
            "order_id": "1003",
            "email": "customer3@example.com",
            "status": "delivered",
            "carrier": "Sundarban Courier",
            "eta": "2026-06-20",
            "tracking_url": "https://example.com/track/1003",
        },
        "1004": {
            "order_id": "1004",
            "email": "test@example.com",
            "status": "cancelled",
            "carrier": None,
            "eta": None,
            "tracking_url": None,
        },
        "1005": {
            "order_id": "1005",
            "email": "test@example.com",
            "status": "processing",
            "carrier": None,
            "eta": "2026-07-15",
            "tracking_url": None,
        },
        "1006": {
            "order_id": "1006",
            "email": "customer6@example.com",
            "status": "shipped",
            "carrier": "DHL",
            "eta": "2026-07-08",
            "tracking_url": "https://dhl.com/track/1006",
        },
        "1007": {
            "order_id": "1007",
            "email": "customer7@example.com",
            "status": "delivered",
            "carrier": "FedEx",
            "eta": "2026-06-05",
            "tracking_url": "https://fedex.com/track/1007",
        },
    }
    
    order = mock_orders.get(order_id)
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
    mock_orders = {
        "1001": {"order_id": "1001", "email": "customer1@example.com", "status": "shipped", "carrier": "Pathao Courier", "eta": "2026-06-27", "tracking_url": "https://example.com/track/1001"},
        "1002": {"order_id": "1002", "email": "test@example.com", "status": "processing", "carrier": None, "eta": "2026-06-30", "tracking_url": None},
        "1003": {"order_id": "1003", "email": "customer3@example.com", "status": "delivered", "carrier": "Sundarban Courier", "eta": "2026-06-20", "tracking_url": "https://example.com/track/1003"},
        "1004": {"order_id": "1004", "email": "test@example.com", "status": "cancelled", "carrier": None, "eta": None, "tracking_url": None},
        "1005": {"order_id": "1005", "email": "test@example.com", "status": "processing", "carrier": None, "eta": "2026-07-15", "tracking_url": None},
        "1006": {"order_id": "1006", "email": "customer6@example.com", "status": "shipped", "carrier": "DHL", "eta": "2026-07-08", "tracking_url": "https://dhl.com/track/1006"},
        "1007": {"order_id": "1007", "email": "customer7@example.com", "status": "delivered", "carrier": "FedEx", "eta": "2026-06-05", "tracking_url": "https://fedex.com/track/1007"},
    }
    
    if not email:
        return None
    email_lower = email.lower().strip()
    matches = [
        order for order in mock_orders.values()
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
    mock_orders = {
        "1001": {"order_id": "1001", "email": "customer1@example.com", "status": "shipped", "carrier": "Pathao Courier", "eta": "2026-06-27", "tracking_url": "https://example.com/track/1001"},
        "1002": {"order_id": "1002", "email": "test@example.com", "status": "processing", "carrier": None, "eta": "2026-06-30", "tracking_url": None},
        "1003": {"order_id": "1003", "email": "customer3@example.com", "status": "delivered", "carrier": "Sundarban Courier", "eta": "2026-06-20", "tracking_url": "https://example.com/track/1003"},
        "1004": {"order_id": "1004", "email": "test@example.com", "status": "cancelled", "carrier": None, "eta": None, "tracking_url": None},
        "1005": {"order_id": "1005", "email": "test@example.com", "status": "processing", "carrier": None, "eta": "2026-07-15", "tracking_url": None},
        "1006": {"order_id": "1006", "email": "customer6@example.com", "status": "shipped", "carrier": "DHL", "eta": "2026-07-08", "tracking_url": "https://dhl.com/track/1006"},
        "1007": {"order_id": "1007", "email": "customer7@example.com", "status": "delivered", "carrier": "FedEx", "eta": "2026-06-05", "tracking_url": "https://fedex.com/track/1007"},
    }
    
    if not email:
        return None
    email_lower = email.lower().strip()
    matches = [
        order for order in mock_orders.values()
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


def process_refund(order_id: str, amount: float) -> dict:
    """Process a refund for a given order (L4 Pipeline).
    
    Returns:
        dict: Refund status
    """
    # --- MOCK BODY ---
    import datetime
    import uuid
    return {
        "refund_id": f"REF-{uuid.uuid4().hex[:6].upper()}",
        "order_id": order_id,
        "amount_refunded": amount,
        "status": "approved",
        "processed_at": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()
    }


def update_subscription(customer_email: str, action: str) -> dict:
    """Update a customer's subscription (L3 Pipeline).
    
    Args:
        action: 'skip', 'cancel', or 'resume'
        
    Returns:
        dict: New subscription status
    """
    # --- MOCK BODY ---
    import datetime
    
    status_map = {
        "skip": "skipped_next_delivery",
        "cancel": "cancelled",
        "resume": "active"
    }
    
    return {
        "email": customer_email,
        "subscription_status": status_map.get(action, "unknown"),
        "updated_at": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()
    }


def recommend_product(context_keywords: str) -> list[dict]:
    """Act as a shopping assistant and recommend a product.
    
    Args:
        context_keywords: Search terms or context
        
    Returns:
        List of recommended products.
    """
    # --- MOCK BODY ---
    return [
        {
            "product_id": "PROD-X2",
            "name": "Premium Plan Upgrade",
            "price": 29.99,
            "description": "Upgrade to our premium tier for faster shipping and exclusive content.",
            "link": "https://example.com/upgrade/PROD-X2"
        },
        {
            "product_id": "PROD-Y1",
            "name": "Limited Edition Merch",
            "price": 15.00,
            "description": "Show your support with our limited edition merch.",
            "link": "https://example.com/merch/PROD-Y1"
        }
    ]


def track_purchase(product_id: str) -> dict:
    """Simulate the customer buying a recommended product to track revenue.
    
    Returns:
        dict: Revenue details
    """
    # --- MOCK BODY ---
    price_map = {
        "PROD-X2": 29.99,
        "PROD-Y1": 15.00
    }
    return {
        "success": True,
        "product_id": product_id,
        "revenue_generated": price_map.get(product_id, 10.00)
    }
