"""finance.exchange_rates use cases (asset-design sections 4.1, 5.3).

Rates are household bookkeeping quotes. Lookup rule: latest direct pair with
rate_date <= as-of, else the inverse 1/rate; no triangulation.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.core.money import quantize_amount
from app.core.pagination import Pagination, resolve_sort
from app.modules.audit.service import write_audit
from app.modules.currencies.service import get_currency
from app.modules.exchange_rates.models import ExchangeRate
from app.modules.exchange_rates.schemas import ExchangeRateCreate

EXCHANGE_RATE_PLACES = 12

_SORTABLE = {
    "rate_date": ExchangeRate.rate_date,
    "created_at": ExchangeRate.created_at,
    "rate": ExchangeRate.rate,
}


def _audit_data(rate: ExchangeRate) -> dict[str, Any]:
    return {
        "base_currency": str(rate.base_currency).strip(),
        "quote_currency": str(rate.quote_currency).strip(),
        "rate": str(rate.rate),
        "rate_date": rate.rate_date.isoformat(),
        "source": rate.source,
    }


async def _validate_pair(base: str, quote: str) -> None:
    if base == quote:
        raise AppError(
            "base_currency and quote_currency must differ",
            status_code=422,
            error_code="EXCHANGE_RATE_VALUE_INVALID",
        )


async def create_exchange_rate(
    session: AsyncSession,
    household_id: UUID,
    payload: ExchangeRateCreate,
) -> ExchangeRate:
    await _validate_pair(payload.base_currency, payload.quote_currency)
    await get_currency(session, payload.base_currency)
    await get_currency(session, payload.quote_currency)
    if payload.rate <= 0:
        raise AppError(
            "rate must be positive",
            status_code=422,
            error_code="EXCHANGE_RATE_VALUE_INVALID",
        )

    duplicate = await session.scalar(
        select(func.count())
        .select_from(ExchangeRate)
        .where(
            ExchangeRate.household_id == household_id,
            ExchangeRate.base_currency == payload.base_currency,
            ExchangeRate.quote_currency == payload.quote_currency,
            ExchangeRate.rate_date == payload.rate_date,
        )
    )
    if duplicate:
        raise AppError(
            f"Rate for {payload.base_currency}/{payload.quote_currency} on "
            f"{payload.rate_date.isoformat()} already exists",
            status_code=409,
            error_code="EXCHANGE_RATE_DUPLICATE",
        )

    rate = ExchangeRate(
        household_id=household_id,
        base_currency=payload.base_currency,
        quote_currency=payload.quote_currency,
        rate=payload.rate,
        rate_date=payload.rate_date,
    )
    session.add(rate)
    await session.flush()
    write_audit(
        session,
        household_id=household_id,
        action="exchange_rate.create",
        entity_type="exchange_rate",
        entity_id=rate.id,
        after=_audit_data(rate),
    )
    await session.commit()
    await session.refresh(rate)
    return rate


async def list_exchange_rates(
    session: AsyncSession,
    household_id: UUID,
    pagination: Pagination,
    *,
    base: str | None = None,
    quote: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[ExchangeRate], int]:
    filters = [ExchangeRate.household_id == household_id]
    if base is not None:
        filters.append(ExchangeRate.base_currency == base.upper())
    if quote is not None:
        filters.append(ExchangeRate.quote_currency == quote.upper())
    if date_from is not None:
        filters.append(ExchangeRate.rate_date >= date_from)
    if date_to is not None:
        filters.append(ExchangeRate.rate_date <= date_to)
    total = await session.scalar(select(func.count()).select_from(ExchangeRate).where(*filters))
    column, descending = resolve_sort(
        pagination.sort_by, pagination.sort_order, _SORTABLE, "rate_date"
    )
    stmt = (
        select(ExchangeRate)
        .where(*filters)
        .order_by(column.desc() if descending else column.asc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return list((await session.scalars(stmt)).all()), int(total or 0)


async def _stored_pair(
    session: AsyncSession,
    household_id: UUID,
    base: str,
    quote: str,
    as_of: date,
) -> ExchangeRate | None:
    return await session.scalar(
        select(ExchangeRate)
        .where(
            ExchangeRate.household_id == household_id,
            ExchangeRate.base_currency == base,
            ExchangeRate.quote_currency == quote,
            ExchangeRate.rate_date <= as_of,
        )
        .order_by(ExchangeRate.rate_date.desc(), ExchangeRate.created_at.desc())
        .limit(1)
    )


async def resolve_rate(
    session: AsyncSession,
    household_id: UUID,
    base: str,
    quote: str,
    as_of: date,
) -> Decimal | None:
    """Rate so that 1 base = <rate> quote, or None when neither side exists."""
    if base == quote:
        return Decimal("1")
    direct = await _stored_pair(session, household_id, base, quote, as_of)
    if direct is not None:
        return quantize_amount(direct.rate, EXCHANGE_RATE_PLACES)
    inverse = await _stored_pair(session, household_id, quote, base, as_of)
    if inverse is not None:
        return quantize_amount(Decimal(1) / inverse.rate, EXCHANGE_RATE_PLACES)
    return None


async def resolve_rates_to_base(
    session: AsyncSession,
    household_id: UUID,
    base: str,
    currencies: set[str],
    as_of: date,
) -> dict[str, Decimal]:
    """Resolve every currency to the base; raise with the full gap list."""
    missing: list[str] = []
    rates: dict[str, Decimal] = {}
    for currency in sorted(currencies):
        if currency == base:
            continue
        rate = await resolve_rate(session, household_id, currency, base, as_of)
        if rate is None:
            missing.append(f"{currency}/{base}")
        else:
            rates[currency] = rate
    if missing:
        raise AppError(
            f"Missing exchange rates for: {', '.join(missing)}",
            status_code=400,
            error_code="EXCHANGE_RATE_NOT_FOUND",
            details={"missing": missing},
        )
    return rates


async def latest_rate(
    session: AsyncSession,
    household_id: UUID,
    base: str,
    quote: str,
    as_of: date | None = None,
) -> dict[str, Any]:
    base = base.upper()
    quote = quote.upper()
    await _validate_pair(base, quote)
    as_of = as_of or date.today()
    direct = await _stored_pair(session, household_id, base, quote, as_of)
    if direct is not None:
        return {
            "base_currency": base,
            "quote_currency": quote,
            "rate": str(quantize_amount(direct.rate, EXCHANGE_RATE_PLACES)),
            "rate_date": direct.rate_date,
            "direction": "direct",
            "source_pair": f"{base}/{quote}",
        }
    inverse = await _stored_pair(session, household_id, quote, base, as_of)
    if inverse is not None:
        return {
            "base_currency": base,
            "quote_currency": quote,
            "rate": str(quantize_amount(Decimal(1) / inverse.rate, EXCHANGE_RATE_PLACES)),
            "rate_date": inverse.rate_date,
            "direction": "inverse",
            "source_pair": f"{quote}/{base}",
        }
    raise NotFoundError(
        f"No rate found for {base}/{quote} on or before {as_of.isoformat()}",
        error_code="EXCHANGE_RATE_NOT_FOUND",
    )


async def delete_exchange_rate(
    session: AsyncSession,
    household_id: UUID,
    rate_id: UUID,
) -> None:
    rate = await session.scalar(
        select(ExchangeRate).where(
            ExchangeRate.id == rate_id,
            ExchangeRate.household_id == household_id,
        )
    )
    if rate is None:
        raise NotFoundError("Exchange rate not found", error_code="EXCHANGE_RATE_NOT_FOUND")
    before = _audit_data(rate)
    await session.delete(rate)
    write_audit(
        session,
        household_id=household_id,
        action="exchange_rate.delete",
        entity_type="exchange_rate",
        entity_id=rate.id,
        before=before,
    )
    await session.commit()
