import json
import time

import redis.asyncio as aioredis


TTL_SECONDS = 7 * 24 * 3600  # 7 days


async def cache_record(r: aioredis, key: str, data: dict, ttl: int = TTL_SECONDS) -> None:
    try:
        await r.set(key, json.dumps(data, default=str), ex=ttl)
    except Exception:
        pass


async def get_cached(r: aioredis, key: str) -> dict | None:
    try:
        raw = await r.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


async def update_recent_set(r: aioredis, set_key: str, member_id: str) -> None:
    try:
        await r.zadd(set_key, {member_id: time.time()})
        await r.zremrangebyrank(set_key, 0, -101)
    except Exception:
        pass
