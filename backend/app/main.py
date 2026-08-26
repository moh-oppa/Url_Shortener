from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import links, redirect
from app.cache import redis_client
from app.config import get_settings
from app.db import engine
from app.errors import RateLimited, ShortenerError
from app.schemas import HealthOut, ReadyOut

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()
    await redis_client.aclose()


app = FastAPI(
    title="URL Shortener",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not settings.is_production else [settings.base_url],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


@app.exception_handler(ShortenerError)
async def shortener_error_handler(request: Request, exc: ShortenerError) -> JSONResponse:
    headers = {"Retry-After": str(exc.retry_after)} if isinstance(exc, RateLimited) else None
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code},
        headers=headers,
    )


@app.get("/health", response_model=HealthOut, tags=["ops"])
async def health() -> HealthOut:
    """Liveness. Must not touch dependencies, or a Redis hiccup restarts the app."""
    return HealthOut(status="ok")


@app.get("/health/ready", response_model=ReadyOut, tags=["ops"])
async def ready() -> ReadyOut:
    """Readiness. This one *does* check dependencies -- used as the deploy gate."""
    pg_ok = False
    redis_ok = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        pg_ok = True
    except Exception:  # noqa: BLE001 - readiness must never raise
        pg_ok = False
    try:
        redis_ok = bool(await redis_client.ping())
    except Exception:  # noqa: BLE001
        redis_ok = False

    return ReadyOut(
        status="ok" if (pg_ok and redis_ok) else "degraded",
        postgres=pg_ok,
        redis=redis_ok,
    )


app.include_router(links.router)
app.include_router(redirect.router)