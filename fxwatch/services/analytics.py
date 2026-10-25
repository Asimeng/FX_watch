"""Descriptive statistics for a rate series (used by the History page and alert emails)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from fxwatch.domain.models import Condition


@dataclass(frozen=True)
class SeriesStats:
    first: float
    latest: float
    low: float
    high: float
    mean: float
    change_pct: float
    volatility_annual_pct: float | None  # stdev of daily log returns, annualised
    percentile: float  # share of days in the window with a lower rate than today (0-100)
    observations: int


def describe(series: pd.Series) -> SeriesStats | None:
    s = series.dropna().astype(float)
    if s.empty:
        return None
    latest = float(s.iloc[-1])
    first = float(s.iloc[0])
    log_returns = (s / s.shift(1)).apply(math.log).dropna()
    vol = float(log_returns.std() * math.sqrt(252) * 100) if len(log_returns) >= 10 else None
    return SeriesStats(
        first=first,
        latest=latest,
        low=float(s.min()),
        high=float(s.max()),
        mean=float(s.mean()),
        change_pct=(latest / first - 1) * 100 if first else 0.0,
        volatility_annual_pct=vol,
        percentile=float((s < latest).mean() * 100),
        observations=len(s),
    )


def share_meeting(series: pd.Series, condition: Condition, threshold: float) -> float | None:
    """Percentage of days on which a level condition would have been met."""
    s = series.dropna().astype(float)
    if s.empty or condition is Condition.CROSS:
        return None
    met = s >= threshold if condition is Condition.ABOVE else s <= threshold
    return float(met.mean() * 100)


def crossings(series: pd.Series, threshold: float) -> int:
    """How many times the series crossed the threshold."""
    s = series.dropna().astype(float)
    side = (s >= threshold).astype(int)
    return int((side.diff().abs() == 1).sum())


def moving_average(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=max(2, window // 2)).mean()
