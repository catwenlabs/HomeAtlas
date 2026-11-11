"""Income/expense statistics endpoints (spec section 6.7)."""

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.enums import CategoryType
from app.core.responses import success_response
from app.modules.households.dependencies import CurrentHousehold
from app.modules.statistics import service

router = APIRouter(prefix="/statistics", tags=["statistics"])

SessionDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("/income-expense")
async def income_expense(
    session: SessionDep,
    household: CurrentHousehold,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    data = await service.income_expense(session, household, start_date, end_date)
    return success_response(data)


@router.get("/overview")
async def overview(
    session: SessionDep,
    household: CurrentHousehold,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    data = await service.overview(session, household, start_date, end_date)
    return success_response(data)


@router.get("/account-balances")
async def account_balances(
    session: SessionDep,
    household: CurrentHousehold,
) -> dict[str, Any]:
    data = await service.account_balances(session, household)
    return success_response(data)


@router.get("/category")
async def category_statistics(
    session: SessionDep,
    household: CurrentHousehold,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    transaction_type: Annotated[CategoryType | None, Query()] = None,
) -> dict[str, Any]:
    data = await service.category_statistics(
        session, household, start_date, end_date, transaction_type
    )
    return success_response(data)


@router.get("/monthly")
async def monthly_statistics(
    session: SessionDep,
    household: CurrentHousehold,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    granularity: Annotated[Literal["month", "year"], Query()] = "month",
) -> dict[str, Any]:
    data = await service.monthly_statistics(session, household, start_date, end_date, granularity)
    return success_response(data)


@router.get("/cashflow")
async def cashflow(
    session: SessionDep,
    household: CurrentHousehold,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    granularity: Annotated[Literal["day", "month", "year"], Query()] = "day",
) -> dict[str, Any]:
    data = await service.cashflow(session, household, start_date, end_date, granularity)
    return success_response(data)
