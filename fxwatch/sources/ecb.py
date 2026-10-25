"""European Central Bank euro foreign exchange reference rates (official)."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, timedelta
from xml.etree import ElementTree

from fxwatch.domain.models import RateObservation, Tier
from fxwatch.sources.base import Source, SourceError, SourceInfo, to_decimal

BASE_URL = "https://www.ecb.europa.eu/stats/eurofxref"


class EcbSource(Source):
    info = SourceInfo(
        id="ecb",
        name="European Central Bank",
        tier=Tier.OFFICIAL,
        base="EUR",
        priority=10,
        homepage="https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html",
        attribution="Source: European Central Bank, euro foreign exchange reference rates.",
        description=(
            "Official euro reference rates for about 30 currencies, set daily from a regular "
            "concertation between central banks. Published for information purposes only."
        ),
        schedule="Business days around 16:00 CET (no rates on TARGET holidays).",
        max_age_days=5,
        history_from=date(1999, 1, 4),
    )

    def fetch_latest(self) -> list[RateObservation]:
        return self.parse_xml(self._get(f"{BASE_URL}/eurofxref-daily.xml").content)

    def fetch_history(self, start: date, end: date) -> list[RateObservation]:
        if start >= date.today() - timedelta(days=89):
            rows = self.parse_xml(self._get(f"{BASE_URL}/eurofxref-hist-90d.xml").content)
        else:
            rows = self.parse_history_zip(self._get(f"{BASE_URL}/eurofxref-hist.zip").content)
        return [r for r in rows if start <= r.rate_date <= end]

    def parse_xml(self, payload: bytes) -> list[RateObservation]:
        try:
            root = ElementTree.fromstring(payload)
        except ElementTree.ParseError as exc:
            raise SourceError(f"ECB XML could not be parsed: {exc}") from exc
        out: list[RateObservation] = []
        for day in root.iter():
            if not day.tag.endswith("Cube") or "time" not in day.attrib:
                continue
            rate_date = date.fromisoformat(day.attrib["time"])
            values = []
            for cube in day:
                value = to_decimal(cube.attrib.get("rate"))
                if value is not None:
                    values.append((cube.attrib.get("currency", ""), value))
            out.extend(self._observations(rate_date, values))
        if not out:
            raise SourceError("ECB response contained no rates")
        return out

    def parse_history_zip(self, payload: bytes) -> list[RateObservation]:
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                text = archive.read(archive.namelist()[0]).decode("utf-8")
        except (zipfile.BadZipFile, IndexError) as exc:
            raise SourceError(f"ECB history archive is invalid: {exc}") from exc
        out: list[RateObservation] = []
        for row in csv.DictReader(io.StringIO(text)):
            raw_date = (row.pop("Date", "") or "").strip()
            if not raw_date:
                continue
            values = []
            for code, raw in row.items():
                value = to_decimal(raw) if code else None
                if value is not None:
                    values.append((code.strip(), value))
            out.extend(self._observations(date.fromisoformat(raw_date), values))
        return out
