from typing import Dict, Any, List
from app.services.mock_apis import get_order_status
from app.services.vectorstore import retrieve_and_rerank

def execute_get_order_status(args: Dict[str, Any]) -> str:
    order_id = args.get("order_id")
    if not order_id:
        return "Missing order_id. Please ask the user to provide it."
    
    result = get_order_status(order_id=order_id)
    if not result:
        return f"Order {order_id} not found."
    return f"Order Status for {order_id}: {result}"

def execute_search_knowledge_base(args: Dict[str, Any]) -> str:
    query = args.get("query")
    if not query:
        return "Missing query."
    
    results = retrieve_and_rerank(query)
    if not results:
        return "No relevant policy found."
    
    context = "\n---\n".join([r.get("text", "") for r in results])
    return f"Knowledge Base Results:\n{context}"

# Map tool names to their execution functions
TOOL_EXECUTORS = {
    "get_order_status": execute_get_order_status,
    "search_knowledge_base": execute_search_knowledge_base
}
