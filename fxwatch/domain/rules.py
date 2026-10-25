"""Alert rule evaluation. Pure functions; the alert service persists the outcome.

Firing semantics
----------------
* ABOVE / BELOW fire while the condition holds and the alert is *armed*. After firing,
  a recurring alert disarms and re-arms only once the rate retreats past the threshold by
  `rearm_margin_pct` (hysteresis), so a rate hovering at the threshold doesn't send an
  email every hour.
* CROSS fires when the rate moves from one side of the threshold to the other between two
  consecutive evaluations. It needs a previous rate and never disarms.
* Recurring alerts additionally respect a minimum cooldown between emails.
* One-shot alerts are marked TRIGGERED by the caller after their first firing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from fxwatch.domain.models import Condition


@dataclass(frozen=True, slots=True)
class RuleState:
    condition: Condition
    threshold: Decimal
    armed: bool = True
    last_rate: Decimal | None = None
    last_triggered_at: datetime | None = None
    cooldown: timedelta = timedelta(hours=24)
    rearm_margin_pct: Decimal = Decimal("0.5")


@dataclass(frozen=True, slots=True)
class Outcome:
    fire: bool
    armed: bool
    reason: str


def condition_met(state: RuleState, rate: Decimal) -> bool:
    t = state.threshold
    if state.condition is Condition.ABOVE:
        return rate >= t
    if state.condition is Condition.BELOW:
        return rate <= t
    prev = state.last_rate
    if prev is None:
        return False
    return (prev < t <= rate) or (prev > t >= rate)


def _rearm_reached(state: RuleState, rate: Decimal) -> bool:
    margin = state.rearm_margin_pct / 100
    if state.condition is Condition.ABOVE:
        return rate < state.threshold * (1 - margin)
    if state.condition is Condition.BELOW:
        return rate > state.threshold * (1 + margin)
    return True


def evaluate(state: RuleState, rate: Decimal, now: datetime) -> Outcome:
    armed = state.armed
    if not armed:
        if _rearm_reached(state, rate):
            return Outcome(False, True, "re-armed: rate moved back past the threshold margin")
        return Outcome(False, False, "disarmed: waiting for the rate to move back")

    if not condition_met(state, rate):
        return Outcome(False, True, "condition not met")

    if state.last_triggered_at is not None and now - state.last_triggered_at < state.cooldown:
        return Outcome(False, True, "condition met but still in cooldown")

    # CROSS alerts stay armed; level alerts disarm until the rate retreats.
    return Outcome(True, state.condition is Condition.CROSS, "condition met")
