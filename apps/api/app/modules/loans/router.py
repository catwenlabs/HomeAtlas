"""Loan endpoints (asset-design section 6.4)."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.pagination import PaginationDep, page_payload
from app.core.responses import success_response
from app.modules.households.dependencies import CurrentHousehold
from app.modules.loans import service
from app.modules.loans.models import Loan
from app.modules.loans.schemas import LoanCreate, LoanRead, LoanSettle, LoanUpdate

router = APIRouter(prefix="/loans", tags=["loans"])

SessionDep = Annotated[AsyncSession, Depends(get_db)]


def _loan(loan: Loan) -> dict[str, Any]:
    data = LoanRead.model_validate(loan).model_dump(mode="json")
    data["daily_interest"] = str(service.daily_interest(loan))
    return data


@router.get("")
async def list_loans(
    session: SessionDep,
    household: CurrentHousehold,
    pagination: PaginationDep,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    loans, total = await service.list_loans(session, household, pagination, status=status_filter)
    return success_response(page_payload([_loan(loan) for loan in loans], total, pagination))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_loan(
    session: SessionDep,
    household: CurrentHousehold,
    payload: LoanCreate,
) -> dict[str, Any]:
    loan = await service.create_loan(session, household, payload)
    return success_response(_loan(loan))


@router.get("/{loan_id}")
async def get_loan(
    session: SessionDep,
    household: CurrentHousehold,
    loan_id: uuid.UUID,
) -> dict[str, Any]:
    loan = await service.get_loan(session, household.id, loan_id)
    return success_response(_loan(loan))


@router.put("/{loan_id}")
async def update_loan(
    session: SessionDep,
    household: CurrentHousehold,
    loan_id: uuid.UUID,
    payload: LoanUpdate,
) -> dict[str, Any]:
    loan = await service.update_loan(session, household, loan_id, payload)
    return success_response(_loan(loan))


@router.delete("/{loan_id}")
async def delete_loan(
    session: SessionDep,
    household: CurrentHousehold,
    loan_id: uuid.UUID,
) -> dict[str, Any]:
    await service.delete_loan(session, household, loan_id)
    return success_response(message="Loan deleted")


@router.post("/{loan_id}/settle")
async def settle_loan(
    session: SessionDep,
    household: CurrentHousehold,
    loan_id: uuid.UUID,
    payload: LoanSettle,
) -> dict[str, Any]:
    loan = await service.settle_loan(session, household, loan_id, payload)
    return success_response(_loan(loan))
