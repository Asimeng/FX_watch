"""Currency converter with a side-by-side comparison of every source."""

from __future__ import annotations

import statistics

import pandas as pd
import streamlit as st

from app.ui import components as ui
from app.ui import data
from fxwatch import currencies
from fxwatch.domain.crossrate import format_rate
from fxwatch.services.rates import AUTO
from fxwatch.sources import SOURCE_INFO

ui.page_header("Converter", "Convert between any two of 150+ currencies.", kicker="Markets")

if not data.current_snapshots():
    ui.no_data_notice()
    st.stop()

amount = st.number_input("Amount", min_value=0.0, value=1000.0, step=100.0, format="%.2f")
base, quote = ui.pair_picker("conv", "EUR", "ZAR")

if base == quote:
    st.info("Choose two different currencies.")
    st.stop()

available = data.quotes(base, quote)
if not available:
    st.warning("No fresh rate is available for this pair right now.")
    st.stop()

source = st.segmented_control(
    "Source",
    [AUTO] + [q.source_id for q in available],
    default=AUTO,
    format_func=lambda s: "Best available" if s == AUTO else SOURCE_INFO[s].name,
    required=True,
)
q = data.quote(base, quote, source or AUTO) or available[0]
converted = float(q.rate) * amount
cb, cq = currencies.get(base), currencies.get(quote)

with st.container(border=True):
    st.html(
        f'<div class="fx-sub">{amount:,.2f} {cb.name} =</div>'
        f'<div class="fx-hero fx-mono">{converted:,.2f} {quote}</div>'
        f'<div class="fx-sub">1 {base} = {format_rate(q.rate)} {quote} · '
        f"1 {quote} = {format_rate(q.inverse)} {base}</div>"
    )
    ui.source_badge(q.source_id)
    st.caption(ui.provenance(q))

ui.show_currency_notes(base, quote)

left, right = st.columns(2, gap="large")

with left:
    st.subheader("Compare sources", anchor=False)
    median = statistics.median(float(x.rate) for x in available)
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Source": SOURCE_INFO[x.source_id].name,
                    "Type": SOURCE_INFO[x.source_id].tier.value.title(),
                    "Rate": float(x.rate),
                    f"{amount:,.0f} {base} →": float(x.rate) * amount,
                    "vs. median %": (float(x.rate) / median - 1) * 100,
                    "Date": x.rate_date,
                }
                for x in available
            ]
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "Rate": st.column_config.NumberColumn(format="%.6g"),
            f"{amount:,.0f} {base} →": st.column_config.NumberColumn(format="%,.2f"),
            "vs. median %": st.column_config.NumberColumn(format="%+.3f%%"),
            "Date": st.column_config.DateColumn(format="DD MMM YYYY"),
        },
    )
    st.caption(
        "Sources publish at different times of day, so small differences are normal. "
        "Large gaps can point to a stale or parallel-market rate."
    )

with right:
    st.subheader("Quick reference", anchor=False)
    steps = [1, 5, 10, 25, 50, 100, 250, 500, 1000, 5000, 10000]
    st.dataframe(
        pd.DataFrame(
            {
                base: steps,
                f"→ {quote}": [s * float(q.rate) for s in steps],
                quote: steps,
                f"→ {base}": [s * float(q.inverse) for s in steps],
            }
        ),
        hide_index=True,
        width="stretch",
        column_config={
            f"→ {quote}": st.column_config.NumberColumn(format="%,.2f"),
            f"→ {base}": st.column_config.NumberColumn(format="%,.2f"),
        },
    )

st.caption(
    "These are mid-market rates. Banks, bureaux and remittance services add a spread and fees, "
    "so the amount you actually receive will usually be lower."
)
