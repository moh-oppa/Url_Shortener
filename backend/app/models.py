from datetime import UTC, date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

UNKNOWN_COUNTRY = "??"
DIRECT_REFERRER = "direct"


class Link(Base):
    __tablename__ = "links"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)

    target_url: Mapped[str] = mapped_column(Text, nullable=False)

    is_custom: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at <= (now or datetime.now(UTC))


class ClickEvent(Base):
    """Raw click log. Written in batches by the phase 3 flusher, trimmed on a
    retention schedule. The dashboard never queries this table."""

    __tablename__ = "click_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    link_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("links.id", ondelete="CASCADE"), nullable=False
    )
    clicked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    referrer_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ua_family: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (Index("ix_click_events_link_time", "link_id", "clicked_at"),)


class ClickDaily(Base):
    """Pre-aggregated rollup. This is what the dashboard reads, which is why
    stats latency stays flat as the raw event table grows."""

    __tablename__ = "click_daily"

    link_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("links.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    country: Mapped[str] = mapped_column(
        String(2), primary_key=True, server_default=UNKNOWN_COUNTRY
    )
    referrer_host: Mapped[str] = mapped_column(
        String(255), primary_key=True, server_default=DIRECT_REFERRER
    )
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
