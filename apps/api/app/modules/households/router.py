"""Household endpoints (spec section 6.1)."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.pagination import PaginationDep, page_payload
from app.core.responses import success_response
from app.modules.households import service
from app.modules.households.schemas import HouseholdCreate, HouseholdRead, HouseholdUpdate

router = APIRouter(prefix="/households", tags=["households"])

SessionDep = Annotated[AsyncSession, Depends(get_db)]


def _payload(household: Any) -> dict[str, Any]:
    return HouseholdRead.model_validate(household).model_dump(mode="json")


@router.get("")
async def list_households(session: SessionDep, pagination: PaginationDep) -> dict[str, Any]:
    households, total = await service.list_households(session, pagination)
    return success_response(
        page_payload([_payload(household) for household in households], total, pagination)
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_household(session: SessionDep, payload: HouseholdCreate) -> dict[str, Any]:
    household = await service.create_household(session, payload)
    return success_response(_payload(household))


@router.get("/{household_id}")
async def get_household(session: SessionDep, household_id: UUID) -> dict[str, Any]:
    household = await service.get_household(session, household_id)
    return success_response(_payload(household))


@router.put("/{household_id}")
async def update_household(
    session: SessionDep, household_id: UUID, payload: HouseholdUpdate
) -> dict[str, Any]:
    household = await service.update_household(session, household_id, payload)
    return success_response(_payload(household))
