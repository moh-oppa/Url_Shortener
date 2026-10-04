from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

RESERVED_CODES: frozenset[str] = frozenset(
    {
        "api",
        "health",
        "static",
        "assets",
        "docs",
        "redoc",
        "openapi.json",
        "favicon.ico",
        "robots.txt",
        "admin",
        "login",
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    debug: bool = False

    base_url: str = "http://localhost:8000"

    trust_proxy: bool = False

    database_url: str = "postgresql+asyncpg://shortener:shortener@localhost:5432/shortener"
    redis_url: str = "redis://localhost:6379/0"

    code_length: int = Field(default=7, ge=4, le=16)
    code_max_attempts: int = Field(default=5, ge=1, le=20)

    create_rate_limit: int = Field(default=20, ge=1)
    create_rate_window_seconds: int = Field(default=3600, ge=1)

    link_cache_ttl_seconds: int = Field(default=3600, ge=1)

    link_negative_cache_ttl_seconds: int = Field(default=60, ge=1)
    click_stream_maxlen: int = Field(default=100_000, ge=1)

    flusher_batch_size: int = Field(default=1000, ge=1)
    flusher_block_ms: int = Field(default=5000, ge=1)

    flusher_claim_idle_ms: int = Field(default=60_000, ge=0)
    click_events_retention_days: int = Field(default=90, ge=1)

    geoip_db_path: str | None = None

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
