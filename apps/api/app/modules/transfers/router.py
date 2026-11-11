"""Transfer endpoints (spec section 6.6)."""

from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.enums import TransactionStatus
from app.core.pagination import PaginationDep, page_payload
from app.core.responses import success_response
from app.modules.households.dependencies import CurrentHousehold
from app.modules.transfers import service
from app.modules.transfers.models import Transfer
from app.modules.transfers.schemas import (
    TransferCreate,
    TransferReverse,
    TransferUpdate,
)

router = APIRouter(prefix="/transfers", tags=["transfers"])

SessionDep = Annotated[AsyncSession, Depends(get_db)]


def _payload(transfer: Transfer) -> dict[str, Any]:
    return service.transfer_response(transfer)


@router.get("")
async def list_transfers(
    session: SessionDep,
    household: CurrentHousehold,
    pagination: PaginationDep,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    account_id: Annotated[UUID | None, Query()] = None,
    from_account_id: Annotated[UUID | None, Query()] = None,
    to_account_id: Annotated[UUID | None, Query()] = None,
    from_currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    to_currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    status_filter: Annotated[TransactionStatus | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    transfers, total = await service.list_transfers(
        session,
        household,
        pagination,
        start_date=start_date,
        end_date=end_date,
        account_id=account_id,
        from_account_id=from_account_id,
        to_account_id=to_account_id,
        status=status_filter,
        from_currency=from_currency,
        to_currency=to_currency,
    )
    return success_response(page_payload([_payload(item) for item in transfers], total, pagination))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_transfer(
    session: SessionDep, household: CurrentHousehold, payload: TransferCreate
) -> dict[str, Any]:
    transfer = await service.create_transfer(session, household, payload)
    return success_response(_payload(transfer))


@router.get("/{transfer_id}")
async def get_transfer(
    session: SessionDep, household: CurrentHousehold, transfer_id: UUID
) -> dict[str, Any]:
    transfer = await service.get_transfer(session, household.id, transfer_id)
    return success_response(_payload(transfer))


@router.put("/{transfer_id}")
async def update_transfer(
    session: SessionDep,
    household: CurrentHousehold,
    transfer_id: UUID,
    payload: TransferUpdate,
) -> dict[str, Any]:
    transfer = await service.update_transfer(session, household, transfer_id, payload)
    return success_response(_payload(transfer))


@router.delete("/{transfer_id}")
async def delete_transfer(
    session: SessionDep, household: CurrentHousehold, transfer_id: UUID
) -> dict[str, Any]:
    await service.delete_transfer(session, household, transfer_id)
    return success_response(None, "Transfer deleted")


@router.post("/{transfer_id}/reverse", status_code=status.HTTP_201_CREATED)
async def reverse_transfer(
    session: SessionDep,
    household: CurrentHousehold,
    transfer_id: UUID,
    payload: Annotated[TransferReverse | None, Body()] = None,
) -> dict[str, Any]:
    reversal = await service.reverse_transfer(
        session, household, transfer_id, payload or TransferReverse()
    )
    return success_response(_payload(reversal))
