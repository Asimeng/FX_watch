"""Transparency page: where rates come from, how fresh they are, and how they're combined."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.ui import components as ui
from app.ui import data
from fxwatch import currencies
from fxwatch.sources import SOURCE_CLASSES

ui.page_header(
    "Data sources & status",
    "Every rate shown in FX Watch is traceable to one of these publishers.",
    kicker="About",
)

snaps = data.current_snapshots()
status = data.source_status()
today = data.today()

for cls in SOURCE_CLASSES:
    info = cls.info
    st_ = status.get(info.id, {})
    snap = snaps.get(info.id)
    with st.container(border=True):
        left, right = st.columns([3, 1.2])
        with left:
            st.markdown(f"#### {info.name}")
            ui.source_badge(info.id)
            st.write(info.description)
            st.caption(
                f"**Schedule:** {info.schedule}  \n**Base currency:** {info.base} · {info.attribution}"
            )
            st.markdown(f"[{info.homepage}]({info.homepage})")
        with right:
            latest = snap.latest_date if snap else None
            healthy = (
                st_.get("consecutive_failures", 0) == 0
                and latest is not None
                and (today - latest).days <= info.max_age_days
            )
            st.metric(
                "Latest rates",
                f"{latest:%d %b %Y}" if latest else "—",
                ui.freshness(latest),
                delta_color="off",
            )
            st.metric("Currencies", len(snap.values) if snap else 0)
            if healthy:
                st.badge("Healthy", icon=":material/check_circle:", color="green")
            elif st_:
                st.badge("Degraded", icon=":material/warning:", color="orange")
                if st_.get("last_error"):
                    st.caption(f"Last error: {st_['last_error'][:200]}")
            else:
                st.badge("Not fetched yet", icon=":material/hourglass_empty:", color="gray")

st.subheader("How rates are combined", anchor=False)
st.markdown(
    """
- **One source per rate.** Each source publishes every currency against its own base (EUR, CAD
  or USD). The rate for any pair is computed from *one* source's snapshot. Legs from different
  publishers are never mixed.
- **Most authoritative first.** For each pair we use the highest-ranked source with a fresh rate
  for both currencies: European Central Bank, then Bank of Canada, then ExchangeRate-API, then
  the open Currency API dataset.
- **Freshness.** A source's rate is considered stale after a few days without publication
  (allowing for weekends and holidays). Stale rates are never shown as current or used for alerts.
- **Cross-checking.** Before an alert fires, its rate is compared with the median of every
  other source. If they disagree by more than the tolerance, the alert is held for that run
  instead of sending a possibly wrong email.
- **Precision.** Arithmetic uses exact decimals. Bank of Canada series with fewer than three
  significant digits are discarded because inverting them would add visible error.
- **Mid-market only.** These are reference rates. Banks and bureaux add a spread; retail
  bank rates are planned as an additional source.
"""
)

st.subheader("Coverage", anchor=False)
cover_rows = []
for code, cur in currencies.CURRENCIES.items():
    row: dict[str, object] = {"Currency": f"{cur.flag} {code}", "Name": cur.name}
    for cls in SOURCE_CLASSES:
        snap = snaps.get(cls.info.id)
        row[cls.info.name] = bool(snap and snap.is_fresh(code, today))
    note = []
    if cur.peg:
        note.append(f"pegged to {cur.peg}")
    if cur.parallel_market:
        note.append("parallel market")
    row["Notes"] = ", ".join(note)
    cover_rows.append(row)
st.dataframe(pd.DataFrame(cover_rows), hide_index=True, width="stretch", height=420)

st.caption(
    "Flag artwork: [Twemoji](https://github.com/jdecked/twemoji) (CC-BY 4.0), "
    "via [country-flag-emoji-polyfill](https://github.com/talkjs/country-flag-emoji-polyfill) (MIT)."
)

with st.expander("Recent fetch runs"):
    runs = data.recent_runs()
    if runs.empty:
        st.caption("No runs recorded yet.")
    else:
        st.dataframe(
            runs,
            hide_index=True,
            width="stretch",
            column_config={"Started": st.column_config.DatetimeColumn(format="DD MMM HH:mm")},
        )
