from datetime import date
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import get_redis
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import LinkNotFound
from app.net import client_ip
from app.schemas import ErrorOut, LinkCreate, LinkOut, LinkStats, StatsQuery
from app.services import create_link as create_link_service
from app.services import get_link_by_code, to_out
from app.stats_service import get_link_stats

router = APIRouter(prefix="/api/links", tags=["links"])


@router.post(
    "",
    response_model=LinkOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ErrorOut, "description": "Custom alias already taken"},
        429: {"model": ErrorOut, "description": "Per-IP creation limit exceeded"},
    },
)
async def create_link(
    payload: LinkCreate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LinkOut:
    link = await create_link_service(session, payload, settings, owner_ip=client_ip(request))
    return to_out(link, settings)


@router.get(
    "/{code}",
    response_model=LinkOut,
    responses={404: {"model": ErrorOut}},
)
async def get_link(
    code: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LinkOut:
    link = await get_link_by_code(session, code)
    if link is None:
        raise LinkNotFound(f"no link with code '{code}'")
    return to_out(link, settings)


@router.get(
    "/{code}/stats",
    response_model=LinkStats,
    responses={404: {"model": ErrorOut}, 422: {"model": ErrorOut}},
)
async def get_stats(
    code: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> LinkStats:
    try:
        StatsQuery(start=start, end=end)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    link = await get_link_by_code(session, code)
    if link is None:
        raise LinkNotFound(f"no link with code '{code}'")

    return await get_link_stats(session, redis, link, start, end)
