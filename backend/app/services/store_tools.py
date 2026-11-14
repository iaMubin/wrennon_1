"""Chatbot tool for signed-in storefront customers: "show me my orders"."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

from app.services.integrations import get_ecommerce_provider


async def execute_get_my_orders(args: Dict[str, Any]) -> str:
    # _customer_email is injected by tool_executor from the signed chat-session token; the LLM cannot supply or forge it.
    email = args.get("_customer_email")
    if not email:
        return ("The customer is not signed in, so you cannot list their orders. Ask them to sign in on the store, "
                "or to give an order number together with the email used at checkout.")
    lister = getattr(get_ecommerce_provider(), "list_orders", None)
    if lister is None:
        return "Listing past orders is not available on this store connection."
    orders = await asyncio.to_thread(lister, email, 5)
    if not orders:
        return "This customer has no orders yet."
    compact = [{
        "order_id": o["order_id"], "status": o["status"], "order_date": o["order_date"], "total": o["total_amount"],
        "items": [f"{i['name']} ({i['size']}) x{i['quantity']}" for i in o.get("items", [])],
        "carrier": o.get("carrier"), "tracking_number": o.get("tracking_number"), "eta": o.get("eta"),
    } for o in orders]
    return "Recent orders for the signed-in customer (newest first): " + json.dumps(compact)
