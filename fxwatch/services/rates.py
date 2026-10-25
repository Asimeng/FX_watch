"""Storing observations and answering "what is the rate for A→B?"."""

from __future__ import annotations

import logging
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from fxwatch.db.models import RateObservationRow
from fxwatch.domain.crossrate import cross_rate, pct_difference
from fxwatch.domain.models import PairQuote, RateObservation
from fxwatch.sources import SOURCE_CLASSES, SOURCE_INFO

log = logging.getLogger(__name__)

AUTO = "auto"
COMPARABLE_COVERAGE = 0.6
_CHUNK = 500


# --------------------------------------------------------------------------- writing


def store_observations(session: Session, rows: Sequence[RateObservation]) -> int:
    """Insert observations, ignoring ones already stored. Returns the number inserted."""
    if not rows:
        return 0
    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    inserted = 0
    for i in range(0, len(rows), _CHUNK):
        chunk = rows[i : i + _CHUNK]
        stmt = insert(RateObservationRow).values(
            [
                {
                    "source_id": r.source_id,
                    "rate_date": r.rate_date,
                    "currency": r.currency,
                    "value": r.value,
                }
                for r in chunk
            ]
        )
        result = session.execute(
            stmt.on_conflict_do_nothing(index_elements=["source_id", "rate_date", "currency"])
        )
        inserted += max(getattr(result, "rowcount", 0) or 0, 0)
    return inserted


def observation_counts(session: Session) -> dict[str, int]:
    stmt = select(RateObservationRow.source_id, func.count()).group_by(RateObservationRow.source_id)
    return {source_id: count for source_id, count in session.execute(stmt)}


# --------------------------------------------------------------------------- snapshots


@dataclass
class SourceSnapshot:
    """Latest (and previous) value per currency for one source."""

    source_id: str
    values: dict[str, Decimal] = field(default_factory=dict)
    dates: dict[str, date] = field(default_factory=dict)
    previous: dict[str, Decimal] = field(default_factory=dict)
    previous_dates: dict[str, date] = field(default_factory=dict)

    @property
    def latest_date(self) -> date | None:
        return max(self.dates.values()) if self.dates else None

    def is_fresh(self, code: str, today: date) -> bool:
        d = self.dates.get(code)
        return d is not None and (today - d).days <= SOURCE_INFO[self.source_id].max_age_days


Snapshots = dict[str, SourceSnapshot]


def load_snapshots(session: Session, today: date, lookback_days: int = 21) -> Snapshots:
    stmt = (
        select(
            RateObservationRow.source_id,
            RateObservationRow.currency,
            RateObservationRow.rate_date,
            RateObservationRow.value,
        )
        .where(RateObservationRow.rate_date >= today - timedelta(days=lookback_days))
        .order_by(RateObservationRow.rate_date)
    )
    snaps: Snapshots = {}
    for source_id, code, rate_date, value in session.execute(stmt):
        if source_id not in SOURCE_INFO:
            continue
        snap = snaps.setdefault(source_id, SourceSnapshot(source_id))
        if code in snap.values:
            snap.previous[code] = snap.values[code]
            snap.previous_dates[code] = snap.dates[code]
        snap.values[code] = value
        snap.dates[code] = rate_date
    return snaps


def available_currencies(snaps: Snapshots, today: date) -> set[str]:
    return {code for s in snaps.values() for code in s.values if s.is_fresh(code, today)}


def _quote_from(snap: SourceSnapshot, base: str, quote: str) -> PairQuote | None:
    try:
        rate = cross_rate(snap.values, base, quote)
    except (KeyError, ValueError):
        return None
    source_base = SOURCE_INFO[snap.source_id].base
    return PairQuote(
        base=base,
        quote=quote,
        rate=rate,
        rate_date=min(snap.dates[base], snap.dates[quote]),
        source_id=snap.source_id,
        derived=source_base not in (base, quote),
    )


def quotes_for_pair(snaps: Snapshots, base: str, quote: str, today: date) -> list[PairQuote]:
    """Fresh quotes for the pair from every source that can price it, best source first."""
    out = []
    for cls in SOURCE_CLASSES:
        snap = snaps.get(cls.info.id)
        if snap is None or not (snap.is_fresh(base, today) and snap.is_fresh(quote, today)):
            continue
        q = _quote_from(snap, base, quote)
        if q is not None:
            out.append(q)
    return out


def get_quote(
    snaps: Snapshots, base: str, quote: str, today: date, source: str = AUTO
) -> PairQuote | None:
    quotes = quotes_for_pair(snaps, base, quote, today)
    if source != AUTO:
        quotes = [q for q in quotes if q.source_id == source]
    return quotes[0] if quotes else None


