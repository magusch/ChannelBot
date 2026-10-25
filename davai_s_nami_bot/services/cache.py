"""Redis JSON cache shared by REST and gRPC.

``cache_key`` must stay byte-for-byte equal to ``api.dependencies.get_cache_key``
so both transports hit the same entries (a test pins it).
"""
import hashlib
import json
from datetime import datetime
from typing import Any, NamedTuple, Optional

from .. import celery_app as celery_module
from ..city_context import current_city

CACHE_TTL_SEC = 60 * 10


class Cached(NamedTuple):
    value: Any
    cached: bool  # served from Redis (REST shows it as "message": "cached")


def json_default(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def cache_key(params: dict) -> str:
    # The city is part of the key: the same filters give different events per city.
    key = json.dumps({"__city": current_city(), **params}, sort_keys=True)
    return hashlib.md5(key.encode()).hexdigest()


def get_json(key: str) -> Optional[Any]:
    # Read the client at call time: tests swap celery_app.redis_client.
    raw = celery_module.redis_client.get(key)
    return json.loads(raw) if raw else None


def set_json(key: str, value: Any, ttl: int = CACHE_TTL_SEC) -> None:
    celery_module.redis_client.setex(key, ttl, json.dumps(value, default=json_default))


def cached_call(key: str, compute, ttl: int = CACHE_TTL_SEC) -> Cached:
    hit = get_json(key)
    if hit is not None:
        return Cached(hit, True)
    value = compute()
    set_json(key, value, ttl)
    return Cached(value, False)
