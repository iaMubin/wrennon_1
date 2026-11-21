"""Small fixed-window counters used for quotas and brute-force throttles.

Backed by Redis when it is reachable. When Redis is down (or the app runs with
``REDIS_URL=memory://``) it falls back to a per-process dictionary, so the
limits still hold per worker instead of silently disappearing: the older
inline limiters fail *open* on a Redis outage, which is the wrong default for
security-relevant counters (login/OTP/lookup attempts, upload quotas).
"""

from __future__ import annotations

import time

from app.logger import logger

_memory: dict[str, tuple[int, float]] = {}


def _mem_hit(key: str, window: int, amount: int) -> int:
    now = time.monotonic()
    if len(_memory) > 50_000:  # crude bound so a flood of keys cannot grow RAM forever
        for k in [k for k, (_, exp) in _memory.items() if exp <= now]:
            _memory.pop(k, None)
        if len(_memory) > 50_000:
            _memory.clear()
    count, exp = _memory.get(key, (0, 0.0))
    if exp <= now:
        count, exp = 0, now + window
    count += amount
    _memory[key] = (count, exp)
    return count


async def hit(key: str, window: int, amount: int = 1) -> int:
    """Add *amount* to the counter for *key* (fixed *window* seconds); return the new total."""
    from app.api.agent import DummyRedis, get_redis

    mem_total = _mem_hit(key, window, amount)
    r = get_redis()
    if isinstance(r, DummyRedis):
        return mem_total
    try:
        total = await r.incrby(key, amount)
        if total == amount:
            await r.expire(key, window)
        return int(total)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Redis unavailable for counter {key.split(':')[0]}; using in-process fallback: {type(e).__name__}")
        return mem_total


async def peek(key: str) -> int:
    from app.api.agent import DummyRedis, get_redis

    r_val = 0
    r = get_redis()
    if not isinstance(r, DummyRedis):
        try:
            v = await r.get(key)
            r_val = int(v) if v else 0
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Redis peek failed, using in-process counter: {type(e).__name__}")
    count, exp = _memory.get(key, (0, 0.0))
    mem_val = count if exp > time.monotonic() else 0
    return max(r_val, mem_val)


async def clear(key: str) -> None:
    from app.api.agent import DummyRedis, get_redis

    _memory.pop(key, None)
    r = get_redis()
    if not isinstance(r, DummyRedis):
        try:
            await r.delete(key)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Redis delete failed: {type(e).__name__}")
