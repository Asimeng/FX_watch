"""Cross-rate arithmetic.

Every source publishes "units of currency X per 1 unit of the source's base". The rate for
any pair is then quote/base. Both legs always come from the same source and snapshot.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, getcontext

getcontext().prec = 28


def cross_rate(values: Mapping[str, Decimal], base: str, quote: str) -> Decimal:
    """Units of `quote` per 1 unit of `base`. Raises KeyError if either leg is missing."""
    if base == quote:
        return Decimal(1)
    base_value = values[base]
    quote_value = values[quote]
    if base_value <= 0 or quote_value <= 0:
        raise ValueError(f"Non-positive rate for {base} or {quote}")
    return quote_value / base_value


def pct_difference(a: Decimal, b: Decimal) -> Decimal:
    """Absolute difference between a and b as a percentage of their midpoint."""
    mid = (a + b) / 2
    return abs(a - b) / mid * 100


def format_rate(value: Decimal | float, significant: int = 6) -> str:
    """Human-friendly rate: enough digits to be useful at any magnitude, no sci-notation."""
    v = float(value)
    if v == 0:
        return "0"
    if abs(v) >= 1000:
        return f"{v:,.2f}"
    if abs(v) >= 1:
        return f"{v:,.4f}"
    # small numbers: keep `significant` significant figures
    text = f"{v:.{significant}g}"
    if "e" in text:
        text = f"{v:.12f}".rstrip("0")
    return text
