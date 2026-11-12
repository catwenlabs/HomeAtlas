"""Household member management (Phase 2A)."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.responses import success_response
from app.modules.auth import service
from app.modules.auth.dependencies import CurrentUser, OwnerUser
from app.modules.auth.schemas import UserCreate, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])

SessionDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("")
async def list_users(session: SessionDep, user: CurrentUser) -> dict[str, Any]:
    users = await service.list_users(session, user.household_id)
    return success_response([service.user_response(item) for item in users])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(session: SessionDep, owner: OwnerUser, payload: UserCreate) -> dict[str, Any]:
    user = await service.create_user(session, owner.household_id, payload, actor=owner.username)
    return success_response(service.user_response(user))


@router.put("/{user_id}")
async def update_user(
    session: SessionDep,
    owner: OwnerUser,
    user_id: UUID,
    payload: UserUpdate,
) -> dict[str, Any]:
    user = await service.update_user(
        session, owner.household_id, user_id, payload, actor=owner.username
    )
    return success_response(service.user_response(user))
