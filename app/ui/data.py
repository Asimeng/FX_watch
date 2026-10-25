"""Cached data access for the UI. The UI never talks to the database any other way."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import Session

from fxwatch.config import Settings, get_settings
from fxwatch.db import session_scope, upgrade
from fxwatch.db.models import FetchRunRow, SourceStatusRow
from fxwatch.domain.models import PairQuote
from fxwatch.logs import configure_logging
from fxwatch.services import rates
from fxwatch.services.rates import AUTO, Snapshots


def settings() -> Settings:
    return get_settings()


@st.cache_resource(show_spinner=False)
def bootstrap() -> bool:
    """Configure logging and bring the schema up to date once per server process."""
    s = settings()
    configure_logging(s.log_level, s.log_format)
    upgrade(s.database_url)
    return True


@contextmanager
def db() -> Iterator[Session]:
    with session_scope(settings().database_url) as session:
        yield session


def today() -> date:
    return datetime.now(UTC).date()


@st.cache_data(ttl=300, show_spinner=False)
def snapshots(day: date) -> Snapshots:
    with db() as s:
        return rates.load_snapshots(s, day)


def current_snapshots() -> Snapshots:
    return snapshots(today())


def quote(base: str, quote_code: str, source: str = AUTO) -> PairQuote | None:
    return rates.get_quote(current_snapshots(), base, quote_code, today(), source)


def quotes(base: str, quote_code: str) -> list[PairQuote]:
    return rates.quotes_for_pair(current_snapshots(), base, quote_code, today())


def previous(q: PairQuote) -> float | None:
    prev = rates.previous_rate(current_snapshots(), q)
    return float(prev) if prev is not None else None


def available_codes() -> set[str]:
    return rates.available_currencies(current_snapshots(), today())


@st.cache_data(ttl=600, show_spinner=False)
def history(
    base: str, quote_code: str, start: date, end: date, source: str = AUTO
) -> tuple[str | None, pd.Series]:
    with db() as s:
        h = rates.history(s, base, quote_code, start, end, source)
    return h.source_id, h.series


@st.cache_data(ttl=600, show_spinner=False)
def history_sources(base: str, quote_code: str) -> list[str]:
    with db() as s:
        return rates.history_sources(s, base, quote_code)


@st.cache_data(ttl=120, show_spinner=False)
def source_status() -> dict[str, dict[str, Any]]:
    with db() as s:
        rows = s.scalars(select(SourceStatusRow)).all()
        return {
            r.source_id: {
                "last_attempt_at": r.last_attempt_at,
                "last_success_at": r.last_success_at,
                "last_error": r.last_error,
                "consecutive_failures": r.consecutive_failures,
                "latest_rate_date": r.latest_rate_date,
            }
            for r in rows
        }


@st.cache_data(ttl=120, show_spinner=False)
def recent_runs(limit: int = 40) -> pd.DataFrame:
    with db() as s:
        rows = s.scalars(
            select(FetchRunRow).order_by(FetchRunRow.started_at.desc()).limit(limit)
        ).all()
        return pd.DataFrame(
            [
                {
                    "Started": r.started_at,
                    "Source": r.source_id,
                    "Kind": r.kind,
                    "OK": r.ok,
                    "Rows": r.rows_received,
                    "New": r.rows_inserted,
                    "Seconds": (r.finished_at - r.started_at).total_seconds()
                    if r.finished_at
                    else None,
                    "Error": r.error,
                }
                for r in rows
            ]
        )


def client_ip() -> str | None:
    """Best-effort visitor IP for rate limiting (None when unavailable, e.g. in tests)."""
    try:
        ip = st.context.ip_address
    except Exception:
        return None
    return ip if isinstance(ip, str) and ip else None
