"""Dashboard: a personal watchlist plus a full rate board for any base currency."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from app.ui import components as ui
from app.ui import data
from fxwatch import currencies
from fxwatch.sources import SOURCE_INFO

ui.page_header(
    "Exchange rates",
    "Daily reference rates from central banks, cross-checked against independent aggregators.",
    kicker="Markets",
)

if not data.current_snapshots():
    ui.no_data_notice()
    st.stop()

# ---------------------------------------------------------------- watchlist state
# Kept in the URL (?pairs=EURZAR,EURGHS) so a watchlist can be bookmarked or shared.


def _parse_pairs(raw: str | None) -> list[tuple[str, str]]:
    out = []
    for token in (raw or "").split(","):
        token = token.strip().upper()
        if (
            len(token) == 6
            and currencies.is_supported(token[:3])
            and currencies.is_supported(token[3:])
        ):
            out.append((token[:3], token[3:]))
    return out


if "watchlist" not in st.session_state:
    st.session_state.watchlist = _parse_pairs(st.query_params.get("pairs")) or list(
        currencies.DEFAULT_PAIRS
    )


def _save_watchlist() -> None:
    st.query_params["pairs"] = ",".join(b + q for b, q in st.session_state.watchlist)


def _remove(pair: tuple[str, str]) -> None:
    st.session_state.watchlist.remove(pair)
    _save_watchlist()


# ---------------------------------------------------------------- watchlist cards
head_l, head_r = st.columns([3, 1], vertical_alignment="bottom")
head_l.subheader("Watchlist", anchor=False)
with head_r.popover("Add pair", icon=":material/add:", width="stretch"):
    base, quote = ui.pair_picker("add", "USD", "EUR")
    if st.button("Add to watchlist", type="primary", width="stretch"):
        if base == quote:
            st.error("Choose two different currencies.")
        elif (base, quote) in st.session_state.watchlist:
            st.info("That pair is already on your watchlist.")
        else:
            st.session_state.watchlist.append((base, quote))
            _save_watchlist()
            st.rerun()

today = data.today()
watch = st.session_state.watchlist
if not watch:
    st.info("Your watchlist is empty. Add a pair to get started.")

cols_per_row = 3
for row_start in range(0, len(watch), cols_per_row):
    cols = st.columns(cols_per_row)
    for col, pair in zip(cols, watch[row_start : row_start + cols_per_row], strict=False):
        b, q = pair
        with col.container(border=True):
            quote_ = data.quote(b, q)
            title = f"{currencies.get(b).flag} {b} → {currencies.get(q).flag} {q}"
            if quote_ is None:
                st.markdown(f"**{title}**")
                st.caption("No fresh rate available for this pair right now.")
            else:
                _, spark = data.history(b, q, today - timedelta(days=45), today, quote_.source_id)
                change = ui.pct_change(float(quote_.rate), data.previous(quote_))
                st.metric(
                    title,
                    ui.rate(quote_.rate),
                    delta=f"{change:+.2f}%" if change is not None else None,
                    delta_color="off" if change is None else "normal",
                    chart_data=spark.tail(30).tolist() if len(spark) > 2 else None,
                    chart_type="area",
                    help=f"1 {q} = {ui.rate(quote_.inverse)} {b}",
                )
                st.caption(ui.provenance(quote_))
            a, r = st.columns(2, vertical_alignment="center")
            a.page_link(
                "app/views/history.py",
                label="Chart",
                icon=":material/show_chart:",
                query_params={"base": b, "quote": q},
            )
            r.button(
                "Remove",
                key=f"rm_{b}{q}",
                icon=":material/close:",
                on_click=_remove,
                args=(pair,),
                type="tertiary",
            )

# ---------------------------------------------------------------- rate board
st.divider()
st.subheader("All currencies", anchor=False)
c1, c2 = st.columns([1, 2], vertical_alignment="bottom")
with c1:
    board_base = ui.currency_select("Base currency", "board_base", "EUR")
with c2:
    search = st.text_input("Filter", placeholder="Search by code or name, e.g. cedi, KES, dollar")

rows = []
for code in currencies.ordered_codes():
    if code == board_base:
        continue
    q_ = data.quote(board_base, code)
    if q_ is None:
        continue
    cur = currencies.get(code)
    if search and search.lower() not in f"{code} {cur.name}".lower():
        continue
    prev = data.previous(q_)
    rows.append(
        {
            "Currency": f"{cur.flag} {code}",
            "Name": cur.name,
            f"1 {board_base} =": float(q_.rate),
            "Inverse": float(q_.inverse),
            "Day change %": ui.pct_change(float(q_.rate), prev),
            "Source": SOURCE_INFO[q_.source_id].name,
            "Rate date": q_.rate_date,
        }
    )

if rows:
    board = pd.DataFrame(rows)
    st.dataframe(
        board,
        hide_index=True,
        placeholder="—",
        width="stretch",
        height=min(38 + 35 * len(board), 560),
        column_config={
            f"1 {board_base} =": st.column_config.NumberColumn(format="%.6g"),
            "Day change %": st.column_config.NumberColumn(format="%+.2f%%"),
            "Inverse": st.column_config.NumberColumn(
                format="%.6g", help=f"Price of one unit of the currency in {board_base}"
            ),
            "Rate date": st.column_config.DateColumn(format="DD MMM YYYY"),
        },
    )
    st.caption(
        f"{len(board)} currencies priced against {board_base}. Each rate uses the most authoritative "
        "fresh source for both currencies. Day change compares with that source's previous publication."
    )
else:
    st.info("No currencies match your filter.")
