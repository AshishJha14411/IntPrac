"""Idempotency keys for unsafe POSTs (Appendix D.2).

Two layers, deliberately:

1. **Redis ``SET NX``** catches the fast retry -- the double-click, the client
   that timed out and resent. It short-circuits before any work happens.
2. **A unique constraint on ``answers.idempotency_key``** is the arbiter. Redis
   can be flushed, evicted, or unavailable; the database cannot lie.

Layer 1 is an optimisation. Layer 2 is the guarantee (FR-S8 / NFR-S2).
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_TTL_SECONDS = 24 * 3600
_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


def _key(scope: str, key: str) -> str:
    return f"idem:{scope}:{key}"


async def claim(scope: str, key: str) -> bool:
    """Try to claim a key. ``False`` means someone already has it.

    A Redis outage returns ``True`` (claim granted) on purpose: the DB
    constraint still protects correctness, and we would rather serve the
    request than fail an interview because a cache blinked (NFR-S4).
    """
    try:
        return bool(await get_redis().set(_key(scope, key), "in-flight", nx=True, ex=_TTL_SECONDS))
    except Exception:
        logger.warning("idempotency_claim_unavailable", scope=scope)
        return True


async def store_result(scope: str, key: str, payload: dict[str, Any]) -> None:
    try:
        await get_redis().set(_key(scope, key), json.dumps(payload), ex=_TTL_SECONDS)
    except Exception:
        logger.warning("idempotency_store_unavailable", scope=scope)


async def fetch_result(scope: str, key: str) -> dict[str, Any] | None:
    try:
        raw = await get_redis().get(_key(scope, key))
    except Exception:
        return None
    if not raw or raw == "in-flight":
        return None
    try:
        return json.loads(raw)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        return None


async def release(scope: str, key: str) -> None:
    """Drop a claim so a genuinely failed request can be retried.

    A failure to release is survivable -- the claim expires on its own -- so
    this suppresses rather than propagates.
    """
    with contextlib.suppress(Exception):
        await get_redis().delete(_key(scope, key))
