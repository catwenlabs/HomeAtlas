"""Household endpoints (spec section 6.1), scoped to the authenticated user."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.exceptions import NotFoundError
from app.core.pagination import PaginationDep, page_payload
from app.core.responses import success_response
from app.modules.auth.dependencies import OwnerUser
from app.modules.households import service
from app.modules.households.dependencies import CurrentHousehold
from app.modules.households.models import Household
from app.modules.households.schemas import HouseholdRead, HouseholdUpdate

router = APIRouter(prefix="/households", tags=["households"])

SessionDep = Annotated[AsyncSession, Depends(get_db)]


def _payload(household: Household) -> dict[str, Any]:
    return HouseholdRead.model_validate(household).model_dump(mode="json")


def _require_own(current: Household, household_id: UUID) -> None:
    if current.id != household_id:
        # Do not reveal whether another household exists.
        raise NotFoundError("Household not found", error_code="HOUSEHOLD_NOT_FOUND")


@router.get("")
async def list_households(
    household: CurrentHousehold,
    pagination: PaginationDep,
) -> dict[str, Any]:
    """Return only the caller's household; there is no cross-household listing."""
    return success_response(page_payload([_payload(household)], 1, pagination))


@router.get("/{household_id}")
async def get_household(
    session: SessionDep,
    household: CurrentHousehold,
    household_id: UUID,
) -> dict[str, Any]:
    _require_own(household, household_id)
    return success_response(_payload(await service.get_household(session, household_id)))


@router.put("/{household_id}")
async def update_household(
    session: SessionDep,
    household: CurrentHousehold,
    owner: OwnerUser,
    household_id: UUID,
    payload: HouseholdUpdate,
) -> dict[str, Any]:
    _require_own(household, household_id)
    updated = await service.update_household(session, household_id, payload, actor=owner.username)
    return success_response(_payload(updated))
