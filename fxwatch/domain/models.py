"""Core value types shared by sources, services, the worker and the UI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class Tier(StrEnum):
    OFFICIAL = "official"
    AGGREGATOR = "aggregator"
    COMMUNITY = "community"


class Condition(StrEnum):
    ABOVE = "above"
    BELOW = "below"
    CROSS = "cross"

    @property
    def describe(self) -> str:
        return {
            Condition.ABOVE: "rises to or above",
            Condition.BELOW: "falls to or below",
            Condition.CROSS: "crosses",
        }[self]


class Mode(StrEnum):
    ONCE = "once"
    RECURRING = "recurring"


class AlertStatus(StrEnum):
    PENDING = "pending"  # waiting for email confirmation
    ACTIVE = "active"
    PAUSED = "paused"
    TRIGGERED = "triggered"  # one-shot alert that has fired
    EXPIRED = "expired"


class NotificationKind(StrEnum):
    CONFIRM_ALERT = "confirm_alert"
    ALERT_TRIGGERED = "alert_triggered"
    MANAGE_LINK = "manage_link"
    EXPIRY_REMINDER = "expiry_reminder"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"  # gave up after max attempts


@dataclass(frozen=True, slots=True)
class RateObservation:
    """One published rate: `value` units of `currency` per 1 unit of the source's base."""

    source_id: str
    rate_date: date
    currency: str
    value: Decimal


@dataclass(frozen=True, slots=True)
class PairQuote:
    """A rate for base→quote derived from a single source."""

    base: str
    quote: str
    rate: Decimal
    rate_date: date
    source_id: str
    derived: bool  # True when computed through the source's base (a cross rate)

    @property
    def inverse(self) -> Decimal:
        return Decimal(1) / self.rate
