import asyncio
from typing import Dict, Any
from app.services.integrations import get_ecommerce_provider
from app.services import store_tools as _store_tools
from app.services.vectorstore import retrieve_and_rerank
import json

ecommerce = get_ecommerce_provider()

async def execute_get_order_status(args: Dict[str, Any]) -> str:
    order_id = args.get("order_id")
    if not order_id:
        return "Missing order_id. Please ask the user to provide it."
    
    if getattr(ecommerce, "requires_verification", False):
        # Identity check: only reveal an order if the customer has told us the email
        # on it. _claimed_emails is injected by tool_executor from the customer's own
        # raw messages and always overwritten, so the LLM cannot supply or forge it.
        claimed = args.get("_claimed_emails") or []
        if not claimed:
            return ("Cannot look up this order yet: ask the customer for the email address used at checkout. "
                    "Do not reveal any order details until they provide it.")
        result = None
        for email in claimed:
            result = await asyncio.to_thread(ecommerce.get_order_status, order_id, verify_email=email)
            if result:
                break
        if not result:
            # Identical wording for "no such order" and "email mismatch" (no enumeration).
            return ("No order found matching that order number and email. "
                    "Ask the customer to double-check both, or offer to escalate to a human agent.")
        return f"Order Status for {order_id}: {result}"
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


# Map tool names to their execution functions
TOOL_EXECUTORS = {
    "get_order_status": execute_get_order_status,
    "search_knowledge_base": execute_search_knowledge_base,
    # process_refund / update_subscription are deliberately NOT registered:
    # money-moving actions must not be reachable from LLM output (prompt
    # injection). Re-add only behind a deterministic policy gate + identity check.
    "recommend_product": execute_recommend_product,
    "track_purchase": execute_track_purchase,
    "get_my_orders": _store_tools.execute_get_my_orders,
    # check_refund_policy / send_otp / verify_otp were unregistered: they are stubs
    # (eligibility always True, any 4-6 digit OTP accepted) and no prompt exposes them.
}
