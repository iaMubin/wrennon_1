from __future__ import annotations

from langchain_core.messages import AIMessage

from app.graph.state import ConversationState


def resolved_node(state: ConversationState) -> ConversationState:
    state["conversation_mode"] = "resolved"
    state["messages"].append(AIMessage(content="I'm glad I could help! If you need anything else, feel free to reach out. Have a great day!"))
    return state
