"""Evaluate every active alert against the latest rates and queue emails for those that fire."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from fxwatch.config import Settings
from fxwatch.db.models import AlertRow
from fxwatch.domain.models import AlertStatus, Condition, Mode, NotificationKind, PairQuote
from fxwatch.domain.rules import RuleState, evaluate
from fxwatch.notify import emails
from fxwatch.services import analytics, outbox, rates
from fxwatch.services.alerts import AlertService
from fxwatch.services.rates import AUTO, Snapshots

log = logging.getLogger(__name__)

MIN_STATS_OBSERVATIONS = 10


@dataclass
class EvaluationReport:
    evaluated: int = 0
    fired: int = 0
    held: int = 0
    no_rate: int = 0
    expired: int = 0
    reminders: int = 0


def _rule_state(alert: AlertRow) -> RuleState:
    return RuleState(
        condition=Condition(alert.condition),
        threshold=alert.threshold,
        armed=alert.armed,
        last_rate=alert.last_rate,
        last_triggered_at=alert.last_triggered_at,
        cooldown=timedelta(hours=alert.cooldown_hours),
        rearm_margin_pct=alert.rearm_margin_pct or Decimal("0.5"),
    )


def evaluate_alerts(
    session: Session, settings: Settings, snaps: Snapshots, now: datetime
) -> EvaluationReport:
    report = EvaluationReport()
    service = AlertService(session, settings, now=now)
    today = now.date()
    quote_cache: dict[tuple[str, str], list[PairQuote]] = {}

    active = session.scalars(
        select(AlertRow)
        .where(AlertRow.status == AlertStatus.ACTIVE.value)
        .options(selectinload(AlertRow.subscriber))
    ).all()

    for alert in active:
        sub = alert.subscriber

        if alert.expires_at <= now:
            alert.status = AlertStatus.EXPIRED.value
            report.expired += 1
            continue

        if alert.reminder_sent_at is None and alert.expires_at - now <= timedelta(
            days=settings.expiry_reminder_days
        ):
            outbox.enqueue(
                session,
                NotificationKind.EXPIRY_REMINDER,
                f"expiry:{alert.id}:{alert.expires_at.date().isoformat()}",
                emails.expiry_reminder(
                    settings,
                    sub.email,
                    alert,
                    service.manage_url(sub, action="extend", alert=alert.id),
                    service.unsubscribe_url(sub),
                ),
                alert_id=alert.id,
            )
            alert.reminder_sent_at = now
            report.reminders += 1

        key = (alert.base, alert.quote)
        if key not in quote_cache:
            quote_cache[key] = rates.quotes_for_pair(snaps, alert.base, alert.quote, today)
        quotes = quote_cache[key]
        candidates = (
            quotes
            if alert.source_preference == AUTO
            else [q for q in quotes if q.source_id == alert.source_preference]
        )
        alert.last_evaluated_at = now
        if not candidates:
            alert.hold_reason = "No fresh rate is currently available for this pair."
            report.no_rate += 1
            continue

        primary = candidates[0]
        check = rates.cross_check(quotes, primary, settings.cross_check_tolerance_pct)
        if not check.ok:
            alert.hold_reason = f"Held: sources disagree. {check.detail}"
            log.warning("alert %s held by cross-check: %s", alert.id, check.detail)
            report.held += 1
            continue

        report.evaluated += 1
        outcome = evaluate(_rule_state(alert), primary.rate, now)
        if outcome.fire:
            alert.trigger_count += 1
            alert.last_triggered_at = now
            if alert.mode == Mode.ONCE.value:
                alert.status = AlertStatus.TRIGGERED.value
            window = rates.history(
                session,
                alert.base,
                alert.quote,
                today - timedelta(days=90),
                today,
                primary.source_id,
            )
            stats = analytics.describe(window.series)
            if stats is not None and stats.observations < MIN_STATS_OBSERVATIONS:
                stats = None  # too little history to say anything meaningful
            facts = emails.TriggerFacts(primary, stats, now)
            outbox.enqueue(
                session,
                NotificationKind.ALERT_TRIGGERED,
                f"alert:{alert.id}:trigger:{alert.trigger_count}",
                emails.alert_triggered(
                    settings,
                    sub.email,
                    alert,
                    facts,
                    service.manage_url(sub),
                    service.unsubscribe_url(sub),
                ),
                alert_id=alert.id,
            )
            report.fired += 1
            log.info("alert %s fired: %s at %s", alert.id, alert.pair, primary.rate)

        alert.armed = outcome.armed
        alert.last_rate = primary.rate
        alert.last_rate_date = primary.rate_date
        alert.last_source_id = primary.source_id
        alert.hold_reason = None

    return report
