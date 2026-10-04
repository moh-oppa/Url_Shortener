from datetime import UTC, datetime, timedelta

from app.cache import (
    NEGATIVE_MARKER,
    cache_link,
    cache_link_missing,
    get_cached_link,
    link_key,
)


async def test_round_trips_a_link_with_no_expiry(redis_conn) -> None:
    await cache_link(redis_conn, "abc1234", link_id=1, target_url="https://x.com", expires_at=None)
    result = await get_cached_link(redis_conn, "abc1234")
    assert result.id == 1
    assert result.target_url == "https://x.com"
    assert result.expires_at is None


async def test_never_cached_returns_none_not_false(redis_conn) -> None:
    assert await get_cached_link(redis_conn, "neverseen") is None


async def test_missing_code_is_cached_as_false(redis_conn) -> None:
    await cache_link_missing(redis_conn, "typo404")
    assert await get_cached_link(redis_conn, "typo404") is False
    raw = await redis_conn.get(link_key("typo404"))
    assert raw == NEGATIVE_MARKER


async def test_ttl_is_capped_at_the_links_own_expiry(redis_conn) -> None:
    soon = datetime.now(UTC) + timedelta(seconds=5)
    await cache_link(redis_conn, "expsoon", link_id=1, target_url="https://x.com", expires_at=soon)
    ttl = await redis_conn.ttl(link_key("expsoon"))
    assert 0 < ttl <= 5


async def test_already_expired_link_is_not_cached_at_all(redis_conn) -> None:
    past = datetime.now(UTC) - timedelta(seconds=5)
    await cache_link(redis_conn, "oldlink", link_id=1, target_url="https://x.com", expires_at=past)
    assert await redis_conn.get(link_key("oldlink")) is None


async def test_expiry_survives_the_round_trip_with_timezone(redis_conn) -> None:
    expires = datetime.now(UTC) + timedelta(days=1)
    await cache_link(redis_conn, "tz1", link_id=1, target_url="https://x.com", expires_at=expires)
    result = await get_cached_link(redis_conn, "tz1")
    assert result.expires_at.tzinfo is not None
    assert abs((result.expires_at - expires).total_seconds()) < 1
