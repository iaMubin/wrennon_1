from __future__ import annotations
from langgraph.graph import END, StateGraph
from app.logger import logger

from app.graph.nodes.handoff_node import handoff_node
from app.graph.nodes.manager_node import manager_node, MAX_ITERATIONS
from app.graph.nodes.tool_executor import tool_executor_node
from app.graph.nodes.final_reply_node import final_reply_node
from app.graph.state import ConversationState


def build_graph():
    graph = StateGraph(ConversationState)

    graph.add_node("manager", manager_node)
    graph.add_node("tool_executor", tool_executor_node)
    graph.add_node("final_reply", final_reply_node)
    graph.add_node("handoff", handoff_node)

    graph.set_entry_point("manager")

    def route_after_manager(state: ConversationState) -> str:
        # NOTE: routing functions must be pure reads. LangGraph does not
        # persist mutations made inside a conditional-edge function back
        # into the graph's state — only a node's return value counts.
        # The turn_count safety valve therefore lives in manager_node.py
        # itself (it sets handoff_requested there); this function just
        # reacts to what's already in state.
        if state.get("handoff_requested") and state["conversation_mode"] != "pending_human":
            return "handoff"

        if state.get("planned_tools"):
            return "tool_executor"

        return "final_reply"

    graph.add_conditional_edges(
        "manager",
        route_after_manager,
        {
            "tool_executor": "tool_executor",
            "handoff": "handoff",
            "final_reply": "final_reply",
        },
    )

    def route_after_tools(state: ConversationState) -> str:
        if state.get("handoff_requested") and state["conversation_mode"] != "pending_human":
            return "handoff"

        # Loop back to the manager so it can react to what the tool(s)
        # actually returned, instead of blindly finalizing — this is what
        # makes the agent genuinely ReAct instead of one-shot classify.
        # iteration_count was already incremented by tool_executor_node
        # itself (a real node) — this function only reads it.
        if state.get("iteration_count", 0) >= MAX_ITERATIONS:
            logger.info("Manager reached max re-planning passes — finalizing reply now.")
            return "final_reply"
        return "manager"

    graph.add_conditional_edges(
        "tool_executor",
        route_after_tools,
        {
            "handoff": "handoff",
            "final_reply": "final_reply",
            "manager": "manager",
        },
    )

    graph.add_edge("handoff", "final_reply")
    graph.add_edge("final_reply", END)

    return graph.compile()
