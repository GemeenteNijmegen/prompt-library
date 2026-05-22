import json
from typing import Any

from cachetools import TTLCache

from src.config import settings

_TTL = 60
_MAXSIZE = 256

_local_cache: TTLCache = TTLCache(maxsize=_MAXSIZE, ttl=_TTL)


def _redis_client():
    import redis as redis_lib
    return redis_lib.from_url(settings.REDIS_URL, decode_responses=True)


def _use_redis() -> bool:
    return bool(settings.REDIS_URL)


def cache_get(key: str) -> Any | None:
    if _use_redis():
        r = _redis_client()
        raw = r.get(key)
        return json.loads(raw) if raw is not None else None
    return _local_cache.get(key)


def cache_set(key: str, value: Any, ttl: int = _TTL) -> None:
    if _use_redis():
        r = _redis_client()
        r.setex(key, ttl, json.dumps(value))
    else:
        _local_cache[key] = value


def cache_delete(key: str) -> None:
    if _use_redis():
        r = _redis_client()
        r.delete(key)
    else:
        _local_cache.pop(key, None)


def cache_clear() -> None:
    if _use_redis():
        r = _redis_client()
        r.flushdb()
    else:
        _local_cache.clear()
