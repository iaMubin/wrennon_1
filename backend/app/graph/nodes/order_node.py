"""
L2 node: order status lookup. Calls get_order_status() — currently the
mock implementation, later a real Shopify call — and turns the result
into a customer-facing reply.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from app.graph.state import ConversationState
from app.services.mock_apis import get_order_status

ORDER_NOT_FOUND_MESSAGE = (
    "I couldn't find an order with that ID under this email address. "
    "Could you double check the order number?"
)


def order_node(state: ConversationState) -> ConversationState:
    order_id = state.get("order_id")
    customer_email = state.get("customer_email") or "unknown@customer"

    if not order_id:
        return state

    result = get_order_status(order_id=order_id, customer_email=customer_email)

    if result is None:
        state["order_status"] = None
        return state

    state["order_status"] = result
    return state


def _format_status_reply(status: dict) -> str:
    if status["status"] == "delivered":
        return f"Order #{status['order_id']} was delivered on {status['eta']}."
    if status["status"] == "shipped":
        return (
            f"Order #{status['order_id']} is on its way via {status['carrier']}, "
            f"expected by {status['eta']}. Track it here: {status['tracking_url']}"
        )
    return f"Order #{status['order_id']} is still being processed. Expected ship date: {status['eta']}."
