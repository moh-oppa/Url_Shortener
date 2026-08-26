from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.config import RESERVED_CODES
from app.net import client_ip

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
async def follow(code: str, request: Request) -> RedirectResponse:
    if code.lower() in RESERVED_CODES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "link_not_found")
    _ = client_ip(request), request.headers.get("referer")
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "not implemented until phase 2")