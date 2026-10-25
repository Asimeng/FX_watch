"""FX Watch: Streamlit entry point. Run with `streamlit run streamlit_app.py`."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

BRAND = Path(__file__).parent / "static" / "brand"

st.set_page_config(
    page_title="FX Watch · Exchange rates & alerts",
    page_icon=str(BRAND / "favicon.png"),
    layout="wide",
    menu_items={
        "About": "FX Watch tracks official and credible exchange rates and emails you when "
        "a rate reaches your threshold. Rates are for information only.",
    },
)

from app.ui import components, data  # noqa: E402
from fxwatch import __version__  # noqa: E402
from fxwatch.sources import SOURCE_CLASSES  # noqa: E402

data.bootstrap()
components.inject_css()

pages = {
    "Markets": [
        st.Page(
            "app/views/dashboard.py", title="Dashboard", icon=":material/monitoring:", default=True
        ),
        st.Page(
            "app/views/converter.py",
            title="Converter",
            icon=":material/currency_exchange:",
            url_path="converter",
        ),
        st.Page(
            "app/views/history.py",
            title="History & analysis",
            icon=":material/show_chart:",
            url_path="history",
        ),
    ],
    "Alerts": [
        st.Page(
            "app/views/new_alert.py",
            title="New alert",
            icon=":material/notification_add:",
            url_path="alerts",
        ),
        st.Page(
            "app/views/manage.py",
            title="My alerts",
            icon=":material/manage_accounts:",
            url_path="manage",
        ),
    ],
    "About": [
        st.Page(
            "app/views/sources.py",
            title="Data sources & status",
            icon=":material/verified:",
            url_path="sources",
        ),
        st.Page(
            "app/views/confirm.py", title="Confirm alert", url_path="confirm", visibility="hidden"
        ),
    ],
}

page = st.navigation(pages)

theme = st.context.theme.type if st.context.theme else None
st.logo(
    str(BRAND / ("logo-dark.svg" if theme == "dark" else "logo-light.svg")),
    icon_image=str(BRAND / "mark.svg"),
    size="large",
)

with st.sidebar:
    st.caption("Official & credible exchange rates, with email alerts. No account needed.")
    snaps = data.current_snapshots()
    if snaps:
        lines = []
        for cls in SOURCE_CLASSES:
            snap = snaps.get(cls.info.id)
            if snap and snap.latest_date:
                fresh = snap.is_fresh(cls.info.base, data.today())
                dot = ":green[:material/check_circle:]" if fresh else ":orange[:material/schedule:]"
                lines.append(f"{dot} **{cls.info.name}** · {snap.latest_date:%d %b}")
        st.caption("  \n".join(lines))
    st.divider()
    st.caption(
        f"v{__version__} · Mid-market reference rates for information only; not an offer to trade."
    )

page.run()
