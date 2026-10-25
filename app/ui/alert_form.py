"""The alert-rule builder, shared by the New alert and My alerts pages."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ui import charts, data
from app.ui import components as ui
from fxwatch.db.models import NotificationRow
from fxwatch.domain.models import Condition, Mode
from fxwatch.notify.mailer import get_mailer
from fxwatch.services import analytics, outbox
from fxwatch.services.alerts import LIFETIME_CHOICES, AlertInput
from fxwatch.services.rates import AUTO
from fxwatch.sources import SOURCE_INFO

CONDITION_LABELS = {
    Condition.ABOVE: "Rises to or above",
    Condition.BELOW: "Falls to or below",
    Condition.CROSS: "Crosses (either way)",
}
COOLDOWNS = {1: "1 hour", 6: "6 hours", 12: "12 hours", 24: "1 day", 72: "3 days", 168: "1 week"}


def rule_builder(prefix: str, show_chart: bool = True) -> AlertInput | None:
    """Render the rule inputs with live context. Returns None if the pair can't be priced."""
    base, quote = ui.pair_picker(prefix, "EUR", "ZAR")
    if base == quote:
        st.info("Choose two different currencies.")
        return None
    current = data.quote(base, quote)
    if current is None:
        st.warning(
            "No fresh rate is available for this pair right now, so alerts can't be set on it."
        )
        return None
    now_rate = float(current.rate)

    condition = (
        st.segmented_control(
            "Notify me when the rate",
            list(Condition),
            default=Condition.ABOVE,
            format_func=lambda c: CONDITION_LABELS[c],
            required=True,
            key=f"{prefix}_cond",
        )
        or Condition.ABOVE
    )

    factor = 0.98 if condition is Condition.BELOW else 1.02
    c1, c2 = st.columns([1, 1], vertical_alignment="bottom")
    with c1:
        threshold = st.number_input(
            f"Threshold (1 {base} in {quote})",
            min_value=0.0,
            value=float(f"{now_rate * factor:.6g}"),
            step=float(f"{now_rate * 0.005:.2g}") or 0.0001,
            format="%.6f",
            key=f"{prefix}_thr_{base}{quote}_{condition.value}",
        )
    with c2:
        distance = (threshold / now_rate - 1) * 100 if now_rate else 0
        st.metric(
            f"Current {base}/{quote}",
            ui.rate(now_rate),
            f"threshold is {distance:+.2f}% away",
            delta_color="off",
        )
    st.caption(ui.provenance(current))

    if threshold <= 0:
        st.error("The threshold must be greater than zero.")
        return None

    already = (condition is Condition.ABOVE and now_rate >= threshold) or (
        condition is Condition.BELOW and now_rate <= threshold
    )
    if already:
        st.warning(
            "The current rate already meets this condition, so the alert will fire on the next check.",
            icon=":material/bolt:",
        )

    if show_chart:
        _, series = data.history(base, quote, data.today() - timedelta(days=365), data.today())
        if len(series) > 10:
            st.plotly_chart(
                charts.rate_chart(series, f"{base}/{quote}", threshold=threshold, height=260),
                width="stretch",
                config={"displayModeBar": False},
            )
            share = analytics.share_meeting(series, condition, threshold)
            crosses = analytics.crossings(series, threshold)
            if share is not None:
                st.caption(
                    f"Over the past year this level was reached on {share:.0f}% of days "
                    f"and crossed {crosses} times."
                )
            else:
                st.caption(f"Over the past year the rate crossed this level {crosses} times.")

    m1, m2 = st.columns(2)
    with m1:
        mode = st.radio(
            "Frequency",
            list(Mode),
            format_func=lambda m: "Notify me once" if m is Mode.ONCE else "Every time it happens",
            key=f"{prefix}_mode",
            help="Recurring alerts re-arm once the rate moves back 0.5% past the threshold.",
        )
    with m2:
        lifetime = st.selectbox(
            "Keep the alert active for",
            LIFETIME_CHOICES,
            index=LIFETIME_CHOICES.index(90),
            format_func=lambda d: f"{d} days",
            key=f"{prefix}_life",
        )

    with st.expander("Advanced options"):
        label = st.text_input(
            "Label (optional)",
            max_chars=120,
            placeholder="e.g. Stipend transfer",
            key=f"{prefix}_label",
        )
        sources = [q.source_id for q in data.quotes(base, quote)]
        source_pref = st.selectbox(
            "Price the alert from",
            [AUTO, *sources],
            format_func=lambda s: (
                "Best available source (recommended)" if s == AUTO else SOURCE_INFO[s].name
            ),
            key=f"{prefix}_src_{base}{quote}",
        )
        cooldown = st.select_slider(
            "Minimum time between recurring emails",
            list(COOLDOWNS),
            value=24,
            format_func=lambda h: COOLDOWNS[h],
            key=f"{prefix}_cool",
        )

    return AlertInput(
        base=base,
        quote=quote,
        condition=condition,
        threshold=Decimal(str(threshold)),
        mode=mode,
        source_preference=source_pref,
        label=label,
        lifetime_days=lifetime,
        cooldown_hours=cooldown,
    )


def send_now(session: Session, dedupe_key: str) -> bool:
    """Deliver a just-queued email immediately (the worker retries if this fails)."""
    row = session.scalar(select(NotificationRow).where(NotificationRow.dedupe_key == dedupe_key))
    if row is None:
        return False
    settings = data.settings()
    return outbox.deliver(session, row, get_mailer(settings), settings.max_send_attempts)
