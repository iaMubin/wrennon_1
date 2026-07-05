import hashlib
import json
from typing import Optional, Any
from app.api.agent import get_redis

async def get_cache(key: str) -> Optional[Any]:
    """Retrieve semantic cache hit from Redis."""
    try:
        r = get_redis()
        cache_key = f"semantic_cache:{hashlib.md5(key.encode()).hexdigest()}"
        data = await r.get(cache_key)
        if data:
            return json.loads(data)
    except Exception:
        pass
    return None

async def set_cache(key: str, value: Any, ttl: int = 3600) -> None:
    """Store response in Redis Semantic Cache."""
    try:
        r = get_redis()
        cache_key = f"semantic_cache:{hashlib.md5(key.encode()).hexdigest()}"
        await r.set(cache_key, json.dumps(value), ex=ttl)
    except Exception:
        pass
