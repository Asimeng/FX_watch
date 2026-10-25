"""ExchangeRate-API open access endpoint (credible aggregator, ~160 currencies)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from fxwatch.domain.models import RateObservation, Tier
from fxwatch.sources.base import Source, SourceError, SourceInfo

LATEST_URL = "https://open.er-api.com/v6/latest/USD"


class ExchangeRateApiSource(Source):
    info = SourceInfo(
        id="erapi",
        name="ExchangeRate-API",
        tier=Tier.AGGREGATOR,
        base="USD",
        priority=30,
        homepage="https://www.exchangerate-api.com",
        attribution="Rates by Exchange Rate API (https://www.exchangerate-api.com).",
        description=(
            "Commercial aggregator of central-bank and market data. Covers almost every "
            "currency in circulation, so it fills the gaps left by official sources."
        ),
        schedule="Once a day (~00:00 UTC). Latest rates only, no history.",
        max_age_days=3,
        history_from=None,
    )

    def fetch_latest(self) -> list[RateObservation]:
        return self.parse(self._get(LATEST_URL).content)

    def parse(self, payload: bytes) -> list[RateObservation]:
        try:
            data = json.loads(payload, parse_float=Decimal, parse_int=Decimal)
        except ValueError as exc:
            raise SourceError(f"ExchangeRate-API response is not JSON: {exc}") from exc
        if data.get("result") != "success":
            raise SourceError(f"ExchangeRate-API error: {data.get('error-type', 'unknown')}")
        if data.get("base_code") != self.info.base:
            raise SourceError(f"Unexpected base currency {data.get('base_code')!r}")
        updated = datetime.fromtimestamp(int(data["time_last_update_unix"]), UTC).date()
        return self._observations(updated, data["rates"].items())
