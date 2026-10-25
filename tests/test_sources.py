from __future__ import annotations

import io
import zipfile
from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from fxwatch.sources.base import SourceError, get_with_retry
from fxwatch.sources.boc import BankOfCanadaSource
from fxwatch.sources.currencyapi import CurrencyApiSource
from fxwatch.sources.ecb import EcbSource
from fxwatch.sources.erapi import ExchangeRateApiSource
from tests.conftest import fixture_bytes


@pytest.fixture
def client():
    with httpx.Client() as c:
        yield c


def by_code(rows):
    return {r.currency: r for r in rows}


def test_ecb_daily_xml(client):
    rows = by_code(EcbSource(client).parse_xml(fixture_bytes("ecb_daily.xml")))
    assert rows["EUR"].value == 1
    assert rows["USD"].value == Decimal("1.1193")
    assert rows["USD"].rate_date == date(2026, 10, 23)
    assert {r.source_id for r in rows.values()} == {"ecb"}
    assert len(rows) >= 25


def test_ecb_history_zip(client):
    csv = "Date,USD,ZAR,XYZ,\n2026-10-23,1.1193,18.5777,N/A,\n2026-10-22,1.1100,N/A,1,\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("eurofxref-hist.csv", csv)
    rows = EcbSource(client).parse_history_zip(buf.getvalue())
    pairs = {(r.rate_date.isoformat(), r.currency) for r in rows}
    assert ("2026-10-23", "ZAR") in pairs
    assert ("2026-10-22", "ZAR") not in pairs  # N/A skipped
    assert not any(r.currency == "XYZ" for r in rows)  # unsupported code dropped


def test_ecb_rejects_garbage(client):
    with pytest.raises(SourceError):
        EcbSource(client).parse_xml(b"<html>maintenance</html>")


def test_boc_inverts_and_drops_imprecise_series(client):
    rows = by_code(BankOfCanadaSource(client).parse(fixture_bytes("boc_recent.json")))
    assert rows["CAD"].value == 1
    # FXUSDCAD = 1.3993 CAD per USD → 0.71464... USD per CAD
    assert abs(rows["USD"].value - Decimal(1) / Decimal("1.3993")) < Decimal("1e-12")
    assert "IDR" not in rows  # published as 0.000078 (2 significant digits)


def test_erapi_parses_exact_decimals(client):
    rows = by_code(ExchangeRateApiSource(client).parse(fixture_bytes("erapi_latest.json")))
    assert rows["USD"].value == 1
    assert rows["GHS"].value > 0
    assert isinstance(rows["AED"].value, Decimal)
    assert rows["AED"].value == Decimal("3.6725")
    assert "CNH" not in rows and "FOK" not in rows  # not in our ISO list


def test_erapi_error_payload(client):
    with pytest.raises(SourceError, match="unsupported-code"):
        ExchangeRateApiSource(client).parse(b'{"result":"error","error-type":"unsupported-code"}')


def test_currencyapi_filters_crypto_and_retired_codes(client):
    rows = by_code(CurrencyApiSource(client).parse(fixture_bytes("currencyapi_eur.json")))
    assert {"EUR", "USD", "ZAR", "GHS", "GBP", "NGN"} <= set(rows)
    assert not {"BTC", "ETH", "ATS", "1INCH"} & set(rows)


@respx.mock
def test_retry_on_server_error_then_success(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    route = respx.get("https://example.test/x").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, text="ok")]
    )
    with httpx.Client() as c:
        assert get_with_retry(c, "https://example.test/x").text == "ok"
    assert route.call_count == 2


@respx.mock
def test_no_retry_on_404(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    route = respx.get("https://example.test/missing").mock(return_value=httpx.Response(404))
    with httpx.Client() as c, pytest.raises(SourceError):
        get_with_retry(c, "https://example.test/missing")
    assert route.call_count == 1
