"""
L2 node: human handoff. Triggered when the customer explicitly asks for
a human, or when a future node decides escalation is needed.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from app.graph.state import ConversationState
from app.services.llm import generate_conversation_summary
from app.services.mock_apis import create_support_ticket


def handoff_node(state: ConversationState) -> ConversationState:
    # Generate an LLM-based summary for the human agent
    conversation_summary = generate_conversation_summary(state["messages"])

    ticket = create_support_ticket(
        customer_email=state.get("customer_email") or "unknown@customer",
        conversation_summary=conversation_summary,
        order_id=state.get("order_id"),
    )

    state["handoff_ticket_id"] = ticket["ticket_id"]
    state["handoff_summary"] = conversation_summary
    state["handoff_requested"] = False
    state["conversation_mode"] = "bot"

    return state
