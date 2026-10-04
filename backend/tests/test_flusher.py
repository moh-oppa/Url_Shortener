from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cache import CLICK_GROUP, CLICK_STREAM
from app.config import Settings
from app.flusher import (
    ensure_consumer_group,
    purge_old_events,
    run_forever,
    run_once,
)
from app.geoip import CountryResolver
from app.models import ClickDaily, ClickEvent, Link

FAST = Settings(flusher_batch_size=1000, flusher_block_ms=200, flusher_claim_idle_ms=0)
resolver = CountryResolver(None)


async def _make_link(session_factory: async_sessionmaker[AsyncSession], code: str) -> int:
    async with session_factory() as session:
        link = Link(code=code, target_url="https://example.com", is_custom=True)
        session.add(link)
        await session.commit()
        await session.refresh(link)
        return link.id


def _click_fields(link_id: int, referrer: str = "direct", client_ip: str = "8.8.8.8") -> dict:
    return {
        "link_id": str(link_id),
        "referrer_host": referrer,
        "client_ip": client_ip,
        "clicked_at": datetime.now(UTC).isoformat(),
    }


async def test_a_single_click_is_written_and_acked(redis_conn, db_session_factory) -> None:
    link_id = await _make_link(db_session_factory, "flush001")
    await ensure_consumer_group(redis_conn)
    await redis_conn.xadd(CLICK_STREAM, _click_fields(link_id))

    n = await run_once(redis_conn, db_session_factory, resolver, FAST, "test-consumer")
    assert n == 1

    async with db_session_factory() as session:
        rows = (
            (await session.execute(select(ClickEvent).where(ClickEvent.link_id == link_id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].referrer_host == "direct"

        daily = (
            (await session.execute(select(ClickDaily).where(ClickDaily.link_id == link_id)))
            .scalars()
            .one()
        )
        assert daily.clicks == 1

    pending = await redis_conn.xpending(CLICK_STREAM, CLICK_GROUP)
    assert pending["pending"] == 0


async def test_same_bucket_events_aggregate_into_one_daily_row(
    redis_conn, db_session_factory
) -> None:
    link_id = await _make_link(db_session_factory, "flush002")
    await ensure_consumer_group(redis_conn)
    for _ in range(3):
        await redis_conn.xadd(CLICK_STREAM, _click_fields(link_id, referrer="news.ycombinator.com"))

    n = await run_once(redis_conn, db_session_factory, resolver, FAST, "test-consumer")
    assert n == 3

    async with db_session_factory() as session:
        rows = (
            (await session.execute(select(ClickDaily).where(ClickDaily.link_id == link_id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].clicks == 3


async def test_a_second_flush_increments_rather_than_overwrites(
    redis_conn, db_session_factory
) -> None:
    link_id = await _make_link(db_session_factory, "flush003")
    await ensure_consumer_group(redis_conn)

    await redis_conn.xadd(CLICK_STREAM, _click_fields(link_id))
    await redis_conn.xadd(CLICK_STREAM, _click_fields(link_id))
    await run_once(redis_conn, db_session_factory, resolver, FAST, "test-consumer")

    await redis_conn.xadd(CLICK_STREAM, _click_fields(link_id))
    await run_once(redis_conn, db_session_factory, resolver, FAST, "test-consumer")

    async with db_session_factory() as session:
        daily = (
            (await session.execute(select(ClickDaily).where(ClickDaily.link_id == link_id)))
            .scalars()
            .one()
        )
        assert daily.clicks == 3


async def test_malformed_entry_is_dropped_not_left_stuck(redis_conn, db_session_factory) -> None:
    link_id = await _make_link(db_session_factory, "flush004")
    await ensure_consumer_group(redis_conn)
    await redis_conn.xadd(CLICK_STREAM, {"referrer_host": "direct"})
    await redis_conn.xadd(CLICK_STREAM, _click_fields(link_id))

    n = await run_once(redis_conn, db_session_factory, resolver, FAST, "test-consumer")
    assert n == 2

    async with db_session_factory() as session:
        rows = (await session.execute(select(ClickEvent))).scalars().all()
        assert len(rows) == 1

    pending = await redis_conn.xpending(CLICK_STREAM, CLICK_GROUP)
    assert pending["pending"] == 0


async def test_crash_before_ack_is_recovered_by_a_different_consumer(
    redis_conn, db_session_factory
) -> None:
    link_id = await _make_link(db_session_factory, "flush005")
    await ensure_consumer_group(redis_conn)
    await redis_conn.xadd(CLICK_STREAM, _click_fields(link_id))

    await redis_conn.xreadgroup("flusher", "consumer-a", {CLICK_STREAM: ">"}, count=10)

    pending_before = await redis_conn.xpending(CLICK_STREAM, CLICK_GROUP)
    assert pending_before["pending"] == 1

    n = await run_once(redis_conn, db_session_factory, resolver, FAST, "consumer-b")
    assert n == 1

    async with db_session_factory() as session:
        rows = (
            (await session.execute(select(ClickEvent).where(ClickEvent.link_id == link_id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1

    pending_after = await redis_conn.xpending(CLICK_STREAM, CLICK_GROUP)
    assert pending_after["pending"] == 0


async def test_a_failed_flush_leaves_the_entry_pending_for_retry(
    redis_conn, db_session_factory, monkeypatch
) -> None:

    import app.flusher as flusher_module

    link_id = await _make_link(db_session_factory, "flush006")
    await ensure_consumer_group(redis_conn)
    await redis_conn.xadd(CLICK_STREAM, _click_fields(link_id))

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated database outage")

    monkeypatch.setattr(flusher_module, "flush_batch", _boom)
    n = await run_once(redis_conn, db_session_factory, resolver, FAST, "test-consumer")
    assert n == 0

    pending = await redis_conn.xpending(CLICK_STREAM, CLICK_GROUP)
    assert pending["pending"] == 1

    monkeypatch.undo()
    n = await run_once(redis_conn, db_session_factory, resolver, FAST, "test-consumer")
    assert n == 1


async def test_purge_deletes_only_events_past_retention(db_session_factory) -> None:
    link_id = await _make_link(db_session_factory, "flush007")
    async with db_session_factory() as session:
        old = ClickEvent(
            link_id=link_id,
            clicked_at=datetime.now(UTC) - timedelta(days=200),
            country="US",
            referrer_host="direct",
        )
        recent = ClickEvent(
            link_id=link_id,
            clicked_at=datetime.now(UTC) - timedelta(days=1),
            country="US",
            referrer_host="direct",
        )
        session.add_all([old, recent])
        await session.commit()

    async with db_session_factory() as session:
        deleted = await purge_old_events(session, retention_days=90)
        assert deleted == 1

    async with db_session_factory() as session:
        remaining = (
            (await session.execute(select(ClickEvent).where(ClickEvent.link_id == link_id)))
            .scalars()
            .all()
        )
        assert len(remaining) == 1
        assert remaining[0].clicked_at > datetime.now(UTC) - timedelta(days=2)


async def test_ensure_consumer_group_is_safe_to_call_twice(redis_conn) -> None:
    await ensure_consumer_group(redis_conn)
    await ensure_consumer_group(redis_conn)


async def test_run_forever_returns_promptly_when_already_stopped(
    redis_conn, db_session_factory
) -> None:
    import asyncio

    stop_event = asyncio.Event()
    stop_event.set()
    await asyncio.wait_for(
        run_forever(redis_conn, db_session_factory, resolver, FAST, "test-consumer", stop_event),
        timeout=1.0,
    )


async def test_a_redis_error_during_shutdown_exits_cleanly_not_with_a_traceback(
    redis_conn, db_session_factory, monkeypatch
) -> None:

    import asyncio

    from redis.exceptions import TimeoutError as RedisTimeoutError

    import app.flusher as flusher_module

    stop_event = asyncio.Event()

    async def _simulate_signal_arriving_mid_read(*_args, **_kwargs):
        stop_event.set()
        raise RedisTimeoutError("Timeout reading from 127.0.0.1:6379")

    monkeypatch.setattr(flusher_module, "run_once", _simulate_signal_arriving_mid_read)

    await asyncio.wait_for(
        run_forever(redis_conn, db_session_factory, resolver, FAST, "test-consumer", stop_event),
        timeout=1.0,
    )


async def test_a_genuine_redis_outage_is_retried_not_fatal(
    redis_conn, db_session_factory, monkeypatch
) -> None:
    import asyncio

    from redis.exceptions import TimeoutError as RedisTimeoutError

    import app.flusher as flusher_module

    stop_event = asyncio.Event()
    attempts = 0

    async def _fail_once_then_stop(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RedisTimeoutError("Timeout reading from 127.0.0.1:6379")
        stop_event.set()
        return 0

    monkeypatch.setattr(flusher_module, "run_once", _fail_once_then_stop)

    await asyncio.wait_for(
        run_forever(redis_conn, db_session_factory, resolver, FAST, "test-consumer", stop_event),
        timeout=3.0,
    )
    assert attempts == 2


async def test_purge_touches_only_click_events_never_the_rollup(
    db_session_factory,
) -> None:
    """click_daily is the durable record; only the raw log is pruned."""
    link_id = await _make_link(db_session_factory, "flush008")
    async with db_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO click_daily (link_id, day, country, referrer_host, clicks) "
                "VALUES (:lid, CURRENT_DATE - INTERVAL '200 days', 'US', 'direct', 5)"
            ),
            {"lid": link_id},
        )
        await session.commit()
        deleted = await purge_old_events(session, retention_days=90)
        assert deleted == 0
        remaining = (
            await session.execute(select(ClickDaily).where(ClickDaily.link_id == link_id))
        ).scalar_one()
        assert remaining.clicks == 5
