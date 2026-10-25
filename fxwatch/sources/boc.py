"""Bank of Canada daily exchange rates via the Valet API (official)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from fxwatch.domain.models import RateObservation, Tier
from fxwatch.sources.base import Source, SourceError, SourceInfo, to_decimal

GROUP_URL = "https://www.bankofcanada.ca/valet/observations/group/FX_RATES_DAILY/json"

# Valet publishes some series (e.g. IDR, VND) with as few as two significant digits.
# Inverting those introduces ~1% error, which is worse than not having the rate at all.
MIN_SIGNIFICANT_DIGITS = 3


def _significant_digits(value: Decimal) -> int:
    return len(value.normalize().as_tuple().digits)


class BankOfCanadaSource(Source):
    info = SourceInfo(
        id="boc",
        name="Bank of Canada",
        tier=Tier.OFFICIAL,
        base="CAD",
        priority=20,
        homepage="https://www.bankofcanada.ca/rates/exchange/daily-exchange-rates/",
        attribution="Source: Bank of Canada, daily exchange rates (Valet API).",
        description=(
            "Official daily average indicative rates for about 25 currencies, expressed in "
            "Canadian dollars. Used both as a source and to cross-check the ECB."
        ),
        schedule="Business days by 16:30 Eastern Time.",
        max_age_days=5,
        history_from=date(2017, 1, 3),
    )

    def fetch_latest(self) -> list[RateObservation]:
        return self.parse(self._get(GROUP_URL, recent="5").content)

    def fetch_history(self, start: date, end: date) -> list[RateObservation]:
        start = max(start, self.info.history_from or start)
        response = self._get(GROUP_URL, start_date=start.isoformat(), end_date=end.isoformat())
        return self.parse(response.content)

    def parse(self, payload: bytes) -> list[RateObservation]:
        try:
            data = json.loads(payload)
            observations = data["observations"]
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceError(f"Bank of Canada response is malformed: {exc}") from exc

        out: list[RateObservation] = []
        for obs in observations:
            rate_date = date.fromisoformat(obs["d"])
            values: list[tuple[str, Decimal]] = []
            for series, cell in obs.items():
                if not (series.startswith("FX") and series.endswith("CAD") and len(series) == 8):
                    continue
                cad_per_unit = to_decimal(cell.get("v") if isinstance(cell, dict) else None)
                if cad_per_unit is None or cad_per_unit <= 0:
                    continue
                if _significant_digits(cad_per_unit) < MIN_SIGNIFICANT_DIGITS:
                    continue
                values.append((series[2:5], Decimal(1) / cad_per_unit))
            if values:
                out.extend(self._observations(rate_date, values))
        if not out:
            raise SourceError("Bank of Canada response contained no usable rates")
        return out
