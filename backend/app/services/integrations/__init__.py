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

class UnconfiguredEcommerceProvider(EcommerceProvider):
    """A tenant with no commerce integration. Answers "nothing found" to every
    lookup; it must NEVER fall back to another tenant's (e.g. the default
    tenant's) store credentials."""

    requires_verification = True

    def get_order_status(self, *a, **k):
        return None

    def get_order_by_email(self, *a, **k):
        return None

    def get_customer_info(self, *a, **k):
        return None

    def process_refund(self, *a, **k):
        return {"success": False, "message": "No commerce integration is configured for this store."}

    def update_subscription(self, *a, **k):
        return {"success": False, "message": "No commerce integration is configured for this store."}

    def recommend_product(self, *a, **k):
        return []

    def track_purchase(self, *a, **k):
        return {"success": False}


_provider_cache: dict[str, tuple[float, EcommerceProvider]] = {}
_PROVIDER_TTL = 300.0


def invalidate_provider_cache(tenant_id: str | None = None) -> None:
    if tenant_id is None:
        _provider_cache.clear()
    else:
        _provider_cache.pop(tenant_id, None)


def get_ecommerce_provider(tenant_id: str | None = None) -> EcommerceProvider:
    """Commerce provider for *tenant_id*.

    * default tenant (or None): behaves exactly as before (mock, or Shopify from env);
    * any other tenant: its own Shopify credentials from the tenants table
      (decrypted), or an UnconfiguredEcommerceProvider.
    """
    from app.db.tenancy import DEFAULT_TENANT_ID

    tid = tenant_id or DEFAULT_TENANT_ID
    if tid == DEFAULT_TENANT_ID:
        return _default_ecommerce_provider()
    import time
    hit = _provider_cache.get(tid)
    if hit and time.monotonic() - hit[0] < _PROVIDER_TTL:
        return hit[1]

    from app.db.models import Tenant
    from app.db.session import SessionLocal
    from app.security.secrets_box import SecretsUnavailable, decrypt

    with SessionLocal() as db:   # unscoped on purpose: tenants is not a tenant-owned table
        tenant = db.get(Tenant, tid)
        provider: EcommerceProvider = UnconfiguredEcommerceProvider()
        if tenant and tenant.is_active and tenant.shopify_store_url and tenant.shopify_token_enc:
            try:
                provider = ShopifyProvider(decrypt(tenant.shopify_token_enc), tenant.shopify_store_url,
                                           api_version=os.environ.get("SHOPIFY_API_VERSION") or None)
            except SecretsUnavailable:
                provider = UnconfiguredEcommerceProvider()
    _provider_cache[tid] = (time.monotonic(), provider)
    return provider


def _default_ecommerce_provider() -> EcommerceProvider:
    # The built-in storefront database is single-merchant (its tables have no
    # tenant_id), so it only ever backs the DEFAULT tenant.
    if store_db_enabled():
        from .store_db import StoreDBProvider  # storefront database (see app/db/store_models.py)
        return StoreDBProvider()
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


def get_crm_provider(tenant_id: str | None = None) -> CRMProvider:
    from app.db.tenancy import DEFAULT_TENANT_ID

    if USE_MOCK:
        return MockCRMProvider()
    if tenant_id and tenant_id != DEFAULT_TENANT_ID:
        # Zendesk credentials are still process-wide; a non-default tenant must not
        # open tickets in the default tenant's helpdesk.
        return MockCRMProvider()
    
    api_token = os.environ.get("ZENDESK_API_TOKEN", "")
    subdomain = os.environ.get("ZENDESK_SUBDOMAIN", "")
    email = os.environ.get("ZENDESK_EMAIL", "")
    return ZendeskProvider(api_token, subdomain, email)

def env_value(key, default=""):
    """os.environ first, then the .env file. The app loads .env through pydantic-settings, which does NOT fill os.environ."""
    value = os.environ.get(key)
    if value is None:
        try:
            with open(".env", encoding="utf-8") as fh:
                for line in fh:
                    k, _, v = line.strip().partition("=")
                    if k.strip() == key:
                        return v.strip().strip("\"'")
        except OSError:
            pass
    return default if value is None else value

def store_db_enabled():
    return env_value("ECOMMERCE_PROVIDER").strip().lower() == "store_db"
