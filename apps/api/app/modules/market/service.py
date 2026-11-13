"""Quote fetching with a short in-memory TTL cache (2C-2)."""

import time
from decimal import Decimal
from typing import Any

from app.core.config import get_settings
from app.core.enums import Market
from app.core.exceptions import AppError
from app.core.money import quantize_money
from app.modules.market.provider import (
    MARKET_CURRENCY,
    FakeQuoteProvider,
    Quote,
    TencentQuoteProvider,
    quote_key,
)

_PROVIDERS: dict[str, type] = {
    "tencent": TencentQuoteProvider,
    "fake": FakeQuoteProvider,
}

_cache: dict[str, tuple[Quote, float]] = {}

_VALID_MARKETS = {market.value for market in Market}


def _provider() -> Any:
    name = get_settings().quote_provider
    provider_cls = _PROVIDERS.get(name)
    if provider_cls is None:
        raise AppError(
            f"Unknown quote provider '{name}'",
            status_code=500,
            error_code="QUOTE_PROVIDER_ERROR",
        )
    return provider_cls()


def clear_cache() -> None:
    """Test hook."""
    _cache.clear()


def parse_symbols(raw: str, *, limit: int = 50) -> list[tuple[str, str]]:
    """Parse 'SH:600519,HK:00700' into (market, symbol) refs."""
    refs: list[tuple[str, str]] = []
    for chunk in raw.split(","):
        part = chunk.strip()
        if not part:
            continue
        market, _, symbol = part.partition(":")
        market = market.strip().upper()
        symbol = symbol.strip().upper()
        if not symbol or market not in _VALID_MARKETS:
            raise AppError(
                f"Invalid symbol reference '{part}' (expected MARKET:SYMBOL, "
                "markets: SH, SZ, HK, US)",
                status_code=422,
                error_code="VALIDATION_ERROR",
            )
        refs.append((market, symbol))
    if not refs:
        raise AppError(
            "At least one symbol is required",
            status_code=422,
            error_code="VALIDATION_ERROR",
        )
    if len(refs) > limit:
        raise AppError(
            f"At most {limit} symbols per request",
            status_code=422,
            error_code="VALIDATION_ERROR",
        )
    return refs


async def fetch_quotes(refs: list[tuple[str, str]]) -> dict[str, Quote]:
    """Return quotes for all refs, from cache when fresh, else the provider."""
    ttl = get_settings().quote_cache_ttl_seconds
    now = time.monotonic()
    missing: list[tuple[str, str]] = []
    quotes: dict[str, Quote] = {}
    for ref in refs:
        key = quote_key(*ref)
        cached = _cache.get(key)
        if cached is not None and cached[1] > now:
            quotes[key] = cached[0]
        else:
            missing.append(ref)

    if missing:
        fetched = await _provider().fetch(missing)
        failed = [quote_key(*ref) for ref in missing if quote_key(*ref) not in fetched]
        if failed:
            raise AppError(
                f"Quote provider returned no usable price for: {', '.join(failed)}",
                status_code=502,
                error_code="QUOTE_PROVIDER_ERROR",
                details={"symbols": failed},
            )
        expires = now + ttl
        for key, quote in fetched.items():
            _cache[key] = (quote, expires)
            quotes[key] = quote
    return quotes


def quote_response(quote: Quote) -> dict[str, Any]:
    return {
        "market": quote.market,
        "symbol": quote.symbol,
        "name": quote.name,
        "price": str(quote.price.normalize()),
        "currency": quote.currency,
        "quoted_at": quote.quoted_at,
    }


def validate_quote_currency(quote: Quote) -> None:
    expected = MARKET_CURRENCY.get(quote.market)
    if expected is not None and quote.currency != expected:
        raise AppError(
            f"Provider returned {quote.currency} for a {quote.market} symbol (expected {expected})",
            status_code=502,
            error_code="QUOTE_PROVIDER_ERROR",
        )


def money(value: Decimal) -> Decimal:
    return quantize_money(value)
