import asyncio
import json

import httpx
import pytest

from app.services.integrations.shopify import ShopifyProvider

ORDER_NODE = {
    "name": "#1001", "email": "Jane@Example.com", "createdAt": "2026-10-01T10:00:00Z",
    "cancelledAt": None, "displayFulfillmentStatus": "FULFILLED", "displayFinancialStatus": "PAID",
    "totalPriceSet": {"shopMoney": {"amount": "59.00", "currencyCode": "GBP"}},
    "paymentGatewayNames": ["shopify_payments"], "shippingLine": {"title": "Standard"},
    "fulfillments": [{"createdAt": "2026-10-02T09:00:00Z", "displayStatus": "DELIVERED",
                      "deliveredAt": "2026-10-04T12:00:00Z", "estimatedDeliveryAt": None,
                      "trackingInfo": [{"company": "DHL", "number": "123", "url": "https://dhl.example/123"}]}],
}


def make_provider(handler):
    calls = []

    def wrapped(request: httpx.Request):
        calls.append(json.loads(request.content))
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(wrapped))
    return ShopifyProvider("tok", "https://shop.myshopify.com/", client=client), calls


def ok(nodes):
    return lambda r: httpx.Response(200, json={"data": {"orders": {"nodes": nodes}}})


def test_order_is_mapped_and_email_hidden_by_default():
    p, calls = make_provider(ok([ORDER_NODE]))
    order = p.get_order_status("#1001")
    assert order["order_id"] == "1001" and order["status"] == "delivered"
    assert order["total_amount"] == "59.00 GBP" and order["carrier"] == "DHL"
    assert "email" not in order
    assert p.get_order_status("1001", include_email=True)["email"] == "Jane@Example.com"
    assert calls[0]["variables"]["q"] == "name:#1001"


def test_email_verification_is_case_insensitive_and_mismatch_looks_like_not_found():
    p, _ = make_provider(ok([ORDER_NODE]))
    assert p.get_order_status("1001", verify_email="jane@example.com") is not None
    assert p.get_order_status("1001", verify_email="attacker@evil.com") is None


def test_search_input_cannot_inject_query_syntax():
    p, calls = make_provider(ok([]))
    p.get_order_status('1001" OR name:#1002')
    q = calls[0]["variables"]["q"]
    assert " " not in q and '"' not in q and q.count(":") == 1


def test_http_and_graphql_errors_never_raise():
    p, _ = make_provider(lambda r: httpx.Response(500, text="boom"))
    assert p.get_order_status("1001") is None
    p2, _ = make_provider(lambda r: httpx.Response(200, json={"errors": [{"message": "throttled"}]}))
    assert p2.get_order_status("1001") is None


def test_identical_lookups_hit_shopify_once():
    p, calls = make_provider(ok([ORDER_NODE]))
    p.get_order_status("1001"); p.get_order_status("1001")
    assert len(calls) == 1


def test_refunds_are_explicitly_unsupported_not_faked():
    p, calls = make_provider(ok([]))
    assert p.process_refund("1001", 10.0)["status"] == "unsupported"
    assert calls == []


def test_tool_requires_claimed_email_and_gives_no_oracle(monkeypatch):
    from app.services import tools
    p, calls = make_provider(ok([ORDER_NODE]))
    monkeypatch.setattr(tools, "ecommerce", p)
    run = lambda args: asyncio.run(tools.execute_get_order_status(args))
    assert "email address" in run({"order_id": "1001", "_claimed_emails": []})
    assert calls == []  # no Shopify call before identity is claimed
    wrong = run({"order_id": "1001", "_claimed_emails": ["attacker@evil.com"]})
    missing = run({"order_id": "9999", "_claimed_emails": ["attacker@evil.com"]})
    assert "No order found" in wrong and "delivered" not in wrong
    assert wrong.split(".")[0] == missing.split(".")[0]
    assert "delivered" in run({"order_id": "1001", "_claimed_emails": ["jane@example.com"]})


def test_executor_ignores_llm_supplied_claimed_emails(monkeypatch):
    from langchain_core.messages import HumanMessage
    from app.graph.nodes import tool_executor
    seen = {}

    async def fake_tool(args):
        seen.update(args)
        return "ok"

    monkeypatch.setitem(tool_executor.TOOL_EXECUTORS, "get_order_status", fake_tool)
    state = {"messages": [HumanMessage(content="order 1001, my email is jane@example.com")],
             "planned_tools": [{"name": "get_order_status",
                                "args": {"order_id": "1001", "_claimed_emails": ["attacker@evil.com"]}}]}
    asyncio.run(tool_executor.tool_executor_node(state))
    assert seen["_claimed_emails"] == ["jane@example.com"]


def test_live_mode_without_credentials_fails_fast(monkeypatch):
    from app.services import integrations
    monkeypatch.setattr(integrations, "USE_MOCK", False)
    monkeypatch.delenv("SHOPIFY_API_KEY", raising=False)
    monkeypatch.delenv("SHOPIFY_STORE_URL", raising=False)
    with pytest.raises(RuntimeError):
        integrations.get_ecommerce_provider()
