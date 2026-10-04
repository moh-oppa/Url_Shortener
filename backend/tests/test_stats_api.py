from datetime import date, timedelta

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cache import counter_key
from app.models import Link

VALID = {"target_url": "https://example.com"}
TODAY = date(2026, 1, 15)


async def _make_link(session_factory: async_sessionmaker[AsyncSession], code: str) -> int:
    async with session_factory() as session:
        link = Link(code=code, target_url="https://example.com", is_custom=True)
        session.add(link)
        await session.commit()
        await session.refresh(link)
        return link.id


async def _insert_daily(
    session_factory: async_sessionmaker[AsyncSession],
    link_id: int,
    day: date,
    country: str,
    referrer: str,
    clicks: int,
) -> None:
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO click_daily (link_id, day, country, referrer_host, clicks) "
                "VALUES (:lid, :day, :country, :ref, :clicks)"
            ),
            {"lid": link_id, "day": day, "country": country, "ref": referrer, "clicks": clicks},
        )
        await session.commit()


async def test_stats_for_a_link_with_no_clicks_returns_zeros_not_an_error(
    api: AsyncClient,
) -> None:
    created = (await api.post("/api/links", json={**VALID, "custom_alias": "nostats1"})).json()
    r = await api.get(f"/api/links/{created['code']}/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total_clicks"] == 0
    assert body["live_clicks"] == 0
    assert body["by_country"] == []
    assert body["by_referrer"] == []
    assert body["timeseries"] == []


async def test_unknown_code_is_404(api: AsyncClient) -> None:
    r = await api.get("/api/links/nosuch1/stats")
    assert r.status_code == 404
    assert r.json()["code"] == "link_not_found"


async def test_same_country_on_different_days_sums_into_one_bucket(
    api: AsyncClient, db_session_factory
) -> None:
    link_id = await _make_link(db_session_factory, "statsA")
    await _insert_daily(db_session_factory, link_id, TODAY, "NG", "direct", 3)
    await _insert_daily(db_session_factory, link_id, TODAY + timedelta(days=1), "NG", "direct", 5)

    r = await api.get("/api/links/statsA/stats")
    body = r.json()
    assert body["by_country"] == [{"key": "NG", "clicks": 8}]
    assert body["total_clicks"] == 8


async def test_by_country_is_ordered_most_clicked_first(
    api: AsyncClient, db_session_factory
) -> None:
    link_id = await _make_link(db_session_factory, "statsB")
    await _insert_daily(db_session_factory, link_id, TODAY, "NG", "direct", 2)
    await _insert_daily(db_session_factory, link_id, TODAY, "US", "direct", 9)
    await _insert_daily(db_session_factory, link_id, TODAY, "GB", "direct", 5)

    r = await api.get("/api/links/statsB/stats")
    keys = [row["key"] for row in r.json()["by_country"]]
    assert keys == ["US", "GB", "NG"]


async def test_timeseries_is_ordered_chronologically_not_by_volume(
    api: AsyncClient, db_session_factory
) -> None:
    link_id = await _make_link(db_session_factory, "statsC")
    day1, day2, day3 = TODAY, TODAY + timedelta(days=1), TODAY + timedelta(days=2)
    await _insert_daily(db_session_factory, link_id, day3, "NG", "direct", 1)
    await _insert_daily(db_session_factory, link_id, day1, "NG", "direct", 1)
    await _insert_daily(db_session_factory, link_id, day2, "NG", "direct", 99)

    r = await api.get("/api/links/statsC/stats")
    days = [row["day"] for row in r.json()["timeseries"]]
    assert days == [str(day1), str(day2), str(day3)]


async def test_date_filter_excludes_rows_outside_the_range(
    api: AsyncClient, db_session_factory
) -> None:
    link_id = await _make_link(db_session_factory, "statsD")
    in_range = TODAY
    out_of_range = TODAY - timedelta(days=30)
    await _insert_daily(db_session_factory, link_id, in_range, "NG", "direct", 4)
    await _insert_daily(db_session_factory, link_id, out_of_range, "NG", "direct", 100)

    r = await api.get(f"/api/links/statsD/stats?start={in_range}&end={in_range}")
    assert r.status_code == 200
    assert r.json()["total_clicks"] == 4


async def test_start_after_end_is_422_not_a_500(api: AsyncClient, db_session_factory) -> None:
    await _make_link(db_session_factory, "statsE")
    r = await api.get(f"/api/links/statsE/stats?start={TODAY}&end={TODAY - timedelta(days=1)}")
    assert r.status_code == 422


async def test_live_clicks_reads_the_redis_counter_unfiltered_by_date(
    api: AsyncClient, db_session_factory, redis_conn
) -> None:
    link_id = await _make_link(db_session_factory, "statsF")
    old_row_day = TODAY - timedelta(days=60)
    await _insert_daily(db_session_factory, link_id, old_row_day, "NG", "direct", 2)
    await redis_conn.set(counter_key(link_id), 47)

    r = await api.get(f"/api/links/statsF/stats?start={TODAY}&end={TODAY}")
    body = r.json()
    assert body["total_clicks"] == 0  # respects the filter
    assert body["live_clicks"] == 47  # does not -- it is a live, unfiltered counter


async def test_referrer_breakdown_and_country_breakdown_are_independent(
    api: AsyncClient, db_session_factory
) -> None:
    link_id = await _make_link(db_session_factory, "statsG")
    await _insert_daily(db_session_factory, link_id, TODAY, "NG", "news.ycombinator.com", 3)
    await _insert_daily(db_session_factory, link_id, TODAY, "US", "news.ycombinator.com", 4)

    r = await api.get("/api/links/statsG/stats")
    body = r.json()
    assert len(body["by_country"]) == 2
    assert body["by_referrer"] == [{"key": "news.ycombinator.com", "clicks": 7}]
