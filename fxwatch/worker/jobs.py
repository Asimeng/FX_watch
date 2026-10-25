"""Worker jobs. `run_once` is one complete, idempotent pass; schedulers just call it.

On GitHub Actions a cron workflow runs `python -m fxwatch run-once`; with Docker the
`serve` command calls it in a loop. Late, skipped or duplicated runs are all harmless.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import delete

from fxwatch.config import Settings
from fxwatch.db import session_scope, upgrade
from fxwatch.db.models import FetchRunRow, SourceStatusRow
from fxwatch.db.types import utcnow
from fxwatch.notify.mailer import Mailer, get_mailer
from fxwatch.services import alerts, outbox, ratelimit, rates
from fxwatch.services.evaluation import evaluate_alerts
from fxwatch.sources import SOURCE_CLASSES, Source, SourceError, build_client

log = logging.getLogger(__name__)


@dataclass
class FetchResult:
    source_id: str
    kind: str
    ok: bool
    received: int = 0
    inserted: int = 0
    error: str | None = None


@dataclass
class RunReport:
    started_at: datetime
    fetches: list[FetchResult] = field(default_factory=list)
    evaluation: dict[str, int] = field(default_factory=dict)
    emails_sent: int = 0
    emails_failed: int = 0
    housekeeping: dict[str, int] = field(default_factory=dict)
    duration_s: float = 0.0

    @property
    def all_sources_failed(self) -> bool:
        latest = [f for f in self.fetches if f.kind == "latest"]
        return bool(latest) and not any(f.ok for f in latest)


def _record(
    settings: Settings, result: FetchResult, started: datetime, latest_date: date | None
) -> None:
    with session_scope(settings.database_url) as s:
        s.add(
            FetchRunRow(
                source_id=result.source_id,
                kind=result.kind,
                started_at=started,
                finished_at=utcnow(),
                ok=result.ok,
                rows_received=result.received,
                rows_inserted=result.inserted,
                error=result.error,
            )
        )
        status = s.get(SourceStatusRow, result.source_id) or SourceStatusRow(
            source_id=result.source_id, consecutive_failures=0
        )
        status.last_attempt_at = started
        if result.ok:
            status.last_success_at = utcnow()
            status.last_error = None
            status.consecutive_failures = 0
            if latest_date and (
                status.latest_rate_date is None or latest_date > status.latest_rate_date
            ):
                status.latest_rate_date = latest_date
        else:
            status.last_error = result.error
            status.consecutive_failures = (status.consecutive_failures or 0) + 1
        s.merge(status)


def fetch_source(
    settings: Settings, source: Source, kind: str, start: date | None = None
) -> FetchResult:
    """Fetch latest (or historical) rates for one source and store them. Never raises."""
    started = utcnow()
    sid = source.info.id
    try:
        if kind == "backfill":
            rows = source.fetch_history(
                start or date.today() - timedelta(days=settings.backfill_days), date.today()
            )
        else:
            rows = source.fetch_latest()
        with session_scope(settings.database_url) as s:
            inserted = rates.store_observations(s, rows)
        result = FetchResult(sid, kind, True, len(rows), inserted)
        latest = max((r.rate_date for r in rows), default=None)
        log.info("%s %s: %d rows, %d new", sid, kind, len(rows), inserted)
    except SourceError as exc:
        result, latest = FetchResult(sid, kind, False, error=str(exc)), None
        log.error("%s %s failed: %s", sid, kind, exc)
    except Exception as exc:  # a bug in one adapter must not stop the others
        result, latest = FetchResult(sid, kind, False, error=f"{type(exc).__name__}: {exc}"), None
        log.exception("%s %s crashed", sid, kind)
    _record(settings, result, started, latest)
    return result


def fetch_all(
    settings: Settings, only: str | None = None, backfill_missing: bool = True
) -> list[FetchResult]:
    results: list[FetchResult] = []
    with session_scope(settings.database_url) as s:
        counts = rates.observation_counts(s)
    with build_client(settings.http_user_agent, settings.http_timeout_seconds) as client:
        for cls in SOURCE_CLASSES:
            if only and cls.info.id != only:
                continue
            source = cls(client)
            days = settings.backfill_days
            if (
                backfill_missing
                and source.supports_history
                and days
                and not counts.get(cls.info.id)
            ):
                log.info("%s has no history yet; backfilling %d days", cls.info.id, days)
                results.append(
                    fetch_source(settings, source, "backfill", date.today() - timedelta(days=days))
                )
            results.append(fetch_source(settings, source, "latest"))
    return results


def backfill(settings: Settings, days: int, only: str | None = None) -> list[FetchResult]:
    start = date.today() - timedelta(days=days)
    results = []
    with build_client(settings.http_user_agent, settings.http_timeout_seconds) as client:
        for cls in SOURCE_CLASSES:
            if only and cls.info.id != only:
                continue
            source = cls(client)
            if source.supports_history:
                results.append(fetch_source(settings, source, "backfill", start))
    return results


def evaluate(settings: Settings, now: datetime | None = None) -> dict[str, int]:
    now = now or utcnow()
    with session_scope(settings.database_url) as s:
        snaps = rates.load_snapshots(s, now.date())
        return asdict(evaluate_alerts(s, settings, snaps, now))


def deliver(settings: Settings, mailer: Mailer | None = None) -> outbox.DeliveryReport:
    with session_scope(settings.database_url) as s:
        return outbox.deliver_pending(s, mailer or get_mailer(settings), settings.max_send_attempts)


def housekeeping(settings: Settings, now: datetime | None = None) -> dict[str, int]:
    now = now or utcnow()
    with session_scope(settings.database_url) as s:
        report = alerts.housekeeping(s, now)
        report["rate_limit_events_removed"] = ratelimit.prune(s, now - timedelta(days=2))
        report["notifications_removed"] = outbox.prune(s, now)
        runs = s.execute(
            delete(FetchRunRow).where(FetchRunRow.started_at < now - timedelta(days=30))
        )
        report["fetch_runs_removed"] = int(getattr(runs, "rowcount", 0) or 0)
    return report


def run_once(settings: Settings, mailer: Mailer | None = None, migrate: bool = True) -> RunReport:
    t0 = time.monotonic()
    report = RunReport(started_at=utcnow())
    if migrate:
        upgrade(settings.database_url)
    report.fetches = fetch_all(settings)
    report.evaluation = evaluate(settings)
    delivery = deliver(settings, mailer)
    report.emails_sent, report.emails_failed = delivery.sent, delivery.failed
    report.housekeeping = housekeeping(settings)
    report.duration_s = round(time.monotonic() - t0, 2)
    log.info(
        "run complete",
        extra={
            "fetches": [asdict(f) for f in report.fetches],
            "evaluation": report.evaluation,
            "emails_sent": report.emails_sent,
            "emails_failed": report.emails_failed,
            "duration_s": report.duration_s,
        },
    )
    return report


def serve(settings: Settings) -> None:
    """Long-running mode for Docker/VPS deployments."""
    upgrade(settings.database_url)
    interval = max(settings.worker_interval_minutes, 5) * 60
    log.info("worker started; running every %d minutes", interval // 60)
    while True:
        try:
            run_once(settings, migrate=False)
        except Exception:
            log.exception("worker pass failed")
        time.sleep(interval)
