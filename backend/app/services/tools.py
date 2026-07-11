from typing import Dict, Any, List
from app.services.mock_apis import get_order_status, process_refund, update_subscription, recommend_product, track_purchase
from app.services.vectorstore import retrieve_and_rerank
import json

async def execute_get_order_status(args: Dict[str, Any]) -> str:
    order_id = args.get("order_id")
    if not order_id:
        return "Missing order_id. Please ask the user to provide it."
    
    result = get_order_status(order_id=order_id)
    if not result:
        return f"Order {order_id} not found."
    return f"Order Status for {order_id}: {result}"

async def execute_search_knowledge_base(args: Dict[str, Any]) -> str:
    query = args.get("query")
    if not query:
        return "Missing query."
    
    results = await retrieve_and_rerank(query)
    if not results:
        return "No relevant policy found."
    
    context = "\n---\n".join([r.get("text", "") for r in results])
    return f"Knowledge Base Results:\n{context}"

async def execute_process_refund(args: Dict[str, Any]) -> str:
    order_id = args.get("order_id")
    amount = args.get("amount", 0.0)
    if not order_id:
        return "Missing order_id."
    result = process_refund(order_id, amount)
    return f"Refund processed: {json.dumps(result)}"

async def execute_update_subscription(args: Dict[str, Any]) -> str:
    email = args.get("customer_email")
    action = args.get("action")
    if not email or not action:
        return "Missing customer_email or action."
    result = update_subscription(email, action)
    return f"Subscription updated: {json.dumps(result)}"

async def execute_recommend_product(args: Dict[str, Any]) -> str:
    context = args.get("context_keywords", "")
    result = recommend_product(context)
    return f"Recommended products: {json.dumps(result)}"

async def execute_track_purchase(args: Dict[str, Any]) -> str:
    product_id = args.get("product_id")
    if not product_id:
        return "Missing product_id."
    result = track_purchase(product_id)
    return f"Purchase tracked: {json.dumps(result)}"

# Map tool names to their execution functions
TOOL_EXECUTORS = {
    "get_order_status": execute_get_order_status,
    "search_knowledge_base": execute_search_knowledge_base,
    "process_refund": execute_process_refund,
    "update_subscription": execute_update_subscription,
    "recommend_product": execute_recommend_product,
    "track_purchase": execute_track_purchase
}
