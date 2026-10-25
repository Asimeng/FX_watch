from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pandas as pd
import pytest

from fxwatch.domain.crossrate import cross_rate, format_rate, pct_difference
from fxwatch.domain.models import Condition
from fxwatch.domain.rules import RuleState, evaluate
from fxwatch.services import analytics

NOW = datetime(2026, 10, 26, tzinfo=UTC)


def test_cross_rate_through_base():
    values = {"EUR": D(1), "ZAR": D("18.5777"), "GHS": D("13.0731")}
    assert cross_rate(values, "EUR", "ZAR") == D("18.5777")
    assert cross_rate(values, "ZAR", "GHS") == D("13.0731") / D("18.5777")
    assert cross_rate(values, "GHS", "GHS") == 1


def test_cross_rate_missing_leg():
    with pytest.raises(KeyError):
        cross_rate({"EUR": D(1)}, "EUR", "ZAR")


def test_pct_difference_is_symmetric():
    assert pct_difference(D(100), D(102)) == pct_difference(D(102), D(100))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (18.57771, "18.5777"),
        (20268.06, "20,268.06"),
        (0.0000493, "0.0000493"),
        (0.70403, "0.70403"),
    ],
)
def test_format_rate(value, expected):
    assert format_rate(value) == expected


def state(cond, threshold="20", **kw):
    return RuleState(condition=cond, threshold=D(threshold), **kw)


def test_above_fires_and_disarms():
    out = evaluate(state(Condition.ABOVE), D("20.1"), NOW)
    assert out.fire and not out.armed


def test_above_not_met():
    out = evaluate(state(Condition.ABOVE), D("19.9"), NOW)
    assert not out.fire and out.armed


def test_below_fires_at_exact_threshold():
    assert evaluate(state(Condition.BELOW), D("20"), NOW).fire


def test_disarmed_alert_needs_hysteresis_to_rearm():
    s = state(Condition.ABOVE, armed=False)
    assert not evaluate(s, D("19.95"), NOW).armed  # within 0.5% margin
    assert evaluate(s, D("19.89"), NOW).armed  # beyond margin → re-armed, but no fire
    assert not evaluate(s, D("19.89"), NOW).fire


def test_cooldown_blocks_repeat():
    s = state(
        Condition.ABOVE, last_triggered_at=NOW - timedelta(hours=2), cooldown=timedelta(hours=24)
    )
    out = evaluate(s, D("21"), NOW)
    assert not out.fire and out.armed


def test_cross_requires_previous_rate_and_side_change():
    assert not evaluate(state(Condition.CROSS), D("21"), NOW).fire
    up = evaluate(state(Condition.CROSS, last_rate=D("19.9")), D("20.1"), NOW)
    assert up.fire and up.armed
    down = evaluate(state(Condition.CROSS, last_rate=D("20.1")), D("19.9"), NOW)
    assert down.fire
    same_side = evaluate(state(Condition.CROSS, last_rate=D("20.5")), D("20.1"), NOW)
    assert not same_side.fire


def test_series_stats():
    s = pd.Series([10.0, 11.0, 12.0, 11.0, 13.0], index=pd.date_range("2026-01-01", periods=5))
    st = analytics.describe(s)
    assert st and st.latest == 13 and st.low == 10 and st.high == 13
    assert st.change_pct == pytest.approx(30.0)
    assert st.percentile == 80.0
    assert analytics.share_meeting(s, Condition.ABOVE, 12) == 40.0
    assert analytics.crossings(s, 11.5) == 3
