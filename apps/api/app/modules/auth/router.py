"""Authentication endpoints (Phase 2A)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.responses import success_response
from app.modules.auth import service
from app.modules.auth.dependencies import CurrentUser
from app.modules.auth.schemas import LoginRequest
from app.modules.households.models import Household

router = APIRouter(prefix="/auth", tags=["auth"])

SessionDep = Annotated[AsyncSession, Depends(get_db)]


@router.post("/login")
async def login(session: SessionDep, payload: LoginRequest) -> dict[str, Any]:
    user = await service.authenticate(session, payload.username, payload.password)
    household = await session.get(Household, user.household_id)
    if household is None:  # pragma: no cover - protected by the FK
        raise RuntimeError("User references a missing household")
    return success_response(await service.token_response(user, household))


@router.get("/me")
async def me(session: SessionDep, user: CurrentUser) -> dict[str, Any]:
    household = await session.get(Household, user.household_id)
    data = service.user_response(user)
    data["household"] = (
        {
            "id": str(household.id),
            "name": household.name,
            "base_currency": household.base_currency,
            "timezone": household.timezone,
        }
        if household is not None
        else None
    )
    return success_response(data)


@router.post("/logout")
async def logout() -> dict[str, Any]:
    # Tokens are stateless; clients discard them locally.
    return success_response(None)
