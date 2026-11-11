"""Decimal helpers. Money is never represented as float (spec section 1)."""

from decimal import ROUND_HALF_EVEN, Decimal

MONEY_PLACES = 8


def quantize_amount(amount: Decimal, decimal_places: int) -> Decimal:
    """Round half-even to the currency's decimal places."""
    return amount.quantize(Decimal(1).scaleb(-decimal_places), rounding=ROUND_HALF_EVEN)


def quantize_money(amount: Decimal) -> Decimal:
    """Round to the NUMERIC(24,8) storage scale."""
    return quantize_amount(amount, MONEY_PLACES)
