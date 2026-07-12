import datetime
import uuid
from typing import Optional, List, Dict, Any
from .base import EcommerceProvider, CRMProvider

class MockEcommerceProvider(EcommerceProvider):
    def __init__(self):
        self.mock_orders = {
            "1001": {"order_id": "1001", "email": "customer1@example.com", "status": "shipped", "carrier": "Pathao Courier", "eta": "2026-06-27", "tracking_url": "https://example.com/track/1001"},
            "1002": {"order_id": "1002", "email": "test@example.com", "status": "processing", "carrier": None, "eta": "2026-06-30", "tracking_url": None},
            "1003": {"order_id": "1003", "email": "customer3@example.com", "status": "delivered", "carrier": "Sundarban Courier", "eta": "2026-06-20", "tracking_url": "https://example.com/track/1003"},
            "1004": {"order_id": "1004", "email": "test@example.com", "status": "cancelled", "carrier": None, "eta": None, "tracking_url": None},
            "1005": {"order_id": "1005", "email": "test@example.com", "status": "processing", "carrier": None, "eta": "2026-07-15", "tracking_url": None},
            "1006": {"order_id": "1006", "email": "customer6@example.com", "status": "shipped", "carrier": "DHL", "eta": "2026-07-08", "tracking_url": "https://dhl.com/track/1006"},
            "1007": {"order_id": "1007", "email": "customer7@example.com", "status": "delivered", "carrier": "FedEx", "eta": "2026-06-05", "tracking_url": "https://fedex.com/track/1007"},
        }

    def get_order_status(self, order_id: str) -> Optional[Dict[str, Any]]:
        order = self.mock_orders.get(order_id)
        if order:
            result = order.copy()
            if "email" in result:
                del result["email"]
            return result
        return None

    def get_order_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        if not email:
            return None
        email_lower = email.lower().strip()
        matches = [o for o in self.mock_orders.values() if o.get("email", "").lower() == email_lower]
        if not matches:
            return None
        latest = max(matches, key=lambda x: x["order_id"])
        result = latest.copy()
        if "email" in result:
            del result["email"]
        return result

    def process_refund(self, order_id: str, amount: float) -> Dict[str, Any]:
        return {
            "refund_id": f"REF-{uuid.uuid4().hex[:6].upper()}",
            "order_id": order_id,
            "amount_refunded": amount,
            "status": "approved",
            "processed_at": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()
        }

    def update_subscription(self, customer_email: str, action: str) -> Dict[str, Any]:
        status_map = {"skip": "skipped_next_delivery", "cancel": "cancelled", "resume": "active"}
        return {
            "email": customer_email,
            "subscription_status": status_map.get(action, "unknown"),
            "updated_at": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()
        }

    def recommend_product(self, context_keywords: str) -> List[Dict[str, Any]]:
        return [
            {
                "product_id": "PROD-X2",
                "name": "Premium Plan Upgrade",
                "price": 29.99,
                "description": "Upgrade to our premium tier for faster shipping and exclusive content.",
                "link": "https://example.com/upgrade/PROD-X2"
            },
            {
                "product_id": "PROD-Y1",
                "name": "Limited Edition Merch",
                "price": 15.00,
                "description": "Show your support with our limited edition merch.",
                "link": "https://example.com/merch/PROD-Y1"
            }
        ]

    def track_purchase(self, product_id: str) -> Dict[str, Any]:
        price_map = {"PROD-X2": 29.99, "PROD-Y1": 15.00}
        return {
            "success": True,
            "product_id": product_id,
            "revenue_generated": price_map.get(product_id, 10.00)
        }

class MockCRMProvider(CRMProvider):
    def create_support_ticket(self, customer_email: str, conversation_summary: str, order_id: Optional[str] = None) -> Dict[str, Any]:
        return {
            "ticket_id": f"TICKET-{uuid.uuid4().hex[:8].upper()}",
            "status": "open",
            "created_at": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat(),
        }

    def reopen_support_ticket(self, ticket_id: str, conversation_summary: str) -> Dict[str, Any]:
        return {
            "ticket_id": ticket_id,
            "status": "reopened",
            "reopened_at": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat(),
        }