def previous_rate(snaps: Snapshots, q: PairQuote) -> Decimal | None:
    """The pair's rate on the source's previous publication, for day-over-day change."""
    snap = snaps.get(q.source_id)
    if snap is None:
        return None
    prev = dict(snap.values)
    changed = False
    for code in (q.base, q.quote):
        # Only use the older value for a leg that has one; otherwise it hasn't moved.
        if code in snap.previous:
            prev[code] = snap.previous[code]
            changed = True
    if not changed:
        return None
    try:
        return cross_rate(prev, q.base, q.quote)
    except (KeyError, ValueError):
        return None


@dataclass(frozen=True)
class CrossCheck:
    ok: bool
    compared_with: list[str]
    max_deviation_pct: Decimal | None
    detail: str


def cross_check(
    quotes: Sequence[PairQuote], primary: PairQuote, tolerance_pct: float
) -> CrossCheck:
    """Compare the primary quote with the median of other sources published within 3 days."""
    others = [
        q
        for q in quotes
        if q.source_id != primary.source_id and abs((q.rate_date - primary.rate_date).days) <= 3
    ]
    if not others:
        return CrossCheck(True, [], None, "no independent source to compare with")
    reference = Decimal(statistics.median([q.rate for q in others]))
    deviation = pct_difference(primary.rate, reference)
    names = [q.source_id for q in others]
    if deviation > Decimal(str(tolerance_pct)):
        detail = (
            f"{primary.source_id} rate {primary.rate:.6g} deviates {deviation:.2f}% from "
            f"{', '.join(names)} ({reference:.6g}); tolerance {tolerance_pct}%"
        )
        return CrossCheck(False, names, deviation, detail)
    return CrossCheck(True, names, deviation, f"within {deviation:.2f}% of {', '.join(names)}")


# --------------------------------------------------------------------------- history


@dataclass(frozen=True)
class History:
    source_id: str | None
    series: pd.Series  # index: date, values: float rate


def _history_frame(
    session: Session, codes: Iterable[str], start: date, end: date, source: str | None
) -> pd.DataFrame:
    stmt = select(
        RateObservationRow.source_id,
        RateObservationRow.rate_date,
        RateObservationRow.currency,
        RateObservationRow.value,
    ).where(
        RateObservationRow.currency.in_(list(codes)),
        RateObservationRow.rate_date.between(start, end),
    )
    if source:
        stmt = stmt.where(RateObservationRow.source_id == source)
    rows = session.execute(stmt).all()
    return pd.DataFrame(rows, columns=["source_id", "rate_date", "currency", "value"])


def history(
    session: Session, base: str, quote: str, start: date, end: date, source: str = AUTO
) -> History:
    """Daily series for base→quote from a single source.

    With source="auto", picks the highest-priority source whose coverage of the window is
    comparable to the best-covered one. Official sources publish on business days only
    (~70% of calendar days), so they still win over sources that also publish weekends.
    """
    frame = _history_frame(session, {base, quote}, start, end, None if source == AUTO else source)
    if frame.empty:
        return History(None, pd.Series(dtype=float))

    series_by_source: dict[str, pd.Series] = {}
    for source_id, group in frame.groupby("source_id"):
        sid = str(source_id)
        if sid not in SOURCE_INFO:
            continue
        wide = group.pivot_table(
            index="rate_date", columns="currency", values="value", aggfunc="first"
        )
        if base not in wide or quote not in wide:
            continue
        wide = wide[[base, quote]].dropna()
        if wide.empty:
            continue
        s = (wide[quote].map(float) / wide[base].map(float)).sort_index()
        s.index = pd.to_datetime(s.index)
        series_by_source[sid] = s
    if not series_by_source:
        return History(None, pd.Series(dtype=float))
    most = max(len(s) for s in series_by_source.values())
    eligible = [sid for sid, s in series_by_source.items() if len(s) >= COMPARABLE_COVERAGE * most]
    chosen = min(eligible, key=lambda sid: SOURCE_INFO[sid].priority)
    return History(chosen, series_by_source[chosen])


def history_sources(session: Session, base: str, quote: str) -> list[str]:
    """Sources that have ever published both legs of the pair."""
    stmt = (
        select(RateObservationRow.source_id)
        .where(RateObservationRow.currency.in_([base, quote]))
        .group_by(RateObservationRow.source_id)
        .having(func.count(func.distinct(RateObservationRow.currency)) == len({base, quote}))
    )
    found = {sid for (sid,) in session.execute(stmt)}
    return [cls.info.id for cls in SOURCE_CLASSES if cls.info.id in found]
