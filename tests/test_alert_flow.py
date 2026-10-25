"""End-to-end alert lifecycle against a real (SQLite) database."""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from fxwatch.db import session_scope
from fxwatch.db.models import AlertRow, NotificationRow, SubscriberRow
from fxwatch.domain.models import AlertStatus, Condition, Mode, NotificationStatus
from fxwatch.services import outbox, rates
from fxwatch.services.alerts import AlertError, AlertInput, AlertService, RateLimited, housekeeping
from fxwatch.services.evaluation import evaluate_alerts
from fxwatch.services.tokens import InvalidToken
from tests.conftest import NOW, TODAY, seed


def make_input(**kw):
    defaults = dict(base="EUR", quote="ZAR", condition=Condition.ABOVE, threshold=D("20"))
    return AlertInput(**(defaults | kw))


def create(settings, email="Someone@Example.com", ip="1.2.3.4", now=NOW, **kw):
    with session_scope(settings.database_url) as s:
        return AlertService(s, settings, now=now).create_unconfirmed(email, make_input(**kw), ip).id


def confirm_token_from_outbox(settings, alert_id):
    with session_scope(settings.database_url) as s:
        n = s.scalar(
            select(NotificationRow).where(NotificationRow.dedupe_key == f"confirm:{alert_id}")
        )
        assert n is not None and n.body_text
        return re.search(r"token=([\w.\-]+)", n.body_text).group(1)  # type: ignore[union-attr]


def confirm(settings, alert_id):
    token = confirm_token_from_outbox(settings, alert_id)
    with session_scope(settings.database_url) as s:
        return AlertService(s, settings, now=NOW).confirm(token)


def run_eval(settings, now=NOW):
    with session_scope(settings.database_url) as s:
        snaps = rates.load_snapshots(s, now.date())
        return evaluate_alerts(s, settings, snaps, now)


def alert(settings, alert_id) -> AlertRow:
    with session_scope(settings.database_url) as s:
        row = s.get(AlertRow, alert_id)
        assert row is not None
        return row


def triggered_emails(settings):
    with session_scope(settings.database_url) as s:
        return s.scalars(
            select(NotificationRow).where(NotificationRow.kind == "alert_triggered")
        ).all()


def test_create_confirm_fire_once(db, mailer):
    seed(db, "ecb", TODAY, {"EUR": "1", "ZAR": "19.5"})
    aid = create(db)
    assert alert(db, aid).status == AlertStatus.PENDING

    # Pending alerts are never evaluated.
    run_eval(db)
    assert triggered_emails(db) == []

    result = confirm(db, aid)
    assert result.alert.status == AlertStatus.ACTIVE and not result.already_confirmed
    assert "/manage?token=" in result.manage_url
    assert confirm(db, aid).already_confirmed  # idempotent

    report = run_eval(db)
    assert report.evaluated == 1 and report.fired == 0

    seed(db, "ecb", TODAY + timedelta(days=1), {"EUR": "1", "ZAR": "20.25"})
    report = run_eval(db, NOW + timedelta(days=1))
    assert report.fired == 1
    a = alert(db, aid)
    assert a.status == AlertStatus.TRIGGERED and a.trigger_count == 1
    assert a.last_rate == D("20.25") and a.last_source_id == "ecb"

    [email] = triggered_emails(db)
    assert email.to_email == "someone@example.com"
    assert "20.2500" in email.subject
    assert email.unsubscribe_url and "action=unsubscribe" in email.unsubscribe_url

    # Running again never duplicates the email.
    run_eval(db, NOW + timedelta(days=1, hours=1))
    assert len(triggered_emails(db)) == 1

    with session_scope(db.database_url) as s:
        delivery = outbox.deliver_pending(s, mailer, db.max_send_attempts)
    assert delivery.sent == 2  # confirmation + trigger
    with session_scope(db.database_url) as s:
        sent = s.scalars(select(NotificationRow)).all()
        assert all(n.status == NotificationStatus.SENT and n.body_text is None for n in sent)


def test_recurring_alert_rearms_with_hysteresis(db):
    seed(db, "ecb", TODAY, {"EUR": "1", "ZAR": "20.1"})
    aid = create(db, mode=Mode.RECURRING)
    confirm(db, aid)
    assert run_eval(db).fired == 1

    steps = [
        ("20.3", 0),
        ("19.98", 0),
        ("19.85", 0),
        ("20.05", 1),
    ]  # hover, small dip, re-arm, fire
    for i, (rate, fires) in enumerate(steps, start=1):
        day = TODAY + timedelta(days=i)
        seed(db, "ecb", day, {"EUR": "1", "ZAR": rate})
        assert run_eval(db, NOW + timedelta(days=i)).fired == fires, rate
    assert alert(db, aid).trigger_count == 2


