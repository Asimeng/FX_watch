"""Smoke tests: every Streamlit page renders without exceptions against seeded data."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from fxwatch.config import get_settings
from fxwatch.db import session_scope
from fxwatch.domain.models import Condition
from fxwatch.services.alerts import AlertInput, AlertService
from tests.conftest import seed_series

ENTRYPOINT = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")

PAGES = [
    "app/views/dashboard.py",
    "app/views/converter.py",
    "app/views/history.py",
    "app/views/new_alert.py",
    "app/views/manage.py",
    "app/views/sources.py",
    "app/views/confirm.py",
]


@pytest.fixture
def app_env(db, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db.database_url)
    monkeypatch.setenv("SECRET_KEY", db.secret_key)
    monkeypatch.setenv("MAIL_BACKEND", "console")
    get_settings.cache_clear()
    from app.ui import data

    today = data.today()
    n = 60
    seed_series(
        db,
        "ecb",
        {
            "EUR": ["1"] * n,
            "ZAR": [f"{18 + i / 100:.2f}" for i in range(n)],
            "USD": ["1.12"] * n,
            "GBP": ["0.84"] * n,
        },
        today,
    )
    seed_series(
        db,
        "erapi",
        {
            "USD": ["1"] * 2,
            "EUR": ["0.89", "0.9"],
            "ZAR": ["16.6", "16.7"],
            "GHS": ["11.7", "11.8"],
        },
        today,
    )
    yield db
    get_settings.cache_clear()


def run(page: str, **query: str) -> AppTest:
    at = AppTest.from_file(ENTRYPOINT, default_timeout=30)
    for k, v in query.items():
        at.query_params[k] = v
    at.run()
    if page != PAGES[0]:
        at.switch_page(page)
        for k, v in query.items():
            at.query_params[k] = v
        at.run()
    return at


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(app_env, page):
    at = run(page)
    assert not at.exception, at.exception


def test_dashboard_shows_watchlist(app_env):
    at = run(PAGES[0])
    labels = [m.label for m in at.metric]
    assert any("EUR" in label and "ZAR" in label for label in labels)


def test_create_alert_flow_in_ui(app_env):
    at = run("app/views/new_alert.py")
    [email] = [t for t in at.text_input if t.label == "Email address"]
    email.set_value("ui-test@example.com")
    at.checkbox[0].check()
    [create] = [b for b in at.button if b.label == "Create alert"]
    create.click()
    at.run()
    assert not at.exception, at.exception
    assert any("confirmation link" in s.value for s in at.success), [e.value for e in at.error]


def test_manage_page_with_token(app_env):
    settings = get_settings()
    with session_scope(settings.database_url) as s:
        svc = AlertService(s, settings)
        a = svc.create_unconfirmed(
            "owner@example.com", AlertInput("EUR", "ZAR", Condition.ABOVE, Decimal("25")), None
        )
        url = svc.manage_url(a.subscriber)
    at = run("app/views/manage.py", token=url.split("token=")[1])
    assert not at.exception, at.exception
    assert any("ow" in c.value and "example.com" in c.value for c in at.caption)
    assert not at.error


def test_history_handles_unknown_pair(app_env):
    at = run("app/views/history.py", base="EUR", quote="NGN")
    assert not at.exception, at.exception


def test_history_explains_short_coverage(app_env):
    # The seeded data covers only 60 days, so a 2-year range must say so.
    at = run("app/views/history.py", base="EUR", quote="ZAR")
    at.segmented_control[0].set_value("2Y").run()
    assert not at.exception, at.exception
    assert any("starts on" in i.value for i in at.info)
