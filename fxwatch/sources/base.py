"""Source adapter contract and shared HTTP plumbing."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Context, Decimal, InvalidOperation
from typing import ClassVar

import httpx

from fxwatch.currencies import CURRENCIES
from fxwatch.domain.models import RateObservation, Tier

log = logging.getLogger(__name__)

# Sources publish 4-10 significant digits; derived values (e.g. inverted CAD rates) are
# rounded to 14 so stored strings stay compact without losing real precision.
_STORE_PRECISION = Context(prec=14)


class SourceError(RuntimeError):
    """A source could not be fetched or its response could not be understood."""


@dataclass(frozen=True, slots=True)
class SourceInfo:
    id: str
    name: str
    tier: Tier
    base: str
    priority: int  # lower wins when several sources can price a pair
    homepage: str
    attribution: str
    description: str
    schedule: str
    max_age_days: int  # observations older than this are considered stale
    history_from: date | None  # earliest date fetch_history can return, if supported


class Source(ABC):
    info: ClassVar[SourceInfo]

    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    @abstractmethod
    def fetch_latest(self) -> list[RateObservation]: ...

    def fetch_history(self, start: date, end: date) -> list[RateObservation]:
        raise SourceError(f"{self.info.name} does not publish historical rates")

    @property
    def supports_history(self) -> bool:
        return self.info.history_from is not None

    # -- helpers for subclasses ------------------------------------------------------------
    def _get(self, url: str, **params: str) -> httpx.Response:
        return get_with_retry(self.client, url, params=params or None)

    def _observations(
        self, rate_date: date, values: Iterable[tuple[str, Decimal]]
    ) -> list[RateObservation]:
        """Normalise codes, drop unsupported currencies, and add the base at 1."""
        out: dict[str, RateObservation] = {}
        for code, value in values:
            code = code.upper()
            if code not in CURRENCIES or value <= 0:
                continue
            out[code] = RateObservation(self.info.id, rate_date, code, _STORE_PRECISION.plus(value))
        out[self.info.base] = RateObservation(self.info.id, rate_date, self.info.base, Decimal(1))
        return list(out.values())


def to_decimal(raw: object) -> Decimal | None:
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def build_client(user_agent: str, timeout: float) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip"},
        timeout=timeout,
        follow_redirects=True,
        transport=httpx.HTTPTransport(retries=2),  # connection-level retries
    )


_RETRY_STATUSES = {429, 500, 502, 503, 504}


def get_with_retry(
    client: httpx.Client,
    url: str,
    params: dict[str, str] | None = None,
    attempts: int = 3,
    backoff: float = 1.5,
) -> httpx.Response:
    """GET with exponential backoff on throttling and server errors."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = client.get(url, params=params)
            if response.status_code in _RETRY_STATUSES and attempt < attempts:
                raise httpx.HTTPStatusError(
                    f"retryable status {response.status_code}",
                    request=response.request,
                    response=response,
                )
            response.raise_for_status()
            return response
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_error = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None and status not in _RETRY_STATUSES:
                break
            if attempt < attempts:
                delay = backoff**attempt
                log.warning("GET %s failed (%s); retrying in %.1fs", url, exc, delay)
                time.sleep(delay)
    raise SourceError(f"GET {url} failed: {last_error}") from last_error
