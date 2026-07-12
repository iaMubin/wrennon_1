import json
from typing import Dict, Any
from .integrations import get_ecommerce_provider

ecommerce = get_ecommerce_provider()

async def execute_check_refund_policy(args: Dict[str, Any]) -> str:
    order_id = args.get("order_id")
    if not order_id:
        return "Missing order_id."
    
    # In a real system, you'd fetch order details and check the 30-day policy
    order = ecommerce.get_order_status(order_id)
    if not order:
        return json.dumps({
            "order_id": order_id,
            "eligible": False,
            "reason": "Order not found."
        })
    
    return json.dumps({
        "order_id": order_id,
        "eligible": True,
        "reason": "Order is within the 30-day return window and is eligible for a full refund."
    })

async def execute_send_otp(args: Dict[str, Any]) -> str:
    email = args.get("email")
    if not email:
        return "Missing email address."
    
    # In a real system, this would send an SMS or Email
    return json.dumps({
        "status": "sent",
        "message": f"A one-time password has been sent to {email}. Please ask the user to provide it."
    })

async def execute_verify_otp(args: Dict[str, Any]) -> str:
    email = args.get("email")
    otp = args.get("otp")
    if not email or not otp:
        return "Missing email or otp."
    
    # Stub: accept any 4 or 6 digit code
    if len(str(otp)) in (4, 6):
        return json.dumps({
            "status": "verified",
            "message": "OTP verified successfully. You may now proceed with sensitive actions."
        })
    else:
        return json.dumps({
            "status": "failed",
            "message": "Invalid OTP. Please ask the user to try again."
        })
