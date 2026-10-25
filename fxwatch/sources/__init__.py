"""Registry of rate sources, ordered by priority (most authoritative first)."""

from __future__ import annotations

from fxwatch.sources.base import Source, SourceError, SourceInfo, build_client
from fxwatch.sources.boc import BankOfCanadaSource
from fxwatch.sources.currencyapi import CurrencyApiSource
from fxwatch.sources.ecb import EcbSource
from fxwatch.sources.erapi import ExchangeRateApiSource

SOURCE_CLASSES: list[type[Source]] = sorted(
    [EcbSource, BankOfCanadaSource, ExchangeRateApiSource, CurrencyApiSource],
    key=lambda cls: cls.info.priority,
)

SOURCE_INFO: dict[str, SourceInfo] = {cls.info.id: cls.info for cls in SOURCE_CLASSES}

__all__ = [
    "SOURCE_CLASSES",
    "SOURCE_INFO",
    "Source",
    "SourceError",
    "SourceInfo",
    "build_client",
]
