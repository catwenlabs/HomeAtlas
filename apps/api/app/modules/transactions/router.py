"""Transaction endpoints (spec section 6.5)."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.enums import TransactionStatus, TransactionType
from app.core.pagination import PaginationDep, page_payload
from app.core.responses import success_response
from app.modules.households.dependencies import CurrentHousehold
from app.modules.transactions import service
from app.modules.transactions.models import Transaction
from app.modules.transactions.schemas import (
    TransactionCreate,
    TransactionReverse,
    TransactionUpdate,
)

router = APIRouter(prefix="/transactions", tags=["transactions"])

SessionDep = Annotated[AsyncSession, Depends(get_db)]


def _payload(transaction: Transaction) -> dict[str, Any]:
    return service.transaction_response(transaction)


@router.get("")
async def list_transactions(
    session: SessionDep,
    household: CurrentHousehold,
    pagination: PaginationDep,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    account_id: Annotated[UUID | None, Query()] = None,
    category_id: Annotated[UUID | None, Query()] = None,
    transaction_type: Annotated[TransactionType | None, Query()] = None,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    min_amount: Annotated[Decimal | None, Query()] = None,
    max_amount: Annotated[Decimal | None, Query()] = None,
    keyword: Annotated[str | None, Query(max_length=200)] = None,
    status_filter: Annotated[TransactionStatus | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    transactions, total = await service.list_transactions(
        session,
        household,
        pagination,
        start_date=start_date,
        end_date=end_date,
        account_id=account_id,
        category_id=category_id,
        transaction_type=transaction_type,
        currency=currency,
        min_amount=min_amount,
        max_amount=max_amount,
        keyword=keyword,
        status=status_filter,
    )
    return success_response(
        page_payload([_payload(item) for item in transactions], total, pagination)
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_transaction(
    session: SessionDep, household: CurrentHousehold, payload: TransactionCreate
) -> dict[str, Any]:
    transaction = await service.create_transaction(session, household, payload)
    return success_response(_payload(transaction))


@router.get("/{transaction_id}")
async def get_transaction(
    session: SessionDep, household: CurrentHousehold, transaction_id: UUID
) -> dict[str, Any]:
    transaction = await service.get_transaction(session, household.id, transaction_id)
    return success_response(_payload(transaction))


@router.put("/{transaction_id}")
async def update_transaction(
    session: SessionDep,
    household: CurrentHousehold,
    transaction_id: UUID,
    payload: TransactionUpdate,
) -> dict[str, Any]:
    transaction = await service.update_transaction(session, household, transaction_id, payload)
    return success_response(_payload(transaction))


@router.delete("/{transaction_id}")
async def delete_transaction(
    session: SessionDep, household: CurrentHousehold, transaction_id: UUID
) -> dict[str, Any]:
    await service.delete_transaction(session, household, transaction_id)
    return success_response(None, "Transaction deleted")


@router.post("/{transaction_id}/reverse", status_code=status.HTTP_201_CREATED)
async def reverse_transaction(
    session: SessionDep,
    household: CurrentHousehold,
    transaction_id: UUID,
    payload: Annotated[TransactionReverse | None, Body()] = None,
) -> dict[str, Any]:
    reversal = await service.reverse_transaction(
        session, household, transaction_id, payload or TransactionReverse()
    )
    return success_response(_payload(reversal))
