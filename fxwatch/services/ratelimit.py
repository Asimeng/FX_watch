"""Sliding-window rate limiting backed by the database (works across app replicas)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from fxwatch.db.models import RateLimitEventRow


def hit(session: Session, key: str, limit: int, window: timedelta, now: datetime) -> bool:
    """Record an attempt for `key`. Returns False (and records nothing) if over the limit."""
    count = session.scalar(
        select(func.count())
        .select_from(RateLimitEventRow)
        .where(RateLimitEventRow.key == key, RateLimitEventRow.created_at >= now - window)
    )
    if (count or 0) >= limit:
        return False
    session.add(RateLimitEventRow(key=key, created_at=now))
    session.flush()
    return True


def prune(session: Session, older_than: datetime) -> int:
    result = session.execute(
        delete(RateLimitEventRow).where(RateLimitEventRow.created_at < older_than)
    )
    return int(getattr(result, "rowcount", 0) or 0)
