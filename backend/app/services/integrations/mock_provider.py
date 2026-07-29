import datetime
import uuid
from typing import Optional, List, Dict, Any
from .base import EcommerceProvider, CRMProvider

# Wrennon's mock catalog — lifestyle clothing, footwear, and accessories.
# `keywords` drives recommend_product's simple relevance matching below and
# is stripped from the dict before it's returned to the caller/LLM.
PRODUCT_CATALOG: list[dict] = [
    {
        "product_id": "WRN-SHO-101",
        "name": "Trailrunner Low Sneakers",
        "price": 89.00,
        "description": "Lightweight everyday sneakers with a breathable mesh upper and cushioned sole — equally at home on city streets or light trails.",
        "link": "https://example.com/products/WRN-SHO-101",
        "keywords": ["sneaker", "sneakers", "shoe", "shoes", "running", "run", "walk", "trail", "casual"],
    },
    {
        "product_id": "WRN-BOOT-102",
        "name": "Highland Leather Boots",
        "price": 145.00,
        "description": "Weatherproof leather boots with a warm shearling lining, built for cold, wet winter days.",
        "link": "https://example.com/products/WRN-BOOT-102",
        "keywords": ["boot", "boots", "winter", "cold", "rain", "snow", "hike", "hiking", "shoe", "shoes"],
    },
    {
        "product_id": "WRN-JKT-201",
        "name": "Summit Insulated Parka",
        "price": 189.00,
        "description": "Our warmest jacket — insulated, waterproof, and rated for sub-zero temperatures.",
        "link": "https://example.com/products/WRN-JKT-201",
        "keywords": ["jacket", "coat", "parka", "winter", "cold", "snow", "hike", "hiking", "outerwear"],
    },
    {
        "product_id": "WRN-JKT-202",
        "name": "Classic Denim Jacket",
        "price": 79.00,
        "description": "A timeless denim jacket that layers well over almost any everyday outfit.",
        "link": "https://example.com/products/WRN-JKT-202",
        "keywords": ["jacket", "denim", "casual", "layer", "outerwear"],
    },
    {
        "product_id": "WRN-TSH-301",
        "name": "Everyday Crewneck Tee",
        "price": 24.00,
        "description": "Soft, breathable 100% cotton tee in a relaxed fit — a wardrobe staple.",
        "link": "https://example.com/products/WRN-TSH-301",
        "keywords": ["shirt", "t-shirt", "tshirt", "tee", "top", "casual", "basic", "summer"],
    },
    {
        "product_id": "WRN-HOD-302",
        "name": "Fleece-Lined Hoodie",
        "price": 58.00,
        "description": "Heavyweight fleece hoodie that keeps you warm without the bulk of a jacket.",
        "link": "https://example.com/products/WRN-HOD-302",
        "keywords": ["hoodie", "sweater", "warm", "cozy", "cold", "fleece", "winter", "top"],
    },
    {
        "product_id": "WRN-PNT-401",
        "name": "Flex-Fit Chinos",
        "price": 65.00,
        "description": "Stretch chinos that move with you — smart enough for the office, comfortable enough for everything else.",
        "link": "https://example.com/products/WRN-PNT-401",
        "keywords": ["pants", "chinos", "trousers", "bottoms", "work", "office", "smart", "formal"],
    },
    {
        "product_id": "WRN-ACC-501",
        "name": "Wool Beanie",
        "price": 22.00,
        "description": "Soft wool beanie for cold-weather days — pairs well with the Summit Parka.",
        "link": "https://example.com/products/WRN-ACC-501",
        "keywords": ["beanie", "hat", "winter", "cold", "accessory", "accessories", "gift"],
    },
    {
        "product_id": "WRN-ACC-502",
        "name": "Canvas Weekender Bag",
        "price": 68.00,
        "description": "Durable canvas duffel with leather trim — ideal for a weekend trip or the gym.",
        "link": "https://example.com/products/WRN-ACC-502",
        "keywords": ["bag", "travel", "weekend", "gym", "gift", "accessory", "accessories", "trip"],
    },
]

# Shown when no keyword in context_keywords matches any product — keeps
# recommend_product() useful even for vague prompts like a page-stall nudge.
_DEFAULT_RECOMMENDATION_IDS = ["WRN-TSH-301", "WRN-SHO-101"]


def _catalog_entry(product_id: str) -> dict:
    for item in PRODUCT_CATALOG:
        if item["product_id"] == product_id:
            return item
    raise KeyError(product_id)


def _public_fields(item: dict) -> Dict[str, Any]:
    """Strips internal matching metadata (`keywords`) before returning to the caller."""
    return {k: v for k, v in item.items() if k != "keywords"}


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
        """Returns up to 2 products from Wrennon's catalog most relevant to
        context_keywords (simple keyword overlap — no ML needed for a mock).
        Falls back to a couple of general bestsellers if nothing matches, so
        the shopping assistant always has something useful to suggest."""
        text = (context_keywords or "").lower()
        scored = []
        for item in PRODUCT_CATALOG:
            score = sum(1 for kw in item["keywords"] if kw in text)
            if score > 0:
                scored.append((score, item))

        if scored:
            scored.sort(key=lambda pair: pair[0], reverse=True)
            top_items = [item for _, item in scored[:2]]
        else:
            top_items = [_catalog_entry(pid) for pid in _DEFAULT_RECOMMENDATION_IDS]

        return [_public_fields(item) for item in top_items]

    def track_purchase(self, product_id: str) -> Dict[str, Any]:
        try:
            revenue = _catalog_entry(product_id)["price"]
        except KeyError:
            return {
                "success": False,
                "product_id": product_id,
                "revenue_generated": 0.00,
                "error": "Unknown product_id — nothing was tracked."
            }
        return {
            "success": True,
            "product_id": product_id,
            "revenue_generated": revenue
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
