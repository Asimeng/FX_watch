"""Reusable widgets and formatting."""

from __future__ import annotations

from datetime import date

import streamlit as st

from app.ui import data
from fxwatch import currencies
from fxwatch.domain.crossrate import format_rate
from fxwatch.domain.models import PairQuote, Tier
from fxwatch.sources import SOURCE_INFO

CSS = """
<style>
  .block-container { padding-top: 2.2rem; max-width: 1240px; }
  .fx-hero { font-size: 2.3rem; font-weight: 700; line-height: 1.15; margin: .2rem 0 .1rem; }
  .fx-sub { color: var(--fx-muted, #6b7385); font-size: .92rem; }
  .fx-kicker { text-transform: uppercase; letter-spacing: .08em; font-size: .72rem;
               font-weight: 600; opacity: .7; margin-bottom: .1rem; }
  div[data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; }
  .fx-mono { font-variant-numeric: tabular-nums; }
</style>
"""

TIER_BADGE = {
    Tier.OFFICIAL: ("Official", "green"),
    Tier.AGGREGATOR: ("Aggregator", "blue"),
    Tier.COMMUNITY: ("Open data", "gray"),
}


def inject_css() -> None:
    st.html(CSS)


def page_header(title: str, subtitle: str | None = None, kicker: str | None = None) -> None:
    if kicker:
        st.html(f'<div class="fx-kicker">{kicker}</div>')
    st.title(title, anchor=False)
    if subtitle:
        st.caption(subtitle)


def currency_select(
    label: str, key: str, default: str, options: list[str] | None = None, **kwargs: object
) -> str:
    opts = options or [
        c
        for c in currencies.ordered_codes()
        if c in (data.available_codes() or currencies.CURRENCIES)
    ]
    if key not in st.session_state and default in opts:
        st.session_state[key] = default
    return st.selectbox(  # type: ignore[no-any-return]
        label,
        opts,
        key=key,
        format_func=lambda c: currencies.get(c).label,
        **kwargs,
    )


def pair_picker(
    prefix: str, default_base: str = "EUR", default_quote: str = "ZAR"
) -> tuple[str, str]:
    """Two currency selectors with a swap button between them."""
    kb, kq = f"{prefix}_base", f"{prefix}_quote"

    def _swap() -> None:
        st.session_state[kb], st.session_state[kq] = st.session_state[kq], st.session_state[kb]

    left, mid, right = st.columns([10, 1.4, 10], vertical_alignment="bottom")
    with left:
        base = currency_select("From", kb, default_base)
    with mid:
        st.button(
            "⇄", key=f"{prefix}_swap", on_click=_swap, help="Swap currencies", width="stretch"
        )
    with right:
        quote = currency_select("To", kq, default_quote)
    return base, quote


def source_badge(source_id: str) -> None:
    info = SOURCE_INFO[source_id]
    text, color = TIER_BADGE[info.tier]
    st.badge(f"{text} · {info.name}", color=color)  # type: ignore[arg-type]


def provenance(q: PairQuote) -> str:
    info = SOURCE_INFO[q.source_id]
    via = f" · cross rate via {info.base}" if q.derived else ""
    return f"{info.name} · {q.rate_date:%a %d %b %Y}{via}"


def freshness(d: date | None) -> str:
    if d is None:
        return "no data"
    days = (data.today() - d).days
    return "today" if days == 0 else "yesterday" if days == 1 else f"{days} days ago"


def pct_change(new: float, old: float | None) -> float | None:
    if old in (None, 0):
        return None
    return (new / old - 1) * 100  # type: ignore[operator]


def show_currency_notes(*codes: str) -> None:
    seen: set[str] = set()
    for code in codes:
        for note in currencies.get(code).notes:
            if note not in seen:
                seen.add(note)
                st.info(note, icon=":material/info:")


def rate(value: object) -> str:
    return format_rate(value)  # type: ignore[arg-type]


def no_data_notice() -> None:
    st.warning(
        "No exchange-rate data is available yet. Run the worker once "
        "(`python -m fxwatch run-once`) or wait for the next scheduled run.",
        icon=":material/hourglass_empty:",
    )


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    shown = local[:2] if len(local) > 2 else local[:1]
    return f"{shown}{'•' * max(len(local) - len(shown), 1)}@{domain}"
