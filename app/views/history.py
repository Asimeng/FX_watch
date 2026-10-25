"""Historical chart, statistics and data export for any pair."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from app.ui import charts, data
from app.ui import components as ui
from fxwatch import currencies
from fxwatch.domain.models import Condition
from fxwatch.services import analytics
from fxwatch.services.rates import AUTO
from fxwatch.sources import SOURCE_INFO

ui.page_header(
    "History & analysis", "Trends, volatility and where today's rate sits.", kicker="Markets"
)

# Deep links from the dashboard: ?base=EUR&quote=ZAR
qp_base, qp_quote = st.query_params.get("base", ""), st.query_params.get("quote", "")
if currencies.is_supported(qp_base) and currencies.is_supported(qp_quote):
    st.session_state.setdefault("hist_base", qp_base.upper())
    st.session_state.setdefault("hist_quote", qp_quote.upper())

base, quote = ui.pair_picker("hist", "EUR", "ZAR")
if base == quote:
    st.info("Choose two different currencies.")
    st.stop()

RANGES = {
    "1M": 30,
    "3M": 91,
    "6M": 182,
    "1Y": 365,
    "2Y": 730,
    "5Y": 1826,
    "10Y": 3652,
    "Max": 20000,
}
c1, c2, c3 = st.columns([2, 1.3, 1.6], vertical_alignment="bottom")
with c1:
    span = st.segmented_control("Range", list(RANGES), default="1Y", required=True) or "1Y"
with c2:
    srcs = data.history_sources(base, quote)
    source = st.selectbox(
        "Source",
        [AUTO, *srcs],
        format_func=lambda s: "Best coverage (auto)" if s == AUTO else SOURCE_INFO[s].name,
    )
with c3:
    overlays_on = st.multiselect(
        "Overlays", ["20-day average", "50-day average"], placeholder="None"
    )

end = data.today()
start = max(end - timedelta(days=RANGES[span]), date(1999, 1, 4))
source_id, series = data.history(base, quote, start, end, source)

if series.empty:
    st.warning(
        "No history is stored for this pair yet. Official sources cover major currencies; "
        "others accumulate from the day the service started tracking them."
    )
    st.stop()

first_day = series.index.min().date()
if span != "Max" and (first_day - start).days > 10:  # allow for weekends and holidays
    years = (end - first_day).days / 365.25
    st.info(
        f"Stored history for {base}/{quote} starts on {first_day:%d %b %Y} "
        f"({SOURCE_INFO[source_id].name if source_id else 'no source'}), so this chart covers "
        f"about {years:.1f} years rather than the full {span}. Free sources for this pair "
        "don't go back further.",
        icon=":material/history:",
    )

stats = analytics.describe(series)
assert stats is not None
threshold_on = st.toggle("Show a threshold line", help="Preview where an alert level would sit")
threshold = None
if threshold_on:
    threshold = st.number_input(
        "Threshold", value=float(round(stats.latest * 1.02, 6)), format="%.6f"
    )

overlays = {}
if "20-day average" in overlays_on:
    overlays["20-day average"] = analytics.moving_average(series, 20)
if "50-day average" in overlays_on:
    overlays["50-day average"] = analytics.moving_average(series, 50)

m = st.columns(6)
m[0].metric("Latest", ui.rate(stats.latest), f"{stats.change_pct:+.2f}% over {span}")
m[1].metric("Low", ui.rate(stats.low))
m[2].metric("High", ui.rate(stats.high))
m[3].metric("Average", ui.rate(stats.mean))
m[4].metric(
    "Volatility",
    f"{stats.volatility_annual_pct:.1f}%" if stats.volatility_annual_pct is not None else "—",
    help="Annualised standard deviation of daily log returns.",
)
m[5].metric(
    "Percentile",
    f"{stats.percentile:.0f}th",
    help="Share of days in this range on which the rate was lower than it is today.",
)

tab_chart, tab_dist, tab_data = st.tabs(["Chart", "Distribution", "Data"])
title = f"{base}/{quote}"
with tab_chart:
    st.plotly_chart(
        charts.rate_chart(series, title, overlays or None, threshold),
        width="stretch",
        config={"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]},
    )
    if threshold is not None:
        share_above = analytics.share_meeting(series, Condition.ABOVE, threshold)
        st.caption(
            f"In this range the rate was at or above {ui.rate(threshold)} on "
            f"{share_above:.0f}% of days and crossed it {analytics.crossings(series, threshold)} times."
        )
with tab_dist:
    st.plotly_chart(charts.distribution_chart(series, stats.latest), width="stretch")
    st.caption(
        f"Today's rate is higher than {stats.percentile:.0f}% of the {stats.observations} "
        f"daily observations in this range."
    )
with tab_data:
    frame = pd.DataFrame({"date": series.index.date, f"{base}_{quote}": series.values})
    st.dataframe(frame.iloc[::-1], hide_index=True, width="stretch", height=380)
    st.download_button(
        "Download CSV",
        frame.to_csv(index=False).encode(),
        file_name=f"{base}{quote}_{start:%Y%m%d}_{end:%Y%m%d}.csv",
        mime="text/csv",
        icon=":material/download:",
    )

if source_id:
    info = SOURCE_INFO[source_id]
    st.caption(
        f"{stats.observations} observations from {series.index.min():%d %b %Y} to "
        f"{series.index.max():%d %b %Y} · {info.name}"
        + (f" (cross rate via {info.base})" if info.base not in (base, quote) else "")
        + f" · {info.attribution}"
    )
ui.show_currency_notes(base, quote)
