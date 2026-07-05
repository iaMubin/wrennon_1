import asyncio
from app.graph.builder import build_graph
from app.graph.state import initial_state
from langchain_core.messages import HumanMessage, AIMessage

async def test_graph():
    graph = build_graph()
    
    # Test 1: Greeting
    print("\n--- TEST 1: Greeting ---")
    state1 = initial_state(customer_email="test@example.com")
    state1["messages"].append(HumanMessage(content="Hello there!"))
    result1 = await asyncio.to_thread(graph.invoke, state1)
    print(f"Planned Tools: {result1.get('planned_tools')}")
    print(f"Final Message: {result1['messages'][-1].content.encode('utf-8')}")
    
    # Test 2: Knowledge Base
    print("\n--- TEST 2: Knowledge Base ---")
    state2 = initial_state(customer_email="test@example.com")
    state2["messages"].append(HumanMessage(content="What is your return policy?"))
    result2 = await asyncio.to_thread(graph.invoke, state2)
    print(f"Planned Tools: {result2.get('planned_tools')}")
    print(f"Final Message: {result2['messages'][-1].content.encode('utf-8')}")
    
    # Test 3: Order Status (missing email)
    print("\n--- TEST 3: Order Status (missing email) ---")
    state3 = initial_state(customer_email=None)
    state3["messages"].append(HumanMessage(content="Where is my order 1002?"))
    result3 = await asyncio.to_thread(graph.invoke, state3)
    print(f"Planned Tools: {result3.get('planned_tools')}")
    print(f"Final Message: {result3['messages'][-1].content.encode('utf-8')}")
    
    # Test 4: Handoff
    print("\n--- TEST 4: Handoff ---")
    state4 = initial_state(customer_email="test@example.com")
    state4["messages"].append(HumanMessage(content="Cancel my order immediately!"))
    result4 = await asyncio.to_thread(graph.invoke, state4)
    print(f"Handoff Requested: {result4.get('handoff_requested')}")
    print(f"Final Message: {result4['messages'][-1].content.encode('utf-8')}")

if __name__ == "__main__":
    asyncio.run(test_graph())
