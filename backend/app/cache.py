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