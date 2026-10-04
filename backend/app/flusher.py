import asyncio
import logging
import os
import signal
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import delete, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.cache import CLICK_GROUP, CLICK_STREAM
from app.config import Settings, get_settings
from app.geoip import CountryResolver
from app.models import ClickDaily, ClickEvent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

StreamEntry = tuple[str, dict[str, str]]


@dataclass(frozen=True)
class ParsedClick:
    link_id: int
    clicked_at: datetime
    referrer_host: str
    client_ip: str


def _parse_entry(entry_id: str, fields: dict[str, str]) -> ParsedClick | None:
    try:
        return ParsedClick(
            link_id=int(fields["link_id"]),
            clicked_at=datetime.fromisoformat(fields["clicked_at"]),
            referrer_host=fields.get("referrer_host") or "direct",
            client_ip=fields.get("client_ip", ""),
        )
    except (KeyError, ValueError) as exc:
        logger.warning("dropping malformed click stream entry %s: %s", entry_id, exc)
        return None


async def ensure_consumer_group(redis: aioredis.Redis) -> None:
    try:
        await redis.xgroup_create(name=CLICK_STREAM, groupname=CLICK_GROUP, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def reclaim_pending(
    redis: aioredis.Redis, consumer_name: str, settings: Settings
) -> list[StreamEntry]:
    try:
        _cursor, claimed, _deleted = await redis.xautoclaim(
            name=CLICK_STREAM,
            groupname=CLICK_GROUP,
            consumername=consumer_name,
            min_idle_time=settings.flusher_claim_idle_ms,
            start_id="0-0",
            count=settings.flusher_batch_size,
        )
    except ResponseError as exc:
        if "NOGROUP" in str(exc):
            return []
        raise
    return claimed


async def read_new(
    redis: aioredis.Redis, consumer_name: str, settings: Settings
) -> list[StreamEntry]:
    result = await redis.xreadgroup(
        groupname=CLICK_GROUP,
        consumername=consumer_name,
        streams={CLICK_STREAM: ">"},
        count=settings.flusher_batch_size,
        block=settings.flusher_block_ms,
    )
    if not result:
        return []
    _stream_name, entries = result[0]
    return entries


async def flush_batch(
    session: AsyncSession, resolver: CountryResolver, parsed: list[ParsedClick]
) -> None:
    event_rows = [
        {
            "link_id": p.link_id,
            "clicked_at": p.clicked_at,
            "country": resolver.resolve(p.client_ip),
            "referrer_host": p.referrer_host,
        }
        for p in parsed
    ]
    await session.execute(insert(ClickEvent), event_rows)
    daily: dict[tuple[int, object, str, str], int] = {}
    for row in event_rows:
        key = (row["link_id"], row["clicked_at"].date(), row["country"], row["referrer_host"])
        daily[key] = daily.get(key, 0) + 1

    daily_rows = [
        {"link_id": link_id, "day": day, "country": country, "referrer_host": referrer, "clicks": n}
        for (link_id, day, country, referrer), n in daily.items()
    ]
    stmt = pg_insert(ClickDaily).values(daily_rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["link_id", "day", "country", "referrer_host"],
        set_={"clicks": ClickDaily.clicks + stmt.excluded.clicks},
    )
    await session.execute(stmt)
    await session.commit()


async def run_once(
    redis: aioredis.Redis,
    session_factory: async_sessionmaker[AsyncSession],
    resolver: CountryResolver,
    settings: Settings,
    consumer_name: str,
) -> int:
    reclaimed = await reclaim_pending(redis, consumer_name, settings)
    fresh = await read_new(redis, consumer_name, settings)
    entries = reclaimed + fresh
    if not entries:
        return 0

    parsed = [pc for eid, fields in entries if (pc := _parse_entry(eid, fields)) is not None]

    try:
        if parsed:
            async with session_factory() as session:
                await flush_batch(session, resolver, parsed)
    except Exception:
        logger.exception("flush failed for a batch of %d event(s); will retry", len(parsed))
        return 0

    ack_ids = [eid for eid, _ in entries]
    await redis.xack(CLICK_STREAM, CLICK_GROUP, *ack_ids)
    return len(entries)


async def purge_old_events(session: AsyncSession, retention_days: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    result = await session.execute(delete(ClickEvent).where(ClickEvent.clicked_at < cutoff))
    await session.commit()
    return result.rowcount


async def run_forever(
    redis: aioredis.Redis,
    session_factory: async_sessionmaker[AsyncSession],
    resolver: CountryResolver,
    settings: Settings,
    consumer_name: str,
    stop_event: asyncio.Event,
) -> None:
    await ensure_consumer_group(redis)
    last_purge = datetime.now(UTC)

    while not stop_event.is_set():
        try:
            n = await run_once(redis, session_factory, resolver, settings, consumer_name)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            if stop_event.is_set():
                logger.info("redis read interrupted by shutdown, exiting cleanly")
                break
            logger.warning("transient redis error, retrying in 1s: %s", exc)
            await asyncio.sleep(1)
            continue

        if n:
            logger.info("flushed %d click event(s)", n)

        if datetime.now(UTC) - last_purge > timedelta(hours=1):
            async with session_factory() as session:
                deleted = await purge_old_events(session, settings.click_events_retention_days)
            if deleted:
                logger.info(
                    "purged %d event(s) past %d-day retention",
                    deleted,
                    settings.click_events_retention_days,
                )
            last_purge = datetime.now(UTC)


async def main() -> None:
    settings = get_settings()
    redis = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=(settings.flusher_block_ms / 1000) + 10,
        socket_connect_timeout=5,
    )
    engine = create_async_engine(settings.database_url, pool_size=2, max_overflow=2)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    resolver = CountryResolver(settings.geoip_db_path)
    consumer_name = f"{socket.gethostname()}-{os.getpid()}"

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    logger.info("flusher starting as consumer %s", consumer_name)
    try:
        await run_forever(redis, session_factory, resolver, settings, consumer_name, stop_event)
    finally:
        logger.info("flusher shutting down")
        resolver.close()
        await engine.dispose()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
