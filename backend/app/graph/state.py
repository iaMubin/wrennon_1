"""
Conversation state schema for the Wrennon showcase agent.

This is the single source of truth that flows through every node in the
LangGraph graph. Fields are grouped by the architecture level that
introduces them. L1/L2 fields are active in this phase of the build.
L3/L4 fields are declared now so the schema does not need to change shape
when those levels are added later — only new nodes get written.
"""

from __future__ import annotations

from typing import Literal, Optional, TypedDict

from langchain_core.messages import BaseMessage


class ConversationState(TypedDict):
    # --- Core conversation state (used from L1 onward) ---
    messages: list[BaseMessage]
    customer_email: Optional[str]
    current_intent: Optional[str]
    conversation_summary: Optional[str]
    
    # --- Conversation State ---
    active_topic: Optional[str]
    last_order_id: Optional[str]
    turn_count: int
    fallback_count: int

    # --- L1: RAG ---
    last_retrieved_context: Optional[str]
    answer_grounded: Optional[bool]
    # True/False once the rag_node has judged whether the retrieved
    # context actually supports an answer. False routes to fallback
    # instead of letting the LLM improvise from a weak match.

    # --- L2: order lookup + human handoff ---
    order_id: Optional[str]
    order_status: Optional[dict]
    handoff_requested: bool
    handoff_ticket_id: Optional[str]
    handoff_summary: Optional[str]
    existing_ticket_id: Optional[str]  # Set when reopening a resolved conversation
    conversation_mode: Literal["bot", "pending_human", "human"]
    # Defaults to "bot". Flips to "pending_human" the moment a handoff is
    # triggered, and to "human" once the ticket is confirmed created.
    # Every node should check this before generating a bot reply.

    # --- L3: reserved, unused in this phase ---
    otp_verified: Optional[bool]
    subscription_action: Optional[Literal["skip", "cancel", "resume"]]

    # --- L4: reserved, unused in this phase ---
    refund_requested: bool
    refund_policy_check: Optional[dict]
    refund_approval_status: Optional[Literal["pending", "approved", "rejected"]]


def initial_state(customer_email: Optional[str] = None) -> ConversationState:
    """Factory for a fresh conversation state. Keeps the TypedDict literal
    out of node code, so adding a field here is the only place that needs
    to change when new levels are switched on."""
    return ConversationState(
        messages=[],
        customer_email=customer_email,
        current_intent=None,
        conversation_summary=None,
        active_topic=None,
        last_order_id=None,
        turn_count=0,
        fallback_count=0,
        last_retrieved_context=None,
        answer_grounded=None,
        order_id=None,
        order_status=None,
        handoff_requested=False,
        handoff_ticket_id=None,
        handoff_summary=None,
        existing_ticket_id=None,
        conversation_mode="bot",
        otp_verified=None,
        subscription_action=None,
        refund_requested=False,
        refund_policy_check=None,
        refund_approval_status=None,
    )
