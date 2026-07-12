"""
L2 node: human handoff. Triggered when the manager decides escalation
is genuinely needed (explicit request, tools couldn't finish the job,
or persistent frustration — see manager_node.py's reasoning, not
keyword rules).

If the conversation had a previous ticket, that ticket is reopened
instead of creating a new one.
"""

from __future__ import annotations

from app.graph.state import ConversationState
from app.services.integrations import get_crm_provider

from app.services.llm import generate_conversation_summary

crm = get_crm_provider()


async def handoff_node(state: ConversationState) -> ConversationState:
    # Generate an LLM-based summary for the human agent, now informed by
    # *why* the manager escalated (not just the raw transcript) — this
    # makes the agent-facing note much more actionable.
    conversation_summary = await generate_conversation_summary(
        state["messages"],
        escalation_reason=state.get("handoff_reason"),
    )

    existing_ticket_id = state.get("existing_ticket_id")

    if existing_ticket_id:
        ticket = crm.reopen_support_ticket(
            ticket_id=existing_ticket_id,
            conversation_summary=conversation_summary,
        )
    else:
        ticket = crm.create_support_ticket(
            customer_email=state.get("customer_email") or "unknown@customer",
            conversation_summary=conversation_summary,
            order_id=state.get("order_id"),
        )

    state["handoff_ticket_id"] = ticket["ticket_id"]
    state["handoff_summary"] = conversation_summary
    state["conversation_mode"] = "pending_human"

    if not state.get("resolution_logged"):
        from app.services.analytics import log_resolution
        log_resolution(
            was_autonomous=False,
            intent=state.get("intent_category"),
            sentiment=state.get("sentiment")
        )
        state["resolution_logged"] = True

    return state
