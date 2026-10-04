import json
from dataclasses import dataclass
from datetime import UTC, datetime

import redis.asyncio as aioredis

from app.config import get_settings

settings = get_settings()

redis_client: aioredis.Redis = aioredis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_timeout=1.0,
    socket_connect_timeout=1.0,
    health_check_interval=30,
)


def get_redis() -> aioredis.Redis:
    return redis_client


def link_key(code: str) -> str:
    """Cached target URL + expiry for a code."""
    return f"link:{code}"


def counter_key(link_id: int) -> str:
    """Live click counter, INCR on the redirect path."""
    return f"clicks:{link_id}"


def rate_key(ip: str) -> str:
    """Per-IP link-creation budget."""
    return f"rl:create:{ip}"


CLICK_STREAM = "clicks:stream"
CLICK_GROUP = "flusher"

NEGATIVE_MARKER = "∅"


@dataclass(frozen=True)
class CachedLink:
    id: int
    target_url: str
    expires_at: datetime | None


def _serialize(link_id: int, target_url: str, expires_at: datetime | None) -> str:
    return json.dumps(
        {
            "id": link_id,
            "target_url": target_url,
            "expires_at": expires_at.isoformat() if expires_at else None,
        }
    )


def _deserialize(raw: str) -> CachedLink:
    data = json.loads(raw)
    expires_at = datetime.fromisoformat(data["expires_at"]) if data["expires_at"] else None
    return CachedLink(id=data["id"], target_url=data["target_url"], expires_at=expires_at)


async def get_cached_link(redis: aioredis.Redis, code: str) -> CachedLink | None | bool:
    raw = await redis.get(link_key(code))
    if raw is None:
        return None
    if raw == NEGATIVE_MARKER:
        return False
    return _deserialize(raw)


async def cache_link(
    redis: aioredis.Redis, code: str, link_id: int, target_url: str, expires_at: datetime | None
) -> None:
    ttl = settings.link_cache_ttl_seconds
    if expires_at is not None:
        seconds_left = int((expires_at - datetime.now(UTC)).total_seconds())
        if seconds_left <= 0:
            return
        ttl = min(ttl, seconds_left)
    await redis.set(link_key(code), _serialize(link_id, target_url, expires_at), ex=ttl)


async def cache_link_missing(redis: aioredis.Redis, code: str) -> None:
    await redis.set(link_key(code), NEGATIVE_MARKER, ex=settings.link_negative_cache_ttl_seconds)
