"""Create a rate alert (no account; confirmed by email)."""

from __future__ import annotations

import streamlit as st

from app.ui import alert_form, data
from app.ui import components as ui
from fxwatch.services.alerts import AlertError, AlertService
from fxwatch.services.tokens import TokenService

ui.page_header(
    "New rate alert",
    "Get an email when a rate reaches your level. No account or password; just confirm your email.",
    kicker="Alerts",
)

if not data.current_snapshots():
    ui.no_data_notice()
    st.stop()

settings = data.settings()

with st.container(border=True):
    st.markdown("##### 1 · What should we watch?")
    rule = alert_form.rule_builder("na")

if rule is None:
    st.stop()

with st.container(border=True):
    st.markdown("##### 2 · Where should we send it?")
    email = st.text_input("Email address", placeholder="you@example.com", autocomplete="email")
    consent = st.checkbox(
        "Email me about this alert. I can pause or delete it, or unsubscribe, at any time.",
    )
    submitted = st.button("Create alert", type="primary", icon=":material/notifications_active:")

if submitted:
    if not consent:
        st.error("Please tick the box to agree to receive alert emails.")
        st.stop()
    try:
        with data.db() as session:
            alert = AlertService(session, settings).create_unconfirmed(
                email, rule, data.client_ip()
            )
            delivered = alert_form.send_now(session, f"confirm:{alert.id}")
            alert_id = alert.id
    except AlertError as exc:
        st.error(str(exc))
        st.stop()

    if delivered:
        st.success(
            f"Almost done! We've sent a confirmation link to **{email.strip()}**. "
            f"Click it within {settings.confirmation_token_max_age_hours} hours to activate the alert.",
            icon=":material/mark_email_read:",
        )
    else:
        st.warning(
            "Your alert is saved, but the confirmation email couldn't be sent right now. "
            "We'll keep retrying for the next few hours.",
            icon=":material/schedule_send:",
        )
    st.caption("Can't find it? Check your spam folder.")

    if settings.mail_backend == "console" and settings.environment != "production":
        with st.expander("Developer mode: confirmation link"):
            st.caption("MAIL_BACKEND=console, so no real email was sent.")
            st.code(TokenService(settings.secret_key, settings.app_base_url).confirm_url(alert_id))

st.divider()
st.caption("Already have alerts?")
st.page_link(
    "app/views/manage.py", label="Get a link to manage them", icon=":material/manage_accounts:"
)
