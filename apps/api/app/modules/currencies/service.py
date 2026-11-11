"""Currency queries and validation."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.core.pagination import Pagination, resolve_sort
from app.modules.currencies.models import Currency
from app.modules.currencies.schemas import CurrencyRead

_SORTABLE = {
    "code": Currency.code,
    "name": Currency.name,
    "decimal_places": Currency.decimal_places,
    "is_active": Currency.is_active,
}


async def list_currencies(
    session: AsyncSession,
    pagination: Pagination,
    *,
    is_active: bool | None = None,
) -> tuple[list[Currency], int]:
    filters = []
    if is_active is not None:
        filters.append(Currency.is_active == is_active)
    total = await session.scalar(select(func.count()).select_from(Currency).where(*filters))
    column, descending = resolve_sort(pagination.sort_by, pagination.sort_order, _SORTABLE, "code")
    stmt = (
        select(Currency)
        .where(*filters)
        .order_by(column.desc() if descending else column.asc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    currencies = list((await session.scalars(stmt)).all())
    return currencies, int(total or 0)


async def get_currency(
    session: AsyncSession,
    code: str,
    *,
    require_active: bool = True,
) -> Currency:
    currency = await session.get(Currency, code.upper())
    if currency is None:
        raise NotFoundError("Currency not found", error_code="CURRENCY_NOT_FOUND")
    if require_active and not currency.is_active:
        raise AppError(
            f"Currency {currency.code} is inactive",
            status_code=400,
            error_code="CURRENCY_INACTIVE",
        )
    return currency


async def ensure_currency(session: AsyncSession, code: str) -> CurrencyRead:
    currency = await get_currency(session, code)
    return CurrencyRead.model_validate(currency)
