"""
Graph construction. Routing is intent-based: a lightweight classifier
decides which node handles the current turn. L3/L4 nodes plug into the
`route_intent` conditional edge map below when those levels are added —
the entry point and compile step do not change.
"""

from __future__ import annotations

import re

from langgraph.graph import END, StateGraph

from app.graph.nodes.greeting_node import greeting_node
from app.graph.nodes.handoff_node import handoff_node
from app.graph.nodes.order_node import order_node
from app.graph.nodes.rag_node import rag_node
from app.graph.nodes.reply_node import reply_node
from app.graph.nodes.resolved_node import resolved_node
from app.graph.state import ConversationState
from app.services.llm import classify_intent


def route_intent(state: ConversationState) -> str:
    """Decide which node should handle this turn using an LLM classifier.
    """
    if state.get("handoff_requested"):
        return "handoff"

    # If order_id was pre-extracted, route directly to order node
    if state.get("order_id"):
        return "order"

    intent = classify_intent(state["messages"])
    
    if intent == "handoff":
        state["handoff_requested"] = True

    return intent



def build_graph():
    graph = StateGraph(ConversationState)

    graph.add_node("greeting", greeting_node)
    graph.add_node("rag", rag_node)
    graph.add_node("order", order_node)
    graph.add_node("handoff", handoff_node)
    graph.add_node("resolved", resolved_node)
    graph.add_node("reply", reply_node)

    graph.set_conditional_entry_point(
        route_intent,
        {
            "greeting": "greeting",
            "rag": "rag",
            "order": "order",
            "handoff": "handoff",
            "resolved": "resolved",
        },
    )

    graph.add_edge("greeting", "reply")
    graph.add_edge("rag", "reply")
    graph.add_edge("order", "reply")
    graph.add_edge("handoff", "reply")
    graph.add_edge("resolved", END)
    graph.add_edge("reply", END)

    # --- L3/L4 extension point ---
    # When those levels are built, add their nodes above and extend the
    # route_intent map with new keys ("subscription", "refund", etc).
    # No existing node or edge needs to change.

    return graph.compile()
