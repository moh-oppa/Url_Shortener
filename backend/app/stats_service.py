from datetime import date

import redis.asyncio as aioredis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import counter_key
from app.models import ClickDaily, Link
from app.schemas import CountBucket, LinkStats, TimeseriesPoint


async def get_link_stats(
    session: AsyncSession,
    redis: aioredis.Redis,
    link: Link,
    start: date | None,
    end: date | None,
) -> LinkStats:
    conditions = [ClickDaily.link_id == link.id]
    if start is not None:
        conditions.append(ClickDaily.day >= start)
    if end is not None:
        conditions.append(ClickDaily.day <= end)

    clicks_sum = func.sum(ClickDaily.clicks)

    country_rows = (
        await session.execute(
            select(ClickDaily.country, clicks_sum)
            .where(*conditions)
            .group_by(ClickDaily.country)
            .order_by(clicks_sum.desc())
        )
    ).all()

    referrer_rows = (
        await session.execute(
            select(ClickDaily.referrer_host, clicks_sum)
            .where(*conditions)
            .group_by(ClickDaily.referrer_host)
            .order_by(clicks_sum.desc())
        )
    ).all()

    day_rows = (
        await session.execute(
            select(ClickDaily.day, clicks_sum)
            .where(*conditions)
            .group_by(ClickDaily.day)
            .order_by(ClickDaily.day)
        )
    ).all()

    by_country = [CountBucket(key=country, clicks=n) for country, n in country_rows]
    by_referrer = [CountBucket(key=referrer, clicks=n) for referrer, n in referrer_rows]
    timeseries = [TimeseriesPoint(day=day, clicks=n) for day, n in day_rows]
    total_clicks = sum(bucket.clicks for bucket in by_country)
    raw = await redis.get(counter_key(link.id))
    live_clicks = int(raw) if raw is not None else 0

    return LinkStats(
        code=link.code,
        total_clicks=total_clicks,
        live_clicks=live_clicks,
        by_country=by_country,
        by_referrer=by_referrer,
        timeseries=timeseries,
    )
