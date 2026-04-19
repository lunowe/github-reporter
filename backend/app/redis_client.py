"""
Redis connection — async via redis.asyncio.
Single pooled client, accessed globally.
"""

from __future__ import annotations

import logging
from typing import Optional

from redis.asyncio import Redis, ConnectionPool

logger = logging.getLogger(__name__)

_pool: Optional[ConnectionPool] = None
_client: Optional[Redis] = None


def init_redis(url: str) -> None:
    """Call once at startup. decode_responses=True → str in, str out."""
    global _pool, _client
    _pool = ConnectionPool.from_url(
        url,
        decode_responses=True,
        max_connections=64,
        health_check_interval=30,
    )
    _client = Redis(connection_pool=_pool)
    logger.info("Redis pool initialised (%s)", _safe_url(url))


def get_redis() -> Redis:
    if _client is None:
        raise RuntimeError("Redis not initialised — call init_redis() first")
    return _client


async def close_redis() -> None:
    global _pool, _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:  # pragma: no cover
            logger.exception("Error closing redis client")
    if _pool is not None:
        try:
            await _pool.disconnect()
        except Exception:  # pragma: no cover
            logger.exception("Error disconnecting redis pool")
    _client = None
    _pool = None


def _safe_url(url: str) -> str:
    """Strip credentials before logging."""
    if "@" in url:
        proto, rest = url.split("://", 1)
        _, host = rest.split("@", 1)
        return f"{proto}://***@{host}"
    return url
