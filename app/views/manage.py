"""Password-free alert management via a signed link: /manage?token=..."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

import streamlit as st

from app.ui import alert_form, data
from app.ui import components as ui
from fxwatch import currencies
from fxwatch.db.models import AlertRow, SubscriberRow
from fxwatch.domain.models import AlertStatus, Condition, Mode
from fxwatch.services.alerts import AlertError, AlertService
from fxwatch.services.tokens import InvalidToken
from fxwatch.sources import SOURCE_INFO

ui.page_header("My alerts", kicker="Alerts")
settings = data.settings()
token = st.query_params.get("token", "")


def request_link_form(intro: str) -> None:
    st.markdown(intro)
    with st.form("request_link", border=True):
        email = st.text_input("Email address", placeholder="you@example.com", autocomplete="email")
        if st.form_submit_button("Email me my link", type="primary", icon=":material/send:"):
            try:
                with data.db() as s:
                    key = AlertService(s, settings).request_manage_link(email, data.client_ip())
                    if key:
                        alert_form.send_now(s, key)
            except AlertError as exc:
                st.error(str(exc))
            else:
                # Same message either way, so the form can't be used to discover who has alerts.
                st.success(
                    "If that address has alerts, a management link is on its way.",
                    icon=":material/mark_email_read:",
                )


if not token:
    request_link_form(
        "Your alerts are tied to your email address. Enter it and we'll send you a private "
        "link to view and manage them. No password needed."
    )
    st.stop()


def act(fn: Callable[[AlertService, SubscriberRow], object], message: str) -> None:
    """Run a change in its own transaction, then refresh the page."""
    try:
        with data.db() as s:
            svc = AlertService(s, settings)
            fn(svc, svc.subscriber_from_token(token))
    except (AlertError, InvalidToken) as exc:
        st.error(str(exc))
        return
    st.toast(message, icon=":material/check:")
    st.rerun()


try:
    with data.db() as s:
        svc = AlertService(s, settings)
        sub = svc.subscriber_from_token(token)
        email, sub_id = sub.email, sub.id
        alerts = svc.list_alerts(sub)
except InvalidToken as exc:
    st.error(str(exc), icon=":material/link_off:")
    request_link_form("Request a fresh link below.")
    st.stop()

# ------------------------------------------------------------------ one-click actions from emails
action, action_alert = st.query_params.get("action"), st.query_params.get("alert")
done_key = f"done:{action}:{action_alert}:{token[-16:]}"

if action == "unsubscribe":
    with st.container(border=True):
        st.markdown("#### Unsubscribe from all alerts?")
        st.markdown(
            f"This deletes **all {len(alerts)} alert(s)** and your email address from FX Watch. "
            "It can't be undone."
        )
        c1, c2 = st.columns(2)
        if c1.button("Delete everything", type="primary", icon=":material/delete_forever:"):
            with data.db() as s:
                svc = AlertService(s, settings)
                svc.delete_everything(svc.subscriber_from_token(token))
            st.query_params.clear()
            st.success("Done. You've been unsubscribed and your data has been deleted.")
            st.stop()
        if c2.button("Keep my alerts"):
            del st.query_params["action"]
            st.rerun()
    st.stop()

if (
    action == "extend"
    and action_alert
    and action_alert.isdigit()
    and not st.session_state.get(done_key)
):
    st.session_state[done_key] = True
    act(lambda svc, sub: svc.extend(sub, int(action_alert)), "Alert extended")

# ------------------------------------------------------------------ header
st.caption(f"Alerts for **{ui.mask_email(email)}**. Keep this page's link private.")
c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
open_count = sum(
    a.status in (AlertStatus.ACTIVE, AlertStatus.PENDING, AlertStatus.PAUSED) for a in alerts
)
c1.markdown(f"**{open_count}** open of {settings.max_active_alerts_per_email} allowed")

with c2.popover("New alert", icon=":material/add:", width="stretch"):
    rule = alert_form.rule_builder("mg", show_chart=False)
    if rule is not None and st.button("Add alert", type="primary", width="stretch"):
        act(lambda svc, sub: svc.create_for_subscriber(sub, rule), "Alert added")

if not alerts:
    st.info("You don't have any alerts yet.")

STATUS_BADGE = {
    AlertStatus.ACTIVE: ("Active", "green"),
    AlertStatus.PENDING: ("Awaiting confirmation", "orange"),
    AlertStatus.PAUSED: ("Paused", "gray"),
    AlertStatus.TRIGGERED: ("Triggered", "violet"),
    AlertStatus.EXPIRED: ("Expired", "red"),
}

RESUME_LABELS = {
    AlertStatus.PAUSED: ("Resume", "Alert resumed"),
    AlertStatus.TRIGGERED: ("Re-arm", "Alert re-armed"),
    AlertStatus.PENDING: ("Activate", "Alert activated"),
}


def _ago(ts: datetime | None) -> str:
    if ts is None:
        return "never"
    minutes = int((datetime.now(ts.tzinfo) - ts).total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min ago"
    if minutes < 48 * 60:
        return f"{minutes // 60} h ago"
    return ts.strftime("%d %b %Y")


def alert_card(a: AlertRow) -> None:
    status = AlertStatus(a.status)
    cond = Condition(a.condition)
    with st.container(border=True):
        top_l, top_r = st.columns([3, 1])
        with top_l:
            title = f"{currencies.get(a.base).flag} **{a.base}/{a.quote}** {cond.describe} **{ui.rate(a.threshold)}**"
            st.markdown(title + (f"  \n_{a.label}_" if a.label else ""))
        with top_r:
            text, color = STATUS_BADGE[status]
            st.badge(text, color=color)  # type: ignore[arg-type]

        current = data.quote(a.base, a.quote, a.source_preference)
        bits = []
        if current is not None:
            gap = (float(a.threshold) / float(current.rate) - 1) * 100
            bits.append(f"Now {ui.rate(current.rate)} ({gap:+.2f}% to threshold)")
        bits.append("Recurring" if a.mode == Mode.RECURRING else "One-time")
        bits.append(f"Checked {_ago(a.last_evaluated_at)}")
        if a.trigger_count:
            bits.append(f"Fired {a.trigger_count}× (last {_ago(a.last_triggered_at)})")
        bits.append(f"Expires {a.expires_at:%d %b %Y}")
        if a.source_preference != "auto":
            bits.append(SOURCE_INFO[a.source_preference].name)
        st.caption(" · ".join(bits))
        if a.hold_reason and status is AlertStatus.ACTIVE:
            st.warning(a.hold_reason, icon=":material/pause_circle:")

        b = st.columns(4)
        if status is AlertStatus.ACTIVE:
            if b[0].button("Pause", key=f"p{a.id}", icon=":material/pause:", width="stretch"):
                act(lambda svc, sub: svc.pause(sub, a.id), "Alert paused")
        elif status in (AlertStatus.PAUSED, AlertStatus.TRIGGERED, AlertStatus.PENDING):
            label, done = RESUME_LABELS[status]
            if b[0].button(label, key=f"r{a.id}", icon=":material/play_arrow:", width="stretch"):
                act(lambda svc, sub: svc.resume(sub, a.id), done)
        if b[1].button("Extend 90 days", key=f"x{a.id}", icon=":material/update:", width="stretch"):
            act(lambda svc, sub: svc.extend(sub, a.id, 90), "Alert extended")
        with (
            b[2].popover("Edit", icon=":material/edit:", width="stretch"),
            st.form(f"edit{a.id}", border=False),
        ):
            new_cond = st.selectbox(
                "Condition",
                list(Condition),
                index=list(Condition).index(cond),
                format_func=lambda c: alert_form.CONDITION_LABELS[c],
            )
            new_thr = st.number_input(
                "Threshold", value=float(a.threshold), min_value=0.0, format="%.6f"
            )
            new_mode = st.radio(
                "Frequency",
                list(Mode),
                index=list(Mode).index(Mode(a.mode)),
                format_func=lambda m: "Once" if m is Mode.ONCE else "Every time",
                horizontal=True,
            )
            new_label = st.text_input("Label", value=a.label or "", max_chars=120)
            if st.form_submit_button("Save", type="primary"):
                act(
                    lambda svc, sub: svc.update(
                        sub,
                        a.id,
                        threshold=Decimal(str(new_thr)),
                        condition=new_cond,
                        mode=new_mode,
                        label=new_label,
                    ),
                    "Alert updated",
                )
        with b[3].popover("Delete", icon=":material/delete:", width="stretch"):
            st.write("Delete this alert permanently?")
            if st.button("Yes, delete", key=f"d{a.id}", type="primary"):
                act(lambda svc, sub: svc.delete_alert(sub, a.id), "Alert deleted")


for alert in alerts:
    alert_card(alert)

# ------------------------------------------------------------------ account-level actions
st.divider()
with st.expander("Security & privacy"):
    st.markdown(
        "**Replace my link.** If you think someone else has this link, replace it. Every older "
        "link stops working and we email you a new one."
    )
    if st.button("Replace my management link", icon=":material/key:"):
        try:
            with data.db() as s:
                svc = AlertService(s, settings)
                key = svc.rotate_link(svc.subscriber_from_token(token))
                alert_form.send_now(s, key)
        except InvalidToken as exc:
            st.error(str(exc))
        else:
            st.success("Done. Check your inbox for the new link. This page's link no longer works.")
            st.stop()
    st.markdown("**Delete my data.** Removes every alert and your email address.")
    if st.button("Delete all my data", icon=":material/delete_forever:"):
        st.query_params["action"] = "unsubscribe"
        st.rerun()
