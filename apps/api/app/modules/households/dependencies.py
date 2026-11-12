"""Household scoping derived from the authenticated user's JWT (Phase 2A)."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.exceptions import NotFoundError
from app.modules.auth.dependencies import CurrentUser
from app.modules.households.models import Household


async def get_current_household(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: CurrentUser,
) -> Household:
    household = await session.get(Household, user.household_id)
    if household is None:
        raise NotFoundError("Household not found", error_code="HOUSEHOLD_NOT_FOUND")
    return household


CurrentHousehold = Annotated[Household, Depends(get_current_household)]
