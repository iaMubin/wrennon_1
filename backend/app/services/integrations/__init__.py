import os
from .base import EcommerceProvider, CRMProvider
from .mock_provider import MockEcommerceProvider, MockCRMProvider
from .shopify import ShopifyProvider
from .zendesk import ZendeskProvider

_raw_mock = os.environ.get("USE_MOCK_INTEGRATIONS")
if _raw_mock is None and os.environ.get("APP_ENV") == "production":
    raise RuntimeError(
        "USE_MOCK_INTEGRATIONS must be set explicitly in production "
        "(true = fake demo data, false = real Shopify/Zendesk). Refusing to guess."
    )
USE_MOCK = (_raw_mock or "true").lower() == "true"

def get_ecommerce_provider() -> EcommerceProvider:
    if USE_MOCK:
        return MockEcommerceProvider()
    
    api_key = os.environ.get("SHOPIFY_API_KEY", "")
    store_url = os.environ.get("SHOPIFY_STORE_URL", "")
    if not api_key or not store_url:
        raise RuntimeError(
            "USE_MOCK_INTEGRATIONS=false requires SHOPIFY_API_KEY (Admin API access token) "
            "and SHOPIFY_STORE_URL (e.g. your-store.myshopify.com)."
        )
    return ShopifyProvider(api_key, store_url, api_version=os.environ.get("SHOPIFY_API_VERSION") or None)

def get_crm_provider() -> CRMProvider:
    if USE_MOCK:
        return MockCRMProvider()
    
    api_token = os.environ.get("ZENDESK_API_TOKEN", "")
    subdomain = os.environ.get("ZENDESK_SUBDOMAIN", "")
    email = os.environ.get("ZENDESK_EMAIL", "")
    return ZendeskProvider(api_token, subdomain, email)