def test_cross_check_holds_alert(db):
    seed(db, "ecb", TODAY, {"EUR": "1", "ZAR": "21"})
    seed(db, "boc", TODAY, {"CAD": "1", "EUR": "0.64", "ZAR": "11.84"})  # 18.5
    seed(db, "currencyapi", TODAY, {"EUR": "1", "ZAR": "18.52"})
    aid = create(db)
    confirm(db, aid)
    report = run_eval(db)
    assert report.held == 1 and report.fired == 0
    assert "sources disagree" in (alert(db, aid).hold_reason or "")


def test_source_preference_respected(db):
    seed(db, "ecb", TODAY, {"EUR": "1", "ZAR": "19"})
    seed(db, "erapi", TODAY, {"USD": "1", "EUR": "0.9", "ZAR": "18.27"})  # 20.3
    aid = create(db, source_preference="erapi", threshold=D("20.2"))
    confirm(db, aid)
    # erapi vs ECB disagree by ~6.6%, so this is held rather than fired on the weaker source.
    assert run_eval(db).held == 1


def test_validation_errors(db):
    with pytest.raises(AlertError, match="valid email"):
        create(db, email="not-an-email")
    with pytest.raises(AlertError, match="different currencies"):
        create(db, quote="EUR")
    with pytest.raises(AlertError, match="positive"):
        create(db, threshold=D("0"))
    with pytest.raises(AlertError, match="Unsupported"):
        create(db, quote="BTC")


def test_rate_limits_and_quota(db):
    db.alert_creations_per_email_per_hour = 2
    create(db)
    create(db)
    with pytest.raises(RateLimited):
        create(db)
    # An hour later the window has passed.
    create(db, now=NOW + timedelta(hours=1, minutes=1))

    db.alert_creations_per_email_per_hour = 100
    db.max_active_alerts_per_email = 4
    create(db, now=NOW + timedelta(hours=2))
    with pytest.raises(AlertError, match="already have 4"):
        create(db, now=NOW + timedelta(hours=2))


def test_manage_link_rotation_and_erasure(db):
    aid = create(db)
    result = confirm(db, aid)
    token = result.manage_url.split("token=")[1]

    with session_scope(db.database_url) as s:
        svc = AlertService(s, db, now=NOW)
        sub = svc.subscriber_from_token(token)
        svc.rotate_link(sub)

    with session_scope(db.database_url) as s, pytest.raises(InvalidToken):
        AlertService(s, db, now=NOW).subscriber_from_token(token)

    with session_scope(db.database_url) as s:
        sub = s.scalar(select(SubscriberRow))
        assert sub is not None
        new_token = AlertService(s, db).manage_url(sub).split("token=")[1]
    with session_scope(db.database_url) as s:
        svc = AlertService(s, db, now=NOW)
        svc.delete_everything(svc.subscriber_from_token(new_token))
    with session_scope(db.database_url) as s:
        assert s.scalar(select(SubscriberRow)) is None
        assert s.scalar(select(AlertRow)) is None


def test_request_manage_link_is_silent_for_unknown_email(db):
    with session_scope(db.database_url) as s:
        assert (
            AlertService(s, db, now=NOW).request_manage_link("nobody@example.com", "9.9.9.9")
            is None
        )


def test_tampered_tokens_rejected(db):
    aid = create(db)
    token = confirm_token_from_outbox(db, aid)
    with session_scope(db.database_url) as s, pytest.raises(InvalidToken):
        AlertService(s, db, now=NOW).confirm(token[:-2] + "xx")


def test_expiry_and_reminder(db):
    seed(db, "ecb", TODAY, {"EUR": "1", "ZAR": "19"})
    aid = create(db, lifetime_days=30)
    confirm(db, aid)
    later = NOW + timedelta(days=25)
    seed(db, "ecb", later.date(), {"EUR": "1", "ZAR": "19"})
    assert run_eval(db, later).reminders == 1
    assert run_eval(db, later).reminders == 0
    assert run_eval(db, NOW + timedelta(days=31)).expired == 1
    assert alert(db, aid).status == AlertStatus.EXPIRED


def test_housekeeping_removes_stale_pending(db):
    create(db)
    with session_scope(db.database_url) as s:
        report = housekeeping(s, NOW + timedelta(days=8))
    assert report == {"pending_alerts_removed": 1, "subscribers_removed": 1}
