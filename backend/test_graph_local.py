import asyncio
from app.graph.builder import build_graph
from app.graph.state import initial_state
from langchain_core.messages import HumanMessage, AIMessage

async def test_graph():
    graph = build_graph()
    state = initial_state(customer_email="test@example.com")
    
    # Simulate history
    state["messages"].append(HumanMessage(content="where is order 1002?"))
    state["messages"].append(AIMessage(content="Please provide the email address or phone number used for order #1002 to retrieve the tracking details."))
    
    # New user message
    state["messages"].append(HumanMessage(content="hello"))
    
    result = await asyncio.to_thread(graph.invoke, state)
    print("Graph execution finished.")
    print(f"Final messages: {result['messages'][-1].content}")

if __name__ == "__main__":
    asyncio.run(test_graph())
