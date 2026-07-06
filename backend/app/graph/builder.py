from __future__ import annotations
from langgraph.graph import END, StateGraph

from app.graph.nodes.handoff_node import handoff_node
from app.graph.nodes.manager_node import manager_node
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
        if state.get("turn_count", 0) >= 5 and state["conversation_mode"] != "pending_human":
            logger.info("Forcing handoff due to turn_count limit.")
            state["handoff_requested"] = True
            return "handoff"
            
        if state.get("handoff_requested") and state["conversation_mode"] != "pending_human":
            # Just route to handoff. The handoff node will create the ticket and change the mode,
            # then it will go to final_reply_node to generate the natural response.
            pass # We'll handle handoff conditionally below if tools are empty
            
        if state.get("planned_tools"):
            return "tool_executor"
        
        # Even if handoff is requested, we go to handoff node first, then to final_reply.
        if state.get("handoff_requested") and state["conversation_mode"] != "pending_human":
            return "handoff"
            
        return "final_reply"

    graph.add_conditional_edges(
        "manager", 
        route_after_manager, 
        {
            "tool_executor": "tool_executor", 
            "handoff": "handoff",
            "final_reply": "final_reply"
        }
    )

    def route_after_tools(state: ConversationState) -> str:
        if state.get("handoff_requested") and state["conversation_mode"] != "pending_human":
            return "handoff"
        return "final_reply"
        
    graph.add_conditional_edges(
        "tool_executor",
        route_after_tools,
        {
            "handoff": "handoff",
            "final_reply": "final_reply"
        }
    )

    graph.add_edge("handoff", "final_reply")
    graph.add_edge("final_reply", END)

    return graph.compile()
