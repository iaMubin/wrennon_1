"""Read-only Shopify Admin GraphQL provider.

Scopes needed on the (custom) app's access token: read_orders, read_customers,
read_products. Orders older than 60 days are invisible unless the app was also
granted `read_all_orders` AND the token was re-issued afterwards - Shopify does
not raise an error for this, it just returns nothing.

Money-moving operations (refunds, subscription changes) are intentionally NOT
implemented: they return an explicit "unsupported" result instead of the old
stub that claimed an approved refund without calling Shopify.
"""
import json
import re
import time
from typing import Any, Dict, List, Optional

import httpx

from app.logger import logger
from .base import EcommerceProvider

DEFAULT_API_VERSION = "2026-01"
CACHE_TTL_SECONDS = 60
CACHE_MAX_ENTRIES = 500

_ORDER_FIELDS = """
  name email createdAt cancelledAt displayFulfillmentStatus displayFinancialStatus
  totalPriceSet { shopMoney { amount currencyCode } }
  paymentGatewayNames
  shippingLine { title }
  fulfillments(first: 5) {
    createdAt displayStatus deliveredAt estimatedDeliveryAt
    trackingInfo { company number url }
  }
"""


def _money(amount: Any, currency: Any) -> str:
    return f"{amount} {currency}".strip()


def _clean_term(value: str) -> str:
    """Strip everything that could change the meaning of a Shopify search query."""
    return re.sub(r"[^A-Za-z0-9@._+\-]", "", value or "")


