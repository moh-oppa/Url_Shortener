import os
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

BACKEND = Path(__file__).resolve().parents[1]

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:1/0")
os.environ.setdefault("BASE_URL", "http://testserver")

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://shortener:shortener@localhost:5432/shortener_test",
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/1")

from app.cache import get_redis  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import get_session  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    """No database, no Redis. For contract, routing and health tests."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def settings_cache_reset():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def migrated_db() -> str:
    subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
        check=True,
        capture_output=True,
    )
    return TEST_DATABASE_URL


@pytest_asyncio.fixture
async def db_engine(migrated_db: str):
    engine = create_async_engine(migrated_db, poolclass=NullPool)
    # Truncate rather than drop and recreate: same isolation, far faster.
    # CASCADE follows the foreign keys into the click tables.
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE links RESTART IDENTITY CASCADE"))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def redis_conn():
    conn = aioredis.from_url(TEST_REDIS_URL, decode_responses=True)
    await conn.flushdb()
    yield conn
    await conn.aclose()


@pytest_asyncio.fixture
async def db_session_factory(db_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def api(db_engine, db_session_factory, redis_conn) -> AsyncClient:
    async def override_get_session():
        async with db_session_factory() as session:
            yield session

    def override_get_redis():
        return redis_conn

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_redis] = override_get_redis
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client
    app.dependency_overrides.clear()
