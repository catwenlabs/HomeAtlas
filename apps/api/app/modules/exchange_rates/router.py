"""Exchange rate endpoints (asset-design section 6.1)."""

from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.pagination import PaginationDep, page_payload
from app.core.responses import success_response
from app.modules.exchange_rates import service
from app.modules.exchange_rates.schemas import (
    ExchangeRateCreate,
    ExchangeRateRead,
)
from app.modules.households.dependencies import CurrentHousehold

router = APIRouter(prefix="/exchange-rates", tags=["exchange-rates"])

SessionDep = Annotated[AsyncSession, Depends(get_db)]


def _rate(rate: Any) -> dict[str, Any]:
    return ExchangeRateRead.model_validate(rate).model_dump(mode="json")


@router.get("")
async def list_exchange_rates(
    session: SessionDep,
    household: CurrentHousehold,
    pagination: PaginationDep,
    base: Annotated[str | None, Query(pattern=r"^[A-Za-z]{3}$")] = None,
    quote: Annotated[str | None, Query(pattern=r"^[A-Za-z]{3}$")] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    rates, total = await service.list_exchange_rates(
        session,
        household.id,
        pagination,
        base=base,
        quote=quote,
        date_from=date_from,
        date_to=date_to,
    )
    return success_response(page_payload([_rate(rate) for rate in rates], total, pagination))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_exchange_rate(
    session: SessionDep,
    household: CurrentHousehold,
    payload: ExchangeRateCreate,
) -> dict[str, Any]:
    rate = await service.create_exchange_rate(session, household.id, payload)
    return success_response(_rate(rate))


@router.get("/latest")
async def latest_exchange_rate(
    session: SessionDep,
    household: CurrentHousehold,
    base: Annotated[str, Query(pattern=r"^[A-Za-z]{3}$")],
    quote: Annotated[str, Query(pattern=r"^[A-Za-z]{3}$")],
    date: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    latest = await service.latest_rate(session, household.id, base, quote, date)
    return success_response(latest)


@router.delete("/{rate_id}")
async def delete_exchange_rate(
    session: SessionDep,
    household: CurrentHousehold,
    rate_id: UUID,
) -> dict[str, Any]:
    await service.delete_exchange_rate(session, household.id, rate_id)
    return success_response(message="Exchange rate deleted")
