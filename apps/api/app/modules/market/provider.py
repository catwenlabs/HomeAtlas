"""Quote provider abstraction (2C-2).

Providers turn (market, symbol) references into live quotes. The default
Tencent provider needs no API key and covers SH/SZ/HK/US. Tests inject the
FakeProvider so CI never touches the network.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

import httpx

from app.core.enums import Market

MARKET_CURRENCY = {
    Market.SH.value: "CNY",
    Market.SZ.value: "CNY",
    Market.HK.value: "HKD",
    Market.US.value: "USD",
}

_TENCENT_PREFIX = {
    Market.SH.value: "sh",
    Market.SZ.value: "sz",
    Market.HK.value: "hk",
    Market.US.value: "us",
}


@dataclass(frozen=True)
class Quote:
    market: str
    symbol: str
    name: str
    price: Decimal
    currency: str
    quoted_at: datetime


def quote_key(market: str, symbol: str) -> str:
    return f"{market}:{symbol}"


class QuoteProvider(Protocol):
    async def fetch(self, refs: list[tuple[str, str]]) -> dict[str, Quote]:
        """Return quotes keyed by 'MARKET:SYMBOL'; missing keys are errors."""
        ...


class FakeQuoteProvider:
    """Deterministic offline provider: price derived from the symbol hash."""

    async def fetch(self, refs: list[tuple[str, str]]) -> dict[str, Quote]:
        quotes: dict[str, Quote] = {}
        for market, symbol in refs:
            digest = hashlib.sha256(f"{market}:{symbol}".encode()).hexdigest()
            price = Decimal(10 + int(digest[:8], 16) % 10_000) / Decimal("10")
            quotes[quote_key(market, symbol)] = Quote(
                market=market,
                symbol=symbol,
                name=fake_name(symbol),
                price=price,
                currency=MARKET_CURRENCY[market],
                quoted_at=datetime.now(UTC),
            )
        return quotes


def fake_name(symbol: str) -> str:
    return f"FAKE {symbol}"


class TencentQuoteProvider:
    """qt.gtimg.cn quotes: GBK text, '~'-separated fields, no API key."""

    BASE_URL = "https://qt.gtimg.cn/q="

    async def fetch(self, refs: list[tuple[str, str]]) -> dict[str, Quote]:
        from app.core.config import get_settings

        settings = get_settings()
        codes = [f"{_TENCENT_PREFIX[market]}{symbol}" for market, symbol in refs]
        quoted_at = datetime.now(UTC)
        async with httpx.AsyncClient(
            timeout=settings.quote_timeout_seconds,
            proxy=settings.quote_proxy_url,
            headers={"User-Agent": "HomeAtlas/2C-2"},
        ) as client:
            response = await client.get(self.BASE_URL + ",".join(codes))
            response.raise_for_status()
        text = response.content.decode("gbk", errors="replace")
        quotes: dict[str, Quote] = {}
        for market, symbol in refs:
            marker = f'v_{_TENCENT_PREFIX[market]}{symbol}="'
            start = text.find(marker)
            if start < 0:
                continue
            fields = text[start + len(marker) :].split('"')[0].split("~")
            if len(fields) < 4:
                continue
            try:
                price = Decimal(fields[3])
            except Exception:  # noqa: BLE001, S112 - provider payload is untrusted
                continue
            if price <= 0:
                continue
            quotes[quote_key(market, symbol)] = Quote(
                market=market,
                symbol=symbol,
                name=fields[1],
                price=price,
                currency=MARKET_CURRENCY[market],
                quoted_at=quoted_at,
            )
        return quotes
