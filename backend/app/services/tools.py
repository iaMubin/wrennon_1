from typing import Dict, Any, List
from app.services.integrations import get_ecommerce_provider, get_crm_provider
from app.services.vectorstore import retrieve_and_rerank
import json

ecommerce = get_ecommerce_provider()

async def execute_get_order_status(args: Dict[str, Any]) -> str:
    order_id = args.get("order_id")
    if not order_id:
        return "Missing order_id. Please ask the user to provide it."
    
    result = ecommerce.get_order_status(order_id=order_id)
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
    result = ecommerce.process_refund(order_id, amount)
    return f"Refund processed: {json.dumps(result)}"

async def execute_update_subscription(args: Dict[str, Any]) -> str:
    email = args.get("customer_email")
    action = args.get("action")
    if not email or not action:
        return "Missing customer_email or action."
    result = ecommerce.update_subscription(email, action)
    return f"Subscription updated: {json.dumps(result)}"

async def execute_recommend_product(args: Dict[str, Any]) -> str:
    context = args.get("context_keywords", "")
    result = ecommerce.recommend_product(context)
    return f"Recommended products: {json.dumps(result)}"

async def execute_track_purchase(args: Dict[str, Any]) -> str:
    product_id = args.get("product_id")
    if not product_id:
        return "Missing product_id."
    result = ecommerce.track_purchase(product_id)
    return f"Purchase tracked: {json.dumps(result)}"

from app.services.tools_l3_l4 import execute_check_refund_policy, execute_send_otp, execute_verify_otp

# Map tool names to their execution functions
TOOL_EXECUTORS = {
    "get_order_status": execute_get_order_status,
    "search_knowledge_base": execute_search_knowledge_base,
    "process_refund": execute_process_refund,
    "update_subscription": execute_update_subscription,
    "recommend_product": execute_recommend_product,
    "track_purchase": execute_track_purchase,
    "check_refund_policy": execute_check_refund_policy,
    "send_otp": execute_send_otp,
    "verify_otp": execute_verify_otp,
}
