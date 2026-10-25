"""ORM models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from fxwatch.db.types import DecimalString, UTCDateTime, utcnow

BigId = BigInteger().with_variant(Integer, "sqlite")

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class RateObservationRow(Base):
    __tablename__ = "rate_observations"
    __table_args__ = (
        UniqueConstraint("source_id", "rate_date", "currency", name="uq_rate_obs_key"),
        Index("ix_rate_obs_lookup", "source_id", "currency", "rate_date"),
        Index("ix_rate_obs_date", "rate_date"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(32))
    rate_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    value: Mapped[Decimal] = mapped_column(DecimalString)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SourceStatusRow(Base):
    __tablename__ = "source_status"

    source_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    latest_rate_date: Mapped[date | None] = mapped_column(Date)


class FetchRunRow(Base):
    __tablename__ = "fetch_runs"
    __table_args__ = (Index("ix_fetch_runs_source_started", "source_id", "started_at"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))  # latest | backfill
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    rows_received: Mapped[int] = mapped_column(Integer, default=0)
    rows_inserted: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class SubscriberRow(Base):
    __tablename__ = "subscribers"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Bumping the version invalidates every management link issued so far.
    token_version: Mapped[int] = mapped_column(Integer, default=1)

    alerts: Mapped[list[AlertRow]] = relationship(
        back_populates="subscriber", cascade="all, delete-orphan", passive_deletes=True
    )


class AlertRow(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_status", "status"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    subscriber_id: Mapped[int] = mapped_column(ForeignKey("subscribers.id", ondelete="CASCADE"))
    base: Mapped[str] = mapped_column(String(3))
    quote: Mapped[str] = mapped_column(String(3))
    condition: Mapped[str] = mapped_column(String(16))
    threshold: Mapped[Decimal] = mapped_column(DecimalString)
    mode: Mapped[str] = mapped_column(String(16))
    source_preference: Mapped[str] = mapped_column(String(32), default="auto")
    label: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16))
    cooldown_hours: Mapped[int] = mapped_column(Integer, default=24)
    rearm_margin_pct: Mapped[Decimal] = mapped_column(DecimalString, default=Decimal("0.5"))

    armed: Mapped[bool] = mapped_column(Boolean, default=True)
    last_rate: Mapped[Decimal | None] = mapped_column(DecimalString)
    last_rate_date: Mapped[date | None] = mapped_column(Date)
    last_source_id: Mapped[str | None] = mapped_column(String(32))
    last_evaluated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_triggered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    trigger_count: Mapped[int] = mapped_column(Integer, default=0)
    hold_reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    subscriber: Mapped[SubscriberRow] = relationship(back_populates="alerts")

    @property
    def pair(self) -> str:
        return f"{self.base}/{self.quote}"


class NotificationRow(Base):
    """Outbox: every email is written here first, then delivered (and retried) from here."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_status", "status"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32))
    dedupe_key: Mapped[str] = mapped_column(String(128), unique=True)
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("alerts.id", ondelete="SET NULL"))
    to_email: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(200))
    # Bodies are cleared once delivered, so the outbox doesn't keep live links around.
    body_text: Mapped[str | None] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(Text)
    unsubscribe_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class RateLimitEventRow(Base):
    __tablename__ = "rate_limit_events"
    __table_args__ = (Index("ix_rate_limit_key_created", "key", "created_at"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
