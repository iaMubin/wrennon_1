import os
from .base import EcommerceProvider, CRMProvider
from .mock_provider import MockEcommerceProvider, MockCRMProvider
from .shopify import ShopifyProvider
from .zendesk import ZendeskProvider

USE_MOCK = os.environ.get("USE_MOCK_INTEGRATIONS", "true").lower() == "true"

def get_ecommerce_provider() -> EcommerceProvider:
    if USE_MOCK:
        return MockEcommerceProvider()
    
    # In a real setup, validate API keys exist
    api_key = os.environ.get("SHOPIFY_API_KEY", "")
    store_url = os.environ.get("SHOPIFY_STORE_URL", "")
    return ShopifyProvider(api_key, store_url)

def get_crm_provider() -> CRMProvider:
    if USE_MOCK:
        return MockCRMProvider()
    
    api_token = os.environ.get("ZENDESK_API_TOKEN", "")
    subdomain = os.environ.get("ZENDESK_SUBDOMAIN", "")
    email = os.environ.get("ZENDESK_EMAIL", "")
    return ZendeskProvider(api_token, subdomain, email)
