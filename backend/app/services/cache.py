import hashlib
import json
from typing import Optional, Any
from app.api.agent import get_redis
from app.logger import logger

def _tenant() -> str:
    # Cached replies are per tenant: a shared key would serve one merchant's answer
    # (policies, prices, order data) to another merchant's customers.
    from app.db.tenancy import DEFAULT_TENANT_ID, current_tenant

    return current_tenant.get() or DEFAULT_TENANT_ID


async def get_cache(key: str) -> Optional[Any]:
    """Retrieve semantic cache hit from Redis."""
    try:
        r = get_redis()
        cache_key = f"semantic_cache:{_tenant()}:{hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()}"
        data = await r.get(cache_key)
        if data:
            return json.loads(data)
    except Exception as e:
        logger.debug(f"Semantic cache read failed, treating as cache miss: {e}")
    return None

async def set_cache(key: str, value: Any, ttl: int = 3600) -> None:
    """Store response in Redis Semantic Cache."""
    try:
        r = get_redis()
        cache_key = f"semantic_cache:{_tenant()}:{hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()}"
        await r.set(cache_key, json.dumps(value), ex=ttl)
    except Exception as e:
        logger.debug(f"Semantic cache write failed, continuing without cache: {e}")