import re
from datetime import UTC, date, datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from app.config import RESERVED_CODES

ALIAS_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")

ALLOWED_SCHEMES = {"http", "https"}


class LinkCreate(BaseModel):
    target_url: HttpUrl
    custom_alias: str | None = Field(
        default=None,
        description="3-32 chars, [A-Za-z0-9_-]. Omit to get a generated code.",
    )
    expires_at: datetime | None = None

    @field_validator("target_url")
    @classmethod
    def _scheme_allowed(cls, v: HttpUrl) -> HttpUrl:
        if v.scheme not in ALLOWED_SCHEMES:
            raise ValueError(f"scheme must be one of {sorted(ALLOWED_SCHEMES)}")
        return v

    @field_validator("custom_alias")
    @classmethod
    def _alias_shape(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not ALIAS_PATTERN.match(v):
            raise ValueError("alias must be 3-32 chars of letters, digits, hyphen or underscore")
        if v.lower() in RESERVED_CODES:
            raise ValueError(f"'{v}' is reserved")
        return v

    @field_validator("expires_at")
    @classmethod
    def _expiry_in_future(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        if v.tzinfo is None:
            v = v.replace(tzinfo=UTC)
        if v <= datetime.now(UTC):
            raise ValueError("expires_at must be in the future")
        return v


class LinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    short_url: str
    target_url: str
    created_at: datetime
    expires_at: datetime | None = None


class CountBucket(BaseModel):
    key: str
    clicks: int


class TimeseriesPoint(BaseModel):
    day: date
    clicks: int


class LinkStats(BaseModel):
    code: str
    total_clicks: int
    live_clicks: int
    by_country: list[CountBucket] = Field(default_factory=list)
    by_referrer: list[CountBucket] = Field(default_factory=list)
    timeseries: list[TimeseriesPoint] = Field(default_factory=list)


class StatsQuery(BaseModel):
    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def _ordered(self) -> "StatsQuery":
        if self.start and self.end and self.start > self.end:
            raise ValueError("start must not be after end")
        return self


class ErrorOut(BaseModel):
    detail: str
    code: str | None = None


class HealthOut(BaseModel):
    status: str


class ReadyOut(BaseModel):
    status: str
    postgres: bool
    redis: bool
