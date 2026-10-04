import asyncio
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import text

from app.cache import CLICK_STREAM, counter_key, link_key


async def _create(api: AsyncClient, **overrides) -> dict:
    payload = {"target_url": "https://example.com/target"} | overrides
    r = await api.post("/api/links", json=payload)
    assert r.status_code == 201
    return r.json()


async def test_valid_code_redirects_with_307(api: AsyncClient) -> None:
    link = await _create(api)
    r = await api.get(f"/{link['code']}", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == link["target_url"]


async def test_unknown_code_is_404(api: AsyncClient) -> None:
    r = await api.get("/nosuch1", follow_redirects=False)
    assert r.status_code == 404
    assert r.json()["code"] == "link_not_found"


async def test_expired_link_is_410(api: AsyncClient) -> None:
    soon = (datetime.now(UTC) + timedelta(seconds=2)).isoformat()
    link = await _create(api, custom_alias="expsoon2", expires_at=soon)
    await asyncio.sleep(2.2)
    r = await api.get(f"/{link['code']}", follow_redirects=False)
    assert r.status_code == 410
    assert r.json()["code"] == "link_expired"


async def test_reserved_code_is_404_not_a_lookup(api: AsyncClient) -> None:
    r = await api.get("/admin", follow_redirects=False)
    assert r.status_code == 404


async def test_second_request_is_served_from_cache_not_postgres(
    api: AsyncClient, db_engine, redis_conn
) -> None:
    link = await _create(api)
    r1 = await api.get(f"/{link['code']}", follow_redirects=False)
    assert r1.status_code == 307

    async with db_engine.begin() as conn:
        await conn.execute(text("DELETE FROM links WHERE code = :c"), {"c": link["code"]})

    r2 = await api.get(f"/{link['code']}", follow_redirects=False)
    assert r2.status_code == 307
    assert r2.headers["location"] == link["target_url"]


async def test_unknown_code_populates_the_negative_cache(api: AsyncClient, redis_conn) -> None:
    r = await api.get("/nowhere1", follow_redirects=False)
    assert r.status_code == 404
    raw = await redis_conn.get(link_key("nowhere1"))
    assert raw is not None


async def test_click_is_counted_by_the_time_the_response_returns(
    api: AsyncClient, db_engine, redis_conn
) -> None:
    link = await _create(api, custom_alias="counted1")
    async with db_engine.begin() as conn:
        row = await conn.execute(text("SELECT id FROM links WHERE code = :c"), {"c": "counted1"})
        link_id = row.scalar_one()

    await api.get(f"/{link['code']}", follow_redirects=False)
    await api.get(f"/{link['code']}", follow_redirects=False)

    count = await redis_conn.get(counter_key(link_id))
    assert count == "2"


async def test_click_stream_carries_the_referrer_host_not_the_full_url(
    api: AsyncClient, redis_conn
) -> None:
    link = await _create(api, custom_alias="referred1")
    await api.get(
        f"/{link['code']}",
        follow_redirects=False,
        headers={"referer": "https://news.ycombinator.com/item?id=123&token=secret"},
    )
    entries = await redis_conn.xrange(CLICK_STREAM)
    assert entries, "expected at least one stream entry"
    _, fields = entries[-1]
    assert fields["referrer_host"] == "news.ycombinator.com"
    assert "secret" not in fields["referrer_host"]
