from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import get_redis
from app.config import RESERVED_CODES, Settings, get_settings
from app.db import get_session
from app.net import client_ip
from app.redirect_service import record_click, referrer_host, resolve_link

router = APIRouter(tags=["redirect"])


@router.get(
    "/{code}",
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    response_class=RedirectResponse,
    responses={
        307: {"description": "Redirect to target URL"},
        404: {"description": "Unknown code"},
        410: {"description": "Link expired"},
    },
)
async def follow(
    code: str,
    request: Request,
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    if code.lower() in RESERVED_CODES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "link_not_found")

    link = await resolve_link(session, redis, code)

    response = RedirectResponse(url=link.target_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    background_tasks.add_task(
        record_click,
        redis,
        settings,
        link.id,
        referrer_host(request.headers.get("referer")),
        client_ip(request),
    )
    return response
