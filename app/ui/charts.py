"""Plotly charts styled for both Streamlit themes.

Colors follow the dataviz reference palette: series in fixed categorical order
(blue, orange, aqua), selected per theme rather than flipped; neutral ink for the
threshold reference line; hairline solid gridlines; 2px lines.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from fxwatch.domain.crossrate import format_rate

PALETTE = {
    "light": {
        "series": ["#2a78d6", "#eb6834", "#1baf7a"],
        "fill": "rgba(42,120,214,0.08)",
        "grid": "rgba(82,81,78,0.14)",
        "ink": "#52514e",
        "ref": "#52514e",
        "surface": "#ffffff",
    },
    "dark": {
        "series": ["#3987e5", "#d95926", "#199e70"],
        "fill": "rgba(57,135,229,0.12)",
        "grid": "rgba(195,194,183,0.16)",
        "ink": "#c3c2b7",
        "ref": "#c3c2b7",
        "surface": "#0e1117",
    },
}


def _theme() -> dict:
    try:
        mode = st.context.theme.type or "light"
    except Exception:
        mode = "light"
    return PALETTE["dark" if mode == "dark" else "light"]


def _hover_format(series: pd.Series) -> str:
    v = float(series.abs().median()) if not series.empty else 1.0
    return ",.2f" if v >= 1000 else ",.4f" if v >= 1 else ".6g"


def rate_chart(
    series: pd.Series,
    title: str,
    overlays: dict[str, pd.Series] | None = None,
    threshold: float | None = None,
    height: int = 420,
) -> go.Figure:
    t = _theme()
    fmt = _hover_format(series)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=series.index,
            y=series.values,
            name=title,
            mode="lines",
            line={"color": t["series"][0], "width": 2},
            fill="tozeroy" if not overlays else None,
            fillcolor=t["fill"],
            hovertemplate=f"%{{y:{fmt}}}<extra>{title}</extra>",
        )
    )
    for i, (name, s) in enumerate((overlays or {}).items(), start=1):
        fig.add_trace(
            go.Scatter(
                x=s.index,
                y=s.values,
                name=name,
                mode="lines",
                line={"color": t["series"][i % len(t["series"])], "width": 2},
                hovertemplate=f"%{{y:{fmt}}}<extra>{name}</extra>",
            )
        )
    if threshold is not None:
        fig.add_hline(
            y=threshold,
            line={"color": t["ref"], "width": 1},
            annotation_text=f"Threshold {format_rate(threshold)}",
            annotation_position="top left",
            annotation_font={"color": t["ink"], "size": 12},
        )

    lo, hi = float(series.min()), float(series.max())
    if threshold is not None:
        lo, hi = min(lo, threshold), max(hi, threshold)
    pad = (hi - lo) * 0.08 or hi * 0.01

    fig.update_layout(
        height=height,
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": t["ink"]},
        hovermode="x unified",
        hoverlabel={"bgcolor": t["surface"], "font": {"color": t["ink"]}},
        showlegend=bool(overlays),
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "xanchor": "left", "x": 0},
        xaxis={
            "showgrid": False,
            "showspikes": True,
            "spikemode": "across",
            "spikethickness": 1,
            "spikecolor": t["grid"],
            "spikedash": "solid",
            "linecolor": t["grid"],
        },
        yaxis={
            "gridcolor": t["grid"],
            "gridwidth": 1,
            "zeroline": False,
            "tickformat": fmt,
            "range": [lo - pad, hi + pad],
            "side": "right",
        },
    )
    return fig


def distribution_chart(series: pd.Series, latest: float, height: int = 300) -> go.Figure:
    t = _theme()
    fig = go.Figure(
        go.Histogram(
            x=series.values,
            nbinsx=40,
            marker={"color": t["series"][0], "line": {"color": t["surface"], "width": 2}},
            hovertemplate="%{x}<br>%{y} days<extra></extra>",
        )
    )
    fig.add_vline(
        x=latest,
        line={"color": t["ref"], "width": 1},
        annotation_text=f"Today {format_rate(latest)}",
        annotation_font={"color": t["ink"], "size": 12},
    )
    fig.update_layout(
        height=height,
        margin={"l": 8, "r": 8, "t": 24, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": t["ink"]},
        bargap=0.04,
        showlegend=False,
        xaxis={"showgrid": False, "title": "Rate"},
        yaxis={"gridcolor": t["grid"], "title": "Days"},
    )
    return fig
