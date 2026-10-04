import logging
from datetime import UTC, datetime
from urllib.parse import urlparse

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import CLICK_STREAM, CachedLink, cache_link, cache_link_missing, counter_key
from app.cache import get_cached_link as _get_cached_link
from app.config import Settings
from app.errors import LinkExpired, LinkNotFound
from app.models import DIRECT_REFERRER
from app.services import get_link_by_code

logger = logging.getLogger(__name__)


async def resolve_link(session: AsyncSession, redis: aioredis.Redis, code: str) -> CachedLink:
    cached = await _get_cached_link(redis, code)

    if cached is False:
        raise LinkNotFound(f"no link with code '{code}'")

    if cached is not None:
        if cached.expires_at is not None and cached.expires_at <= datetime.now(UTC):
            raise LinkExpired(f"link '{code}' expired")
        return cached

    link = await get_link_by_code(session, code)
    if link is None:
        await cache_link_missing(redis, code)
        raise LinkNotFound(f"no link with code '{code}'")

    if link.is_expired():
        raise LinkExpired(f"link '{code}' expired")

    await cache_link(redis, code, link.id, link.target_url, link.expires_at)
    return CachedLink(id=link.id, target_url=link.target_url, expires_at=link.expires_at)


def referrer_host(referer_header: str | None) -> str:
    if not referer_header:
        return DIRECT_REFERRER
    host = urlparse(referer_header).hostname
    return host or DIRECT_REFERRER


async def record_click(
    redis: aioredis.Redis, settings: Settings, link_id: int, referrer: str, client_ip: str
) -> None:
    try:
        await redis.incr(counter_key(link_id))
        await redis.xadd(
            CLICK_STREAM,
            {
                "link_id": link_id,
                "referrer_host": referrer,
                "client_ip": client_ip,
                "clicked_at": datetime.now(UTC).isoformat(),
            },
            maxlen=settings.click_stream_maxlen,
            approximate=True,
        )
    except Exception:
        logger.warning("click recording failed for link_id=%s", link_id, exc_info=True)
