"""Decimal helpers. Money is never represented as float (spec section 1)."""

from decimal import ROUND_HALF_EVEN, Decimal

MONEY_PLACES = 8


def quantize_amount(amount: Decimal, decimal_places: int) -> Decimal:
    """Round half-even to the currency's decimal places."""
    return amount.quantize(Decimal(1).scaleb(-decimal_places), rounding=ROUND_HALF_EVEN)


def quantize_money(amount: Decimal) -> Decimal:
    """Round to the NUMERIC(24,8) storage scale."""
    return quantize_amount(amount, MONEY_PLACES)


DAYS_PER_YEAR = Decimal("365")


def daily_interest(amount: Decimal, annual_rate: Decimal) -> Decimal:
    """amount x annual_rate / 365 (asset-design 5.4 estimate; no flows).

    Unquantized on purpose: callers either quantize the single result or
    accumulate per currency and quantize the aggregate once.
    """
    return amount * annual_rate / DAYS_PER_YEAR
