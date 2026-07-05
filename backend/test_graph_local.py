import asyncio
from app.graph.builder import build_graph
from app.graph.state import initial_state
from langchain_core.messages import HumanMessage

async def test_graph():
    graph = build_graph()
    state = initial_state(customer_email="test@example.com")
    state["messages"].append(HumanMessage(content="Hello!"))
    
    result = await asyncio.to_thread(graph.invoke, state)
    print("Graph execution finished.")
    print(f"Final messages: {result['messages'][-1].content}")

if __name__ == "__main__":
    asyncio.run(test_graph())
