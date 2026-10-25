from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from fxwatch.config import Settings
from fxwatch.db import get_engine, session_scope, upgrade
from fxwatch.domain.models import RateObservation
from fxwatch.notify.mailer import ConsoleMailer
from fxwatch.services import rates

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
TODAY = NOW.date()


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _database_url(tmp_path: Path) -> str:
    """SQLite per test by default; CI also runs the suite against Postgres.

    Set TEST_DATABASE_URL to a disposable Postgres database to do the same locally.
    Its public schema is wiped before every test.
    """
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        return f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    url = Settings(database_url=url, _env_file=None).database_url  # type: ignore[call-arg]
    with get_engine(url).begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    return url


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=_database_url(tmp_path),
        secret_key="t" * 48,
        app_base_url="https://fx.example.com",
        mail_backend="console",
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
def db(settings: Settings) -> Iterator[Settings]:
    upgrade(settings.database_url)
    yield settings


@pytest.fixture
def mailer(settings: Settings) -> ConsoleMailer:
    return ConsoleMailer(settings)


def seed(settings: Settings, source_id: str, day: date, values: dict[str, str]) -> None:
    with session_scope(settings.database_url) as s:
        rates.store_observations(
            s, [RateObservation(source_id, day, code, Decimal(v)) for code, v in values.items()]
        )


def seed_series(
    settings: Settings, source_id: str, base_values: dict[str, list[str]], end: date
) -> None:
    """Seed consecutive days ending at `end` (lists are oldest → newest)."""
    length = len(next(iter(base_values.values())))
    for i in range(length):
        day = end - timedelta(days=length - 1 - i)
        seed(settings, source_id, day, {code: vals[i] for code, vals in base_values.items()})
