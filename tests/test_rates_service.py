from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D

from fxwatch.db import session_scope
from fxwatch.services import rates
from tests.conftest import TODAY, seed, seed_series


def test_store_is_idempotent(db):
    seed(db, "ecb", TODAY, {"EUR": "1", "ZAR": "18.5"})
    seed(db, "ecb", TODAY, {"EUR": "1", "ZAR": "18.5"})
    with session_scope(db.database_url) as s:
        assert rates.observation_counts(s) == {"ecb": 2}


def test_priority_and_freshness(db):
    seed(db, "ecb", TODAY - timedelta(days=1), {"EUR": "1", "ZAR": "18.50"})
    seed(db, "erapi", TODAY, {"USD": "1", "EUR": "0.9", "ZAR": "16.65", "GHS": "11.7"})
    with session_scope(db.database_url) as s:
        snaps = rates.load_snapshots(s, TODAY)
    q = rates.get_quote(snaps, "EUR", "ZAR", TODAY)
    assert q and q.source_id == "ecb" and not q.derived  # official source wins
    g = rates.get_quote(snaps, "ZAR", "GHS", TODAY)
    assert g and g.source_id == "erapi" and g.derived  # only aggregator covers GHS
    assert g.rate == D("11.7") / D("16.65")

    stale = rates.get_quote(snaps, "EUR", "ZAR", TODAY + timedelta(days=10))
    assert stale is None


def test_previous_rate_for_day_change(db):
    seed_series(db, "ecb", {"EUR": ["1", "1"], "ZAR": ["18.0", "18.36"]}, TODAY)
    with session_scope(db.database_url) as s:
        snaps = rates.load_snapshots(s, TODAY)
    q = rates.get_quote(snaps, "EUR", "ZAR", TODAY)
    assert q and rates.previous_rate(snaps, q) == D("18.0")


def test_cross_check_flags_outlier(db):
    seed(db, "ecb", TODAY, {"EUR": "1", "ZAR": "18.50"})
    seed(db, "boc", TODAY, {"CAD": "1", "EUR": "0.64", "ZAR": "11.84"})  # 18.50
    seed(db, "erapi", TODAY, {"USD": "1", "EUR": "0.9", "ZAR": "18.0"})  # 20.0, the outlier
    seed(db, "currencyapi", TODAY, {"EUR": "1", "ZAR": "18.52"})
    with session_scope(db.database_url) as s:
        snaps = rates.load_snapshots(s, TODAY)
    quotes = {q.source_id: q for q in rates.quotes_for_pair(snaps, "EUR", "ZAR", TODAY)}
    assert list(quotes) == ["ecb", "boc", "erapi", "currencyapi"]

    # ECB vs median(18.50, 20.00, 18.52) = 18.52 → fine
    assert rates.cross_check(list(quotes.values()), quotes["ecb"], tolerance_pct=2.0).ok
    # erapi vs median(18.50, 18.50, 18.52) = 18.50 → ~7.8% off
    bad = rates.cross_check(list(quotes.values()), quotes["erapi"], tolerance_pct=2.0)
    assert not bad.ok and bad.max_deviation_pct is not None and bad.max_deviation_pct > 7


def test_history_prefers_official_with_comparable_coverage(db):
    business = ["18.0", "18.1", "18.2", "18.3", "18.4"]
    seed_series(db, "ecb", {"EUR": ["1"] * 5, "ZAR": business}, TODAY)
    seed_series(db, "currencyapi", {"EUR": ["1"] * 7, "ZAR": ["18"] * 7}, TODAY)
    with session_scope(db.database_url) as s:
        h = rates.history(s, "EUR", "ZAR", TODAY - timedelta(days=30), TODAY)
        assert h.source_id == "ecb" and len(h.series) == 5
        assert rates.history_sources(s, "EUR", "ZAR") == ["ecb", "currencyapi"]
