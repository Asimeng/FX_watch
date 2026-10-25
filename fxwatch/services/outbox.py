"""Transactional email outbox.

Emails are written to the `notifications` table in the same transaction as the state
change that caused them (e.g. an alert firing), then delivered separately. A crash can
therefore never lose an email or send it twice, and failed sends are retried.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fxwatch.db.models import NotificationRow
from fxwatch.db.types import utcnow
from fxwatch.domain.models import NotificationKind, NotificationStatus
from fxwatch.notify.mailer import Mailer, MailError, OutgoingEmail

log = logging.getLogger(__name__)


def enqueue(
    session: Session,
    kind: NotificationKind,
    dedupe_key: str,
    email: OutgoingEmail,
    alert_id: int | None = None,
) -> NotificationRow | None:
    """Queue an email. Returns None if one with the same dedupe key already exists."""
    existing = session.scalar(
        select(NotificationRow).where(NotificationRow.dedupe_key == dedupe_key)
    )
    if existing is not None:
        return None
    row = NotificationRow(
        kind=kind.value,
        dedupe_key=dedupe_key,
        alert_id=alert_id,
        to_email=email.to,
        subject=email.subject[:200],
        body_text=email.text,
        body_html=email.html,
        unsubscribe_url=email.unsubscribe_url,
        status=NotificationStatus.PENDING.value,
    )
    try:
        with session.begin_nested():
            session.add(row)
    except IntegrityError:  # lost a race with a concurrent writer
        return None
    return row


def deliver(session: Session, row: NotificationRow, mailer: Mailer, max_attempts: int) -> bool:
    """Try to send one queued email and record the outcome. Caller commits."""
    if row.status != NotificationStatus.PENDING.value:
        return row.status == NotificationStatus.SENT.value
    row.attempts += 1
    try:
        mailer.send(
            OutgoingEmail(
                to=row.to_email,
                subject=row.subject,
                text=row.body_text or "",
                html=row.body_html,
                unsubscribe_url=row.unsubscribe_url,
            )
        )
    except MailError as exc:
        row.last_error = str(exc)[:2000]
        if row.attempts >= max_attempts:
            row.status = NotificationStatus.FAILED.value
        log.warning("email delivery failed (attempt %d): %s", row.attempts, exc)
        return False
    row.status = NotificationStatus.SENT.value
    row.sent_at = utcnow()
    row.last_error = None
    row.body_text = row.body_html = None  # don't keep live links in the database
    return True


@dataclass
class DeliveryReport:
    sent: int = 0
    failed: int = 0


def deliver_pending(
    session: Session, mailer: Mailer, max_attempts: int, limit: int = 200
) -> DeliveryReport:
    report = DeliveryReport()
    ids = session.scalars(
        select(NotificationRow.id)
        .where(NotificationRow.status == NotificationStatus.PENDING.value)
        .order_by(NotificationRow.created_at)
        .limit(limit)
    ).all()
    for notification_id in ids:
        row = session.get(NotificationRow, notification_id)
        if row is None:
            continue
        if deliver(session, row, mailer, max_attempts):
            report.sent += 1
        else:
            report.failed += 1
        session.commit()  # commit per email so a crash can't cause re-sends
    return report


def prune(session: Session, now: datetime) -> int:
    result = session.execute(
        delete(NotificationRow).where(
            (
                (NotificationRow.status == NotificationStatus.SENT.value)
                & (NotificationRow.created_at < now - timedelta(days=30))
            )
            | (
                (NotificationRow.status == NotificationStatus.FAILED.value)
                & (NotificationRow.created_at < now - timedelta(days=90))
            )
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)
