"""X-Household-Id scoping dependency (spec v1.3 section 6.0)."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.exceptions import AppError, NotFoundError
from app.modules.households.models import Household


async def get_current_household(
    session: Annotated[AsyncSession, Depends(get_db)],
    x_household_id: Annotated[UUID | None, Header(alias="X-Household-Id")] = None,
) -> Household:
    if x_household_id is not None:
        household = await session.get(Household, x_household_id)
        if household is None:
            raise NotFoundError("Household not found", error_code="HOUSEHOLD_NOT_FOUND")
        return household

    total = int(await session.scalar(select(func.count()).select_from(Household)) or 0)
    if total == 0:
        raise AppError(
            "No household exists; create one first",
            status_code=400,
            error_code="HOUSEHOLD_REQUIRED",
        )
    if total > 1:
        raise AppError(
            "Multiple households exist; provide the X-Household-Id header",
            status_code=400,
            error_code="HOUSEHOLD_REQUIRED",
        )
    household = (await session.scalars(select(Household).limit(1))).first()
    if household is None:  # pragma: no cover - count already proved it exists
        raise NotFoundError("Household not found", error_code="HOUSEHOLD_NOT_FOUND")
    return household


CurrentHousehold = Annotated[Household, Depends(get_current_household)]
