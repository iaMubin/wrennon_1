"""
L2 node: human handoff. Triggered when the customer explicitly asks for
a human, or when a future node decides escalation is needed.
If the conversation had a previous ticket, that ticket is reopened
instead of creating a new one.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from app.graph.state import ConversationState
from app.services.llm import generate_conversation_summary
from app.services.mock_apis import create_support_ticket, reopen_support_ticket


async def handoff_node(state: ConversationState) -> ConversationState:
    # Generate an LLM-based summary for the human agent
    conversation_summary = await generate_conversation_summary(state["messages"])

    existing_ticket_id = state.get("existing_ticket_id")

    if existing_ticket_id:
        # Reopen the previous ticket instead of creating a new one
        ticket = reopen_support_ticket(
            ticket_id=existing_ticket_id,
            conversation_summary=conversation_summary,
        )
    else:
        # Create a brand new ticket
        ticket = create_support_ticket(
            customer_email=state.get("customer_email") or "unknown@customer",
            conversation_summary=conversation_summary,
            order_id=state.get("order_id"),
        )

    state["handoff_ticket_id"] = ticket["ticket_id"]
    state["handoff_summary"] = conversation_summary
    state["conversation_mode"] = "pending_human"

    return state
