"""Landing page for confirmation links: /confirm?token=..."""

from __future__ import annotations

import streamlit as st

from app.ui import components as ui
from app.ui import data
from fxwatch import currencies
from fxwatch.domain.models import Condition
from fxwatch.services.alerts import AlertService
from fxwatch.services.tokens import InvalidToken

ui.page_header("Confirm alert", kicker="Alerts")

token = st.query_params.get("token", "")
if not token:
    st.error("This page needs a confirmation link. Open the link from your email.")
    st.stop()

try:
    with data.db() as session:
        result = AlertService(session, data.settings()).confirm(token)
        alert = result.alert
        summary = (
            f"{currencies.get(alert.base).flag} **{alert.base}/{alert.quote}** "
            f"{Condition(alert.condition).describe} **{ui.rate(alert.threshold)}**"
        )
except InvalidToken as exc:
    st.error(str(exc), icon=":material/link_off:")
    if exc.expired:
        st.caption(
            "Confirmation links expire for security. Create the alert again to get a new one."
        )
    st.page_link(
        "app/views/new_alert.py", label="Create an alert", icon=":material/notification_add:"
    )
    st.stop()

if result.already_confirmed:
    st.info(f"This alert is already active: {summary}.", icon=":material/check_circle:")
else:
    st.success(f"Your alert is active: {summary}.", icon=":material/check_circle:")
    st.balloons()

st.markdown(
    "We check rates every hour. When the condition is met you'll get an email with the rate, "
    "recent context and a link to manage your alerts."
)
st.link_button(
    "Manage my alerts", result.manage_url, type="primary", icon=":material/manage_accounts:"
)
st.caption("Bookmark that page: it's your private, password-free link to all your alerts.")
