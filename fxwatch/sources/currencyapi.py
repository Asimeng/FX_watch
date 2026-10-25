"""Open community currency dataset (fawazahmed0/exchange-api), served from jsDelivr.

Used mainly for its daily history of currencies the official sources don't cover
(GHS, NGN, KES, ...). Lowest priority: only used when nothing better prices a pair.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal

from fxwatch.domain.models import RateObservation, Tier
from fxwatch.sources.base import Source, SourceError, SourceInfo

log = logging.getLogger(__name__)

PRIMARY = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{tag}/v1/currencies/eur.json"
FALLBACK = "https://{tag}.currency-api.pages.dev/v1/currencies/eur.json"


class CurrencyApiSource(Source):
    info = SourceInfo(
        id="currencyapi",
        name="Currency API (open dataset)",
        tier=Tier.COMMUNITY,
        base="EUR",
        priority=40,
        homepage="https://github.com/fawazahmed0/exchange-api",
        attribution="Historical data: fawazahmed0/exchange-api (CC0), via jsDelivr.",
        description=(
            "Free, open dataset republished daily from public market data. Provides daily "
            "history since March 2024 for currencies official sources don't cover."
        ),
        schedule="Once a day. History available per date since 2024-03-02.",
        max_age_days=3,
        history_from=date(2024, 3, 2),
    )

    max_workers = 8

    def fetch_latest(self) -> list[RateObservation]:
        return self._fetch_tag("latest")

    def fetch_history(self, start: date, end: date) -> list[RateObservation]:
        start = max(start, self.info.history_from or start)
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        out: list[RateObservation] = []

        def one(day: date) -> list[RateObservation]:
            try:
                return self._fetch_tag(day.isoformat())
            except SourceError as exc:
                log.info("currencyapi: no data for %s (%s)", day, exc)
                return []

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            for rows in pool.map(one, days):
                out.extend(rows)
        return out

    def _fetch_tag(self, tag: str) -> list[RateObservation]:
        try:
            response = self._get(PRIMARY.format(tag=tag))
        except SourceError:
            response = self._get(FALLBACK.format(tag=tag))
        return self.parse(response.content)

    def parse(self, payload: bytes) -> list[RateObservation]:
        try:
            data = json.loads(payload, parse_float=Decimal, parse_int=Decimal)
            rate_date = date.fromisoformat(data["date"])
            rates = data["eur"]
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceError(f"Currency API response is malformed: {exc}") from exc
        return self._observations(rate_date, rates.items())
