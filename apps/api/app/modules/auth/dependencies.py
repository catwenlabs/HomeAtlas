"""Bearer authentication dependencies (Phase 2A)."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import set_actor
from app.core.dependencies import get_db
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.auth.security import decode_access_token

_bearer = HTTPBearer(auto_error=False, description="JWT access token")


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> User:
    if credentials is None or not credentials.credentials:
        raise AppError(
            "Authentication required",
            status_code=401,
            error_code="AUTH_REQUIRED",
        )
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = UUID(str(payload["sub"]))
    except Exception as exc:
        raise AppError(
            "Invalid or expired access token",
            status_code=401,
            error_code="AUTH_INVALID_TOKEN",
        ) from exc
    user = await session.get(User, user_id)
    if user is None:
        raise AppError(
            "Invalid or expired access token",
            status_code=401,
            error_code="AUTH_INVALID_TOKEN",
        )
    if not user.is_active:
        raise AppError(
            "This account is disabled",
            status_code=403,
            error_code="AUTH_ACCOUNT_DISABLED",
        )
    set_actor(user.username)
    return user


async def require_owner(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role != "owner":
        raise AppError(
            "Only the household owner can perform this action",
            status_code=403,
            error_code="OWNER_REQUIRED",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
OwnerUser = Annotated[User, Depends(require_owner)]
