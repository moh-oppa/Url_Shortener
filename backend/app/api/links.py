from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.net import client_ip
from app.schemas import ErrorOut, LinkCreate, LinkOut, LinkStats, StatsQuery

router = APIRouter(prefix="/api/links", tags=["links"])

NOT_IMPLEMENTED = "not implemented until phase 1"


@router.post(
    "",
    response_model=LinkOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ErrorOut, "description": "Custom alias already taken"},
        429: {"model": ErrorOut, "description": "Per-IP creation limit exceeded"},
    },
)
async def create_link(payload: LinkCreate, request: Request) -> LinkOut:
    _ = payload, client_ip(request)
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, NOT_IMPLEMENTED)


@router.get(
    "/{code}",
    response_model=LinkOut,
    responses={404: {"model": ErrorOut}},
)
async def get_link(code: str) -> LinkOut:
    _ = code
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, NOT_IMPLEMENTED)


@router.get(
    "/{code}/stats",
    response_model=LinkStats,
    responses={404: {"model": ErrorOut}},
)
async def get_stats(
    code: str,
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> LinkStats:
    _ = code, StatsQuery(start=start, end=end)
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, NOT_IMPLEMENTED)