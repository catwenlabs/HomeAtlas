"""Account endpoints (spec section 6.2)."""

from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.enums import TransactionStatus, TransactionType
from app.core.pagination import PaginationDep, page_payload
from app.core.responses import success_response
from app.modules.accounts import service
from app.modules.accounts.models import Account, AccountBalance
from app.modules.accounts.schemas import (
    AccountBalanceSnapshotRead,
    AccountCreate,
    AccountRead,
    AccountUpdate,
    OpeningBalanceUpsert,
)
from app.modules.households.dependencies import CurrentHousehold
from app.modules.transactions import service as transaction_service
from app.modules.transactions.schemas import TransactionRead

router = APIRouter(prefix="/accounts", tags=["accounts"])

SessionDep = Annotated[AsyncSession, Depends(get_db)]


def _account(account: Account) -> dict[str, Any]:
    return AccountRead.model_validate(account).model_dump(mode="json")


def _snapshot(snapshot: AccountBalance) -> dict[str, Any]:
    return AccountBalanceSnapshotRead.model_validate(snapshot).model_dump(mode="json")


@router.get("")
async def list_accounts(
    session: SessionDep,
    household: CurrentHousehold,
    pagination: PaginationDep,
    is_active: Annotated[bool | None, Query()] = None,
) -> dict[str, Any]:
    accounts, total = await service.list_accounts(
        session, household.id, pagination, is_active=is_active
    )
    return success_response(
        page_payload([_account(account) for account in accounts], total, pagination)
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_account(
    session: SessionDep, household: CurrentHousehold, payload: AccountCreate
) -> dict[str, Any]:
    account = await service.create_account(session, household.id, payload)
    return success_response(_account(account))


@router.get("/{account_id}")
async def get_account(
    session: SessionDep, household: CurrentHousehold, account_id: UUID
) -> dict[str, Any]:
    account = await service.get_account(session, household.id, account_id)
    return success_response(_account(account))


@router.put("/{account_id}")
async def update_account(
    session: SessionDep,
    household: CurrentHousehold,
    account_id: UUID,
    payload: AccountUpdate,
) -> dict[str, Any]:
    account = await service.update_account(session, household.id, account_id, payload)
    return success_response(_account(account))


@router.delete("/{account_id}")
async def delete_account(
    session: SessionDep, household: CurrentHousehold, account_id: UUID
) -> dict[str, Any]:
    await service.delete_account(session, household.id, account_id)
    return success_response(None, "Account deleted")


@router.put("/{account_id}/opening-balance")
async def set_opening_balance(
    session: SessionDep,
    household: CurrentHousehold,
    account_id: UUID,
    payload: OpeningBalanceUpsert,
) -> dict[str, Any]:
    account = await service.get_account(session, household.id, account_id)
    transaction = await transaction_service.set_opening_balance(
        session,
        account,
        household,
        amount=payload.amount,
        currency_code=payload.currency,
        exchange_rate=payload.exchange_rate,
        exchange_rate_date=payload.exchange_rate_date,
        transaction_date=payload.transaction_date,
        description=payload.description,
    )
    return success_response(transaction_service.opening_balance_response(transaction))


@router.get("/{account_id}/balances")
async def get_account_balances(
    session: SessionDep, household: CurrentHousehold, account_id: UUID
) -> dict[str, Any]:
    balances = await service.get_account_balances(session, household.id, account_id)
    return success_response(balances.model_dump(mode="json"))


@router.get("/{account_id}/transactions")
async def list_account_transactions(
    session: SessionDep,
    household: CurrentHousehold,
    account_id: UUID,
    pagination: PaginationDep,
    start_date: Annotated[datetime | None, Query()] = None,
    end_date: Annotated[datetime | None, Query()] = None,
    transaction_type: Annotated[TransactionType | None, Query()] = None,
    status_filter: Annotated[TransactionStatus | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    transactions, total = await service.list_account_transactions(
        session,
        household.id,
        account_id,
        pagination,
        start_date=start_date,
        end_date=end_date,
        transaction_type=transaction_type,
        status=status_filter,
    )
    items = [
        TransactionRead.model_validate(transaction).model_dump(mode="json")
        for transaction in transactions
    ]
    return success_response(page_payload(items, total, pagination))


@router.get("/{account_id}/balance-history")
async def list_balance_history(
    session: SessionDep,
    household: CurrentHousehold,
    account_id: UUID,
    pagination: PaginationDep,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    snapshots, total = await service.list_balance_history(
        session,
        household.id,
        account_id,
        pagination,
        currency=currency,
        start_date=start_date,
        end_date=end_date,
    )
    return success_response(
        page_payload([_snapshot(snapshot) for snapshot in snapshots], total, pagination)
    )
