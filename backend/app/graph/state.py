"""
Conversation state schema for the Wrennon showcase agent.

This is the single source of truth that flows through every node in the
LangGraph graph. Fields are grouped by the architecture level that
introduces them. L1/L2 fields are active in this phase of the build.
L3/L4 fields are declared now so the schema does not need to change shape
when those levels are added later — only new nodes get written.

CHANGE (LLM-quality rewrite): added iteration_count, tool_call_history,
and handoff_reason. All three are turn-scoped only (reset every message,
never persisted to the DB) — they exist purely so the manager node can
loop back after a tool call and reason about the result, instead of
being a one-shot classifier.
"""

from __future__ import annotations

from typing import Literal, Optional, TypedDict, NotRequired

from langchain_core.messages import BaseMessage


class ConversationState(TypedDict):
    # --- Core conversation state (used from L1 onward) ---
    messages: list[BaseMessage]
    customer_email: Optional[str]
    current_intent: Optional[str]
    conversation_summary: Optional[str]

    # --- Plan and Execute ---
    planned_tools: list[dict]
    gathered_context: list[str]

    # --- Manager <-> tool_executor loop (turn-scoped, never persisted) ---
    iteration_count: int
    # How many times control has passed manager -> tool_executor this
    # turn. Bounded by MAX_ITERATIONS in manager_node.py so a confused
    # model can't loop forever (and run up the Groq bill).
    tool_call_history: list[str]
    # "tool_name:json_args" signatures of everything actually executed
    # this turn, across all loop iterations. Used to (a) stop the
    # manager re-running an identical call and (b) let the caller know
    # everything that ran this turn (planned_tools only reflects the
    # *last* decision, since manager overwrites it each pass).

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
    handoff_reason: Optional[str]
    # WHY the manager decided to escalate, in the manager's own words.
    # Set before the handoff node runs; used both to write a sharper
    # ticket summary and to let final_reply explain the handoff to the
    # customer without generic filler.
    handoff_ticket_id: Optional[str]
    handoff_summary: Optional[str]
    existing_ticket_id: Optional[str]  # Set when reopening a resolved conversation
    conversation_mode: Literal["bot", "pending_human", "human", "resolved"]
    # Defaults to "bot". Flips to "pending_human" the moment a handoff is
    # triggered, to "human" once the ticket is confirmed created, and to
    # "resolved" when the manager decides the customer is done. Every
    # node should check this before generating a bot reply.
    direct_reply: Optional[str]

    # --- L3: reserved, unused in this phase ---
    otp_verified: Optional[bool]
    subscription_action: Optional[Literal["skip", "cancel", "resume"]]

    # --- L4: reserved, unused in this phase ---
    refund_requested: bool
    refund_policy_check: Optional[dict]
    refund_approval_status: Optional[Literal["pending", "approved", "rejected"]]

    # --- Analytics & Copilot ---
    revenue_generated: float
    resolution_logged: bool
    sentiment: NotRequired[str]
    intent_category: NotRequired[str]
    language: NotRequired[str]


def initial_state(customer_email: Optional[str] = None) -> ConversationState:
    """Factory for a fresh conversation state. Keeps the TypedDict literal
    out of node code, so adding a field here is the only place that needs
    to change when new levels are switched on."""
    return ConversationState(
        messages=[],
        customer_email=customer_email,
        current_intent=None,
        conversation_summary=None,
        planned_tools=[],
        gathered_context=[],
        iteration_count=0,
        tool_call_history=[],
        active_topic=None,
        last_order_id=None,
        turn_count=0,
        fallback_count=0,
        last_retrieved_context=None,
        answer_grounded=None,
        order_id=None,
        order_status=None,
        handoff_requested=False,
        handoff_reason=None,
        handoff_ticket_id=None,
        handoff_summary=None,
        existing_ticket_id=None,
        conversation_mode="bot",
        otp_verified=None,
        subscription_action=None,
        refund_requested=False,
        refund_policy_check=None,
        refund_approval_status=None,
        revenue_generated=0.0,
        resolution_logged=False,
        sentiment=None,
        intent_category=None,
        language="English",
        direct_reply=None,
    )