class ShopifyProvider(EcommerceProvider):
    # The bot must prove the requester owns an order (email match) before
    # revealing it; the mock/demo provider doesn't need this.
    requires_verification = True

    def __init__(self, api_key: str, store_url: str, api_version: Optional[str] = None,
                 client: Optional[httpx.Client] = None):
        domain = re.sub(r"^https?://", "", (store_url or "").strip()).strip("/")
        self.store_domain = domain
        self.api_version = api_version or DEFAULT_API_VERSION
        self._endpoint = f"https://{domain}/admin/api/{self.api_version}/graphql.json"
        self._headers = {"X-Shopify-Access-Token": api_key, "Content-Type": "application/json"}
        self._client = client or httpx.Client(timeout=8.0)
        self._cache: Dict[str, tuple] = {}

    # ---- transport -------------------------------------------------------
    def _graphql(self, query: str, variables: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        key = json.dumps([query, variables], sort_keys=True)
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
        try:
            resp = self._client.post(self._endpoint, headers=self._headers,
                                     json={"query": query, "variables": variables})
            resp.raise_for_status()
            body = resp.json()
        except Exception as e:  # network, 4xx/5xx, bad JSON: never crash the chat turn
            logger.error(f"Shopify request failed: {type(e).__name__}: {e}")
            return None
        if body.get("errors"):
            logger.error(f"Shopify GraphQL errors: {body['errors']}")
            return None
        data = body.get("data")
        if len(self._cache) >= CACHE_MAX_ENTRIES:
            self._cache.clear()
        self._cache[key] = (time.time(), data)
        return data

    # ---- mapping ---------------------------------------------------------
    @staticmethod
    def _map_order(node: Dict[str, Any], include_email: bool) -> Dict[str, Any]:
        fulfillments = node.get("fulfillments") or []
        delivered = next((f for f in fulfillments if f.get("displayStatus") == "DELIVERED"), None)
        shipped = fulfillments[0] if fulfillments else None
        if node.get("cancelledAt"):
            status = "cancelled"
        elif delivered:
            status = "delivered"
        elif shipped:
            status = "shipped"
        elif node.get("displayFulfillmentStatus") in ("UNFULFILLED", "ON_HOLD", "SCHEDULED", "IN_PROGRESS", "OPEN"):
            status = "processing"
        else:
            status = (node.get("displayFulfillmentStatus") or "processing").lower()

        tracking = ((shipped or {}).get("trackingInfo") or [{}])[0] if shipped else {}
        price = ((node.get("totalPriceSet") or {}).get("shopMoney") or {})
        timeline = [{"status": "placed", "time": node.get("createdAt"), "label": "Order Placed"}]
        if shipped:
            timeline.append({"status": "shipped", "time": shipped.get("createdAt"), "label": "Shipped"})
        if delivered:
            timeline.append({"status": "delivered", "time": delivered.get("deliveredAt"), "label": "Delivered"})
        if node.get("cancelledAt"):
            timeline.append({"status": "cancelled", "time": node["cancelledAt"], "label": "Cancelled"})

        order = {
            "order_id": (node.get("name") or "").lstrip("#"),
            "status": status,
            "order_date": (node.get("createdAt") or "")[:10],
            "total_amount": _money(price.get("amount", ""), price.get("currencyCode", "")),
            "payment_method": ", ".join(node.get("paymentGatewayNames") or []) or None,
            "shipping_method": (node.get("shippingLine") or {}).get("title"),
            "carrier": tracking.get("company"),
            "eta": (shipped or {}).get("estimatedDeliveryAt"),
            "tracking_url": tracking.get("url"),
            "payment_status": (node.get("displayFinancialStatus") or "").lower() or None,
            "timeline": timeline,
        }
        if include_email:
            order["email"] = node.get("email")
        return order

    # ---- EcommerceProvider ----------------------------------------------
    def get_order_status(self, order_id: str, verify_email: Optional[str] = None,
                         include_email: bool = False) -> Optional[Dict[str, Any]]:
        number = _clean_term(str(order_id)).lstrip("#")
        if not number:
            return None
        data = self._graphql(
            "query($q: String!) { orders(first: 5, query: $q) { nodes {" + _ORDER_FIELDS + "} } }",
            {"q": f"name:#{number}"},
        )
        for node in ((data or {}).get("orders") or {}).get("nodes") or []:
            if (node.get("name") or "").lstrip("#") != number:
                continue
            if verify_email is not None and (node.get("email") or "").strip().lower() != verify_email.strip().lower():
                return None  # same result as "not found": don't confirm the order exists
            return self._map_order(node, include_email)
        return None

    def get_order_by_email(self, email: str, include_email: bool = False) -> Optional[Dict[str, Any]]:
        term = _clean_term(email)
        if not term:
            return None
        data = self._graphql(
            "query($q: String!) { orders(first: 1, sortKey: CREATED_AT, reverse: true, query: $q) { nodes {"
            + _ORDER_FIELDS + "} } }",
            {"q": f"email:{term}"},
        )
        nodes = ((data or {}).get("orders") or {}).get("nodes") or []
        return self._map_order(nodes[0], include_email) if nodes else None

    def get_customer_info(self, email: Optional[str] = None, phone: Optional[str] = None,
                          customer_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        term = _clean_term(email) if email else ""
        q = f"email:{term}" if term else (f"phone:{_clean_term(phone)}" if phone else "")
        if not q or q.endswith(":"):
            return None
        data = self._graphql(
            "query($q: String!) { customers(first: 1, query: $q) { nodes {"
            " id displayName email phone numberOfOrders tags"
            " amountSpent { amount currencyCode }"
            " lastOrder { name } } } }",
            {"q": q},
        )
        nodes = ((data or {}).get("customers") or {}).get("nodes") or []
        if not nodes:
            return None
        c = nodes[0]
        spent = c.get("amountSpent") or {}
        return {
            "id": str(c.get("id") or "").rsplit("/", 1)[-1] or None,
            "name": c.get("displayName"),
            "email": c.get("email"),
            "phone": c.get("phone"),
            "lifetime_value": _money(spent.get("amount", ""), spent.get("currencyCode", "")),
            "loyalty_tier": None,
            "recent_order": ((c.get("lastOrder") or {}).get("name") or "").lstrip("#") or None,
            "tags": c.get("tags") or [],
            "total_orders": int(c.get("numberOfOrders") or 0),
        }

    def recommend_product(self, context_keywords: str) -> List[Dict[str, Any]]:
        terms = [t for t in (_clean_term(w) for w in (context_keywords or "").split()) if len(t) > 2][:4]
        if not terms:
            return []
        clause = " OR ".join(f"title:*{t}* OR product_type:*{t}* OR tag:{t}" for t in terms)
        data = self._graphql(
            "query($q: String!) { products(first: 3, query: $q) { nodes {"
            " id title description onlineStoreUrl"
            " priceRangeV2 { minVariantPrice { amount currencyCode } } } } }",
            {"q": f"status:active AND ({clause})"},
        )
        out = []
        for p in ((data or {}).get("products") or {}).get("nodes") or []:
            price = ((p.get("priceRangeV2") or {}).get("minVariantPrice") or {})
            out.append({
                "product_id": p.get("id"),
                "name": p.get("title"),
                "price": price.get("amount"),
                "currency": price.get("currencyCode"),
                "description": (p.get("description") or "")[:200],
                "link": p.get("onlineStoreUrl"),
            })
        return out

    # ---- deliberately unsupported ---------------------------------------
    def process_refund(self, order_id: str, amount: float) -> Dict[str, Any]:
        return {"order_id": order_id, "status": "unsupported",
                "message": "Refunds must be issued by a human agent in the Shopify admin."}

    def update_subscription(self, customer_email: str, action: str) -> Dict[str, Any]:
        return {"status": "unsupported", "message": "Subscription changes are not supported."}

    def track_purchase(self, product_id: str) -> Dict[str, Any]:
        return {}
