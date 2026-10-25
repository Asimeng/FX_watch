"""Rendering of every email the service sends (HTML + plain-text alternatives)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from fxwatch import currencies
from fxwatch.config import Settings
from fxwatch.db.models import AlertRow
from fxwatch.domain.crossrate import format_rate
from fxwatch.domain.models import Condition, Mode, PairQuote
from fxwatch.notify.mailer import OutgoingEmail
from fxwatch.services.analytics import SeriesStats
from fxwatch.sources import SOURCE_INFO

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["rate"] = format_rate


def _alert_context(alert: AlertRow) -> dict[str, Any]:
    cond = Condition(alert.condition)
    return {
        "pair": f"{alert.base}/{alert.quote}",
        "base": currencies.get(alert.base),
        "quote": currencies.get(alert.quote),
        "condition": cond.describe,
        "threshold": format_rate(alert.threshold),
        "recurring": alert.mode == Mode.RECURRING,
        "label": alert.label,
        "expires": alert.expires_at.strftime("%d %b %Y"),
        "source": "best available source"
        if alert.source_preference == "auto"
        else SOURCE_INFO[alert.source_preference].name,
    }


def _render(
    settings: Settings,
    template: str,
    to: str,
    subject: str,
    unsubscribe_url: str | None,
    **ctx: Any,
) -> OutgoingEmail:
    ctx = {
        "app_name": settings.app_name,
        "app_url": settings.app_base_url,
        "subject": subject,
        **ctx,
    }
    ctx.setdefault("unsubscribe_url", unsubscribe_url)
    return OutgoingEmail(
        to=to,
        subject=subject,
        text=_env.get_template(f"{template}.txt").render(**ctx),
        html=_env.get_template(f"{template}.html").render(**ctx),
        unsubscribe_url=unsubscribe_url,
    )


def confirm_alert(settings: Settings, to: str, alert: AlertRow, confirm_url: str) -> OutgoingEmail:
    return _render(
        settings,
        "confirm_alert",
        to,
        f"Confirm your {alert.base}/{alert.quote} rate alert",
        None,
        alert=_alert_context(alert),
        confirm_url=confirm_url,
        hours=settings.confirmation_token_max_age_hours,
    )


@dataclass(frozen=True)
class TriggerFacts:
    quote: PairQuote
    stats_90d: SeriesStats | None
    triggered_at: datetime


def alert_triggered(
    settings: Settings,
    to: str,
    alert: AlertRow,
    facts: TriggerFacts,
    manage_url: str,
    unsubscribe_url: str,
) -> OutgoingEmail:
    q = facts.quote
    direction = {
        Condition.ABOVE: "is now at or above",
        Condition.BELOW: "is now at or below",
        Condition.CROSS: "has crossed",
    }[Condition(alert.condition)]
    return _render(
        settings,
        "alert_triggered",
        to,
        f"{alert.base}/{alert.quote} {direction.replace('is now ', '')} {format_rate(alert.threshold)}"
        f" — now {format_rate(q.rate)}",
        unsubscribe_url,
        alert=_alert_context(alert),
        direction=direction,
        rate=format_rate(q.rate),
        inverse=format_rate(q.inverse),
        rate_date=q.rate_date.strftime("%a %d %b %Y"),
        source=SOURCE_INFO[q.source_id],
        derived=q.derived,
        stats=facts.stats_90d,
        manage_url=manage_url,
        notes=currencies.get(alert.base).notes + currencies.get(alert.quote).notes,
    )


def manage_link(
    settings: Settings, to: str, manage_url: str, alerts: list[AlertRow], rotated: bool = False
) -> OutgoingEmail:
    return _render(
        settings,
        "manage_link",
        to,
        f"Your {settings.app_name} management link",
        None,
        manage_url=manage_url,
        alerts=[_alert_context(a) | {"status": a.status} for a in alerts],
        rotated=rotated,
    )


def expiry_reminder(
    settings: Settings, to: str, alert: AlertRow, extend_url: str, unsubscribe_url: str
) -> OutgoingEmail:
    return _render(
        settings,
        "expiry_reminder",
        to,
        f"Your {alert.base}/{alert.quote} alert expires on {alert.expires_at:%d %b}",
        unsubscribe_url,
        alert=_alert_context(alert),
        extend_url=extend_url,
    )
