"""Alert lifecycle: create → confirm → (pause/resume/edit/extend) → trigger/expire → delete.

There are no accounts. A person is identified by an email address they have proven they
control, either by clicking a confirmation link or by holding a signed management link.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from fxwatch import currencies
from fxwatch.config import Settings
from fxwatch.db.models import AlertRow, SubscriberRow
from fxwatch.db.types import utcnow
from fxwatch.domain.models import AlertStatus, Condition, Mode, NotificationKind
from fxwatch.notify import emails
from fxwatch.services import outbox, ratelimit
from fxwatch.services.rates import AUTO
from fxwatch.services.tokens import InvalidToken, TokenService
from fxwatch.sources import SOURCE_INFO

EMAIL_RE = re.compile(
    r"^[^@\s<>\"',;]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$"
)
LIFETIME_CHOICES = (30, 90, 180, 365)
OPEN_STATUSES = (AlertStatus.PENDING.value, AlertStatus.ACTIVE.value, AlertStatus.PAUSED.value)


class AlertError(Exception):
    """A problem the user can fix; the message is safe to show in the UI."""


class RateLimited(AlertError):
    pass


def normalise_email(raw: str) -> str:
    email = (raw or "").strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise AlertError("Please enter a valid email address.")
    return email


@dataclass
class AlertInput:
    base: str
    quote: str
    condition: Condition
    threshold: Decimal
    mode: Mode = Mode.ONCE
    source_preference: str = AUTO
    label: str | None = None
    lifetime_days: int = 90
    cooldown_hours: int = 24

    def validated(self) -> AlertInput:
        self.base, self.quote = self.base.upper(), self.quote.upper()
        if not currencies.is_supported(self.base) or not currencies.is_supported(self.quote):
            raise AlertError("Unsupported currency.")
        if self.base == self.quote:
            raise AlertError("Choose two different currencies.")
        try:
            self.threshold = Decimal(str(self.threshold))
        except InvalidOperation as exc:
            raise AlertError("The threshold must be a number.") from exc
        if not self.threshold.is_finite() or self.threshold <= 0:
            raise AlertError("The threshold must be a positive number.")
        if self.threshold.as_tuple().exponent < -10:  # type: ignore[operator]
            raise AlertError("The threshold has too many decimal places.")
        if self.source_preference != AUTO and self.source_preference not in SOURCE_INFO:
            raise AlertError("Unknown data source.")
        if self.lifetime_days not in LIFETIME_CHOICES:
            raise AlertError("Invalid alert lifetime.")
        if not 1 <= self.cooldown_hours <= 24 * 14:
            raise AlertError("Cooldown must be between 1 hour and 14 days.")
        self.label = (self.label or "").strip()[:120] or None
        return self


@dataclass(frozen=True)
class ConfirmResult:
    alert: AlertRow
    manage_url: str
    already_confirmed: bool


class AlertService:
    def __init__(self, session: Session, settings: Settings, now: datetime | None = None) -> None:
        self.session = session
        self.settings = settings
        self.tokens = TokenService(settings.secret_key, settings.app_base_url)
        self.now = now or utcnow()

    # ------------------------------------------------------------------ helpers
    def _limit(self, key: str, limit: int, message: str) -> None:
        if not ratelimit.hit(self.session, key, limit, timedelta(hours=1), self.now):
            raise RateLimited(message)

    def _subscriber_for(self, email: str) -> SubscriberRow:
        sub = self.session.scalar(select(SubscriberRow).where(SubscriberRow.email == email))
        if sub is None:
            sub = SubscriberRow(email=email, created_at=self.now, token_version=1)
            self.session.add(sub)
            self.session.flush()
        return sub

    def _open_alert_count(self, sub: SubscriberRow) -> int:
        return (
            self.session.scalar(
                select(func.count())
                .select_from(AlertRow)
                .where(AlertRow.subscriber_id == sub.id, AlertRow.status.in_(OPEN_STATUSES))
            )
            or 0
        )

    def _new_alert(self, sub: SubscriberRow, inp: AlertInput, status: AlertStatus) -> AlertRow:
        if self._open_alert_count(sub) >= self.settings.max_active_alerts_per_email:
            raise AlertError(
                f"You already have {self.settings.max_active_alerts_per_email} alerts. "
                "Delete some before adding more."
            )
        alert = AlertRow(
            subscriber_id=sub.id,
            base=inp.base,
            quote=inp.quote,
            condition=inp.condition.value,
            threshold=inp.threshold,
            mode=inp.mode.value,
            source_preference=inp.source_preference,
            label=inp.label,
            status=status.value,
            cooldown_hours=inp.cooldown_hours,
            rearm_margin_pct=Decimal("0.5"),
            armed=True,
            trigger_count=0,
            created_at=self.now,
            confirmed_at=self.now if status is AlertStatus.ACTIVE else None,
            expires_at=self.now + timedelta(days=inp.lifetime_days),
        )
        self.session.add(alert)
        self.session.flush()
        return alert

    def manage_url(self, sub: SubscriberRow, **extra: str | int) -> str:
        return self.tokens.manage_url(sub.id, sub.token_version, **extra)

    def unsubscribe_url(self, sub: SubscriberRow) -> str:
        return self.manage_url(sub, action="unsubscribe")

    def _owned(self, sub: SubscriberRow, alert_id: int) -> AlertRow:
        alert = self.session.get(AlertRow, alert_id)
        if alert is None or alert.subscriber_id != sub.id:
            raise AlertError("Alert not found.")
        return alert

    # ------------------------------------------------------------------ public API
    def create_unconfirmed(self, raw_email: str, inp: AlertInput, ip: str | None) -> AlertRow:
        """Create a PENDING alert and queue a confirmation email (anonymous visitors)."""
        email = normalise_email(raw_email)
        inp.validated()
        busy = "Too many alert requests. Please try again in an hour."
        self._limit(
            f"create:email:{self.tokens.fingerprint(email)}",
            self.settings.alert_creations_per_email_per_hour,
            busy,
        )
        if ip:
            self._limit(
                f"create:ip:{self.tokens.fingerprint(ip)}",
                self.settings.alert_creations_per_ip_per_hour,
                busy,
            )
        sub = self._subscriber_for(email)
        alert = self._new_alert(sub, inp, AlertStatus.PENDING)
        outbox.enqueue(
            self.session,
            NotificationKind.CONFIRM_ALERT,
            f"confirm:{alert.id}",
            emails.confirm_alert(self.settings, email, alert, self.tokens.confirm_url(alert.id)),
            alert_id=alert.id,
        )
        return alert

    def create_for_subscriber(self, sub: SubscriberRow, inp: AlertInput) -> AlertRow:
        """Create an ACTIVE alert for someone holding a valid management link."""
        inp.validated()
        self._limit(
            f"create:email:{self.tokens.fingerprint(sub.email)}",
            self.settings.alert_creations_per_email_per_hour * 2,
            "You've added a lot of alerts recently. Please try again in an hour.",
        )
        return self._new_alert(sub, inp, AlertStatus.ACTIVE)

    def confirm(self, token: str) -> ConfirmResult:
        max_age = self.settings.confirmation_token_max_age_hours * 3600
        alert_id = self.tokens.read_confirm_token(token, max_age)
        alert = self.session.get(AlertRow, alert_id)
        if alert is None:
            raise InvalidToken("This alert no longer exists.")
        sub = alert.subscriber
        already = alert.status != AlertStatus.PENDING.value
        if not already:
            alert.status = AlertStatus.ACTIVE.value
            alert.confirmed_at = self.now
            alert.armed = True
        if sub.verified_at is None:
            sub.verified_at = self.now
        return ConfirmResult(alert, self.manage_url(sub), already)

    def subscriber_from_token(self, token: str) -> SubscriberRow:
        claims = self.tokens.read_manage_token(token)
        sub = self.session.get(SubscriberRow, claims.subscriber_id)
        if sub is None or sub.token_version != claims.version:
            raise InvalidToken("This management link is invalid or has been replaced.")
        if sub.verified_at is None:  # holding a valid link proves ownership
            sub.verified_at = self.now
        return sub

    def request_manage_link(self, raw_email: str, ip: str | None) -> str | None:
        """Email a management link if the address has alerts. Never reveals whether it does.

        Returns the outbox key of the queued email (for immediate delivery), or None.
        """
        email = normalise_email(raw_email)
        self._limit(
            f"manage:email:{self.tokens.fingerprint(email)}",
            self.settings.manage_link_requests_per_email_per_hour,
            "Too many requests for this address. Please try again in an hour.",
        )
        if ip:
            self._limit(
                f"manage:ip:{self.tokens.fingerprint(ip)}",
                self.settings.alert_creations_per_ip_per_hour,
                "Too many requests. Please try again in an hour.",
            )
        sub = self.session.scalar(select(SubscriberRow).where(SubscriberRow.email == email))
        if sub is None or not sub.alerts:
            return None
        return self._send_manage_link(sub, rotated=False)

    def rotate_link(self, sub: SubscriberRow) -> str:
        """Invalidate every existing management link and email a fresh one."""
        sub.token_version += 1
        self.session.flush()
        return self._send_manage_link(sub, rotated=True)

    def _send_manage_link(self, sub: SubscriberRow, rotated: bool) -> str:
        key = f"manage:{sub.id}:{sub.token_version}:{self.now.isoformat()}"
        outbox.enqueue(
            self.session,
            NotificationKind.MANAGE_LINK,
            key,
            emails.manage_link(
                self.settings, sub.email, self.manage_url(sub), list(sub.alerts), rotated
            ),
        )
        return key

    def list_alerts(self, sub: SubscriberRow) -> list[AlertRow]:
        return list(
            self.session.scalars(
                select(AlertRow)
                .where(AlertRow.subscriber_id == sub.id)
                .order_by(AlertRow.created_at.desc())
            )
        )

    def pause(self, sub: SubscriberRow, alert_id: int) -> AlertRow:
        alert = self._owned(sub, alert_id)
        if alert.status == AlertStatus.ACTIVE.value:
            alert.status = AlertStatus.PAUSED.value
        return alert

    def resume(self, sub: SubscriberRow, alert_id: int) -> AlertRow:
        """Resume a paused alert, or re-arm a one-time alert that has already fired."""
        alert = self._owned(sub, alert_id)
        if alert.status in (
            AlertStatus.PAUSED.value,
            AlertStatus.TRIGGERED.value,
            AlertStatus.PENDING.value,
        ):
            alert.status = AlertStatus.ACTIVE.value
            alert.armed = True
            alert.hold_reason = None
            alert.confirmed_at = alert.confirmed_at or self.now
        if alert.expires_at <= self.now:
            self.extend(sub, alert_id)
        return alert

    def extend(self, sub: SubscriberRow, alert_id: int, days: int | None = None) -> AlertRow:
        alert = self._owned(sub, alert_id)
        days = days or self.settings.default_alert_lifetime_days
        alert.expires_at = max(alert.expires_at, self.now) + timedelta(days=days)
        alert.reminder_sent_at = None
        if alert.status == AlertStatus.EXPIRED.value:
            alert.status = AlertStatus.ACTIVE.value
            alert.armed = True
        return alert

    def update(
        self,
        sub: SubscriberRow,
        alert_id: int,
        *,
        threshold: Decimal | None = None,
        condition: Condition | None = None,
        mode: Mode | None = None,
        label: str | None = None,
    ) -> AlertRow:
        alert = self._owned(sub, alert_id)
        probe = AlertInput(
            alert.base,
            alert.quote,
            condition or Condition(alert.condition),
            threshold if threshold is not None else alert.threshold,
            mode or Mode(alert.mode),
            alert.source_preference,
            label if label is not None else alert.label,
            LIFETIME_CHOICES[0],
            alert.cooldown_hours,
        ).validated()
        changed_rule = (
            probe.threshold != alert.threshold or probe.condition.value != alert.condition
        )
        alert.threshold = probe.threshold
        alert.condition = probe.condition.value
        alert.mode = probe.mode.value
        alert.label = probe.label
        if changed_rule:
            alert.armed = True
            alert.last_rate = None  # a CROSS rule must observe a fresh "before" value
            if alert.status == AlertStatus.TRIGGERED.value:
                alert.status = AlertStatus.ACTIVE.value
        return alert

    def delete_alert(self, sub: SubscriberRow, alert_id: int) -> None:
        self.session.delete(self._owned(sub, alert_id))

    def delete_everything(self, sub: SubscriberRow) -> None:
        """Right to erasure: remove the subscriber and all their alerts."""
        self.session.delete(sub)


def housekeeping(session: Session, now: datetime) -> dict[str, int]:
    """Remove stale unconfirmed alerts and orphaned, never-verified subscribers."""
    stale_pending = session.execute(
        delete(AlertRow).where(
            AlertRow.status == AlertStatus.PENDING.value,
            AlertRow.created_at < now - timedelta(days=7),
        )
    )
    has_alerts = select(AlertRow.id).where(AlertRow.subscriber_id == SubscriberRow.id).exists()
    orphans = session.execute(
        delete(SubscriberRow).where(
            SubscriberRow.created_at < now - timedelta(days=7),
            ~has_alerts,
        )
    )
    return {
        "pending_alerts_removed": int(getattr(stale_pending, "rowcount", 0) or 0),
        "subscribers_removed": int(getattr(orphans, "rowcount", 0) or 0),
    }
