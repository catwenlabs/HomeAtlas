"""Built-in currency catalog (moved out of migrations in Phase 2A).

The catalog is static reference data shown in the setup wizard. Only the
currencies the user confirms during first-time setup are written to the database.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.modules.currencies.models import Currency


@dataclass(frozen=True)
class DefaultCurrency:
    code: str
    name: str
    symbol: str
    decimal_places: int


BUILTIN_CURRENCIES: tuple[DefaultCurrency, ...] = (
    DefaultCurrency("CNY", "人民币", "¥", 2),
    DefaultCurrency("USD", "美元", "$", 2),
    DefaultCurrency("HKD", "港币", "HK$", 2),
    DefaultCurrency("EUR", "欧元", "€", 2),
    DefaultCurrency("GBP", "英镑", "£", 2),
    DefaultCurrency("JPY", "日元", "¥", 0),
)

BUILTIN_CURRENCY_CODES: tuple[str, ...] = tuple(item.code for item in BUILTIN_CURRENCIES)


def build_default_currencies(codes: list[str] | None = None) -> list[Currency]:
    selected = set(codes) if codes is not None else set(BUILTIN_CURRENCY_CODES)
    return [
        Currency(
            code=item.code,
            name=item.name,
            symbol=item.symbol,
            decimal_places=item.decimal_places,
            is_active=True,
        )
        for item in BUILTIN_CURRENCIES
        if item.code in selected
    ]


async def seed_currencies(session: AsyncSession, codes: list[str] | None = None) -> None:
    """Insert the confirmed built-in currencies; existing rows are left untouched."""
    selected = [item.upper() for item in (codes or BUILTIN_CURRENCY_CODES)]
    unknown = sorted(set(selected) - set(BUILTIN_CURRENCY_CODES))
    if unknown:
        raise AppError(
            f"Unsupported currency codes: {', '.join(unknown)}",
            status_code=400,
            error_code="CURRENCY_UNSUPPORTED",
        )
    if not selected:
        raise AppError(
            "At least one currency must be selected",
            status_code=400,
            error_code="CURRENCY_REQUIRED",
        )
    existing = set(
        (await session.scalars(select(Currency.code).where(Currency.code.in_(selected)))).all()
    )
    missing = [code for code in selected if code not in existing]
    if missing:
        session.add_all(build_default_currencies(missing))
        await session.flush()
