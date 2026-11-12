"""Authentication, first-time setup and member management use cases."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.modules.audit.service import write_audit
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    SetupCategory,
    SetupRequest,
    SetupStatus,
    TokenResponse,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.modules.auth.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.modules.categories.defaults import DEFAULT_CATEGORIES
from app.modules.categories.models import Category
from app.modules.currencies.defaults import BUILTIN_CURRENCY_CODES, seed_currencies
from app.modules.currencies.service import get_currency
from app.modules.households.models import Household


async def setup_status(session: AsyncSession) -> SetupStatus:
    user = (await session.scalars(select(User).limit(1))).first()
    if user is None:
        return SetupStatus(initialized=False)
    household = await session.get(Household, user.household_id)
    return SetupStatus(
        initialized=True,
        household_name=household.name if household is not None else None,
    )


async def _ensure_not_initialized(session: AsyncSession) -> None:
    total = int(await session.scalar(select(func.count()).select_from(User)) or 0)
    if total > 0:
        raise ConflictError(
            "HomeAtlas has already been initialized",
            error_code="SETUP_ALREADY_COMPLETED",
        )


async def setup(session: AsyncSession, payload: SetupRequest) -> TokenResponse:
    await _ensure_not_initialized(session)
    if payload.currency_codes is not None and payload.base_currency not in payload.currency_codes:
        raise AppError(
            "The base currency must be among the selected currencies",
            status_code=400,
            error_code="BASE_CURRENCY_NOT_SELECTED",
        )
    selected_currencies = (
        payload.currency_codes
        if payload.currency_codes is not None
        else list(BUILTIN_CURRENCY_CODES)
    )
    await seed_currencies(session, selected_currencies)
    await get_currency(session, payload.base_currency)

    household = Household(
        name=payload.household_name,
        base_currency=payload.base_currency,
        timezone=payload.timezone,
    )
    session.add(household)
    await session.flush()

    categories = (
        payload.categories
        if payload.categories is not None
        else [
            SetupCategory(
                name=item.name,
                category_type=item.category_type.value,
                sort_order=item.sort_order,
                icon=item.icon,
            )
            for item in DEFAULT_CATEGORIES
        ]
    )
    session.add_all(
        [
            Category(
                household_id=household.id,
                name=item.name,
                category_type=item.category_type,
                parent_id=None,
                icon=item.icon,
                sort_order=item.sort_order,
                is_active=True,
            )
            for item in categories
        ]
    )
    await session.flush()

    user = User(
        household_id=household.id,
        username=payload.username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name or payload.username,
        role="owner",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    write_audit(
        session,
        household_id=household.id,
        action="setup.complete",
        entity_type="household",
        entity_id=household.id,
        after={
            "household_name": household.name,
            "base_currency": household.base_currency,
            "timezone": household.timezone,
            "owner": user.username,
            "currencies": selected_currencies,
            "categories": len(categories),
        },
        actor=user.username,
    )
    await session.commit()
    await session.refresh(user)
    await session.refresh(household)
    return await token_response(user, household)


async def authenticate(session: AsyncSession, username: str, password: str) -> User:
    user = (await session.scalars(select(User).where(User.username == username))).first()
    if user is None or not verify_password(password, user.password_hash):
        raise AppError(
            "Invalid username or password",
            status_code=401,
            error_code="AUTH_INVALID_CREDENTIALS",
        )
    if not user.is_active:
        raise AppError(
            "This account is disabled",
            status_code=403,
            error_code="AUTH_ACCOUNT_DISABLED",
        )
    return user


async def token_response(user: User, household: Household) -> TokenResponse:
    settings = get_settings()
    token = create_access_token(
        user_id=user.id,
        household_id=user.household_id,
        username=user.username,
        role=user.role,
    )
    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserRead.model_validate(user),
        household={
            "id": str(household.id),
            "name": household.name,
            "base_currency": household.base_currency,
            "timezone": household.timezone,
        },
    )


async def list_users(session: AsyncSession, household_id: UUID) -> list[User]:
    stmt = (
        select(User)
        .where(User.household_id == household_id)
        .order_by(User.created_at.asc(), User.username.asc())
    )
    return list((await session.scalars(stmt)).all())


async def _get_user(session: AsyncSession, household_id: UUID, user_id: UUID) -> User:
    user = await session.get(User, user_id)
    if user is None or user.household_id != household_id:
        raise NotFoundError("User not found", error_code="USER_NOT_FOUND")
    return user


async def create_user(
    session: AsyncSession,
    household_id: UUID,
    payload: UserCreate,
    *,
    actor: str,
) -> User:
    existing = (
        await session.scalars(select(User).where(User.username == payload.username))
    ).first()
    if existing is not None:
        raise ConflictError("Username is already taken", error_code="USERNAME_TAKEN")
    user = User(
        household_id=household_id,
        username=payload.username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        role=payload.role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    write_audit(
        session,
        household_id=household_id,
        action="user.create",
        entity_type="user",
        entity_id=user.id,
        after={"username": user.username, "role": user.role},
        actor=actor,
    )
    await session.commit()
    await session.refresh(user)
    return user


async def update_user(
    session: AsyncSession,
    household_id: UUID,
    user_id: UUID,
    payload: UserUpdate,
    *,
    actor: str,
) -> User:
    user = await _get_user(session, household_id, user_id)
    before = {
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
    }
    changes = payload.model_dump(exclude_unset=True)
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
    for field in ("display_name", "role", "is_active"):
        value = changes.get(field)
        if value is not None:
            setattr(user, field, value)

    loses_owner = user.role != "owner" or not user.is_active
    if before["role"] == "owner" and before["is_active"] and loses_owner:
        owners = int(
            await session.scalar(
                select(func.count())
                .select_from(User)
                .where(
                    User.household_id == household_id,
                    User.role == "owner",
                    User.is_active.is_(True),
                )
            )
            or 0
        )
        if owners <= 1:
            raise AppError(
                "The household must keep at least one active owner",
                status_code=409,
                error_code="LAST_OWNER_PROTECTED",
            )

    write_audit(
        session,
        household_id=household_id,
        action="user.update",
        entity_type="user",
        entity_id=user.id,
        before=before,
        after={
            "display_name": user.display_name,
            "role": user.role,
            "is_active": user.is_active,
        },
        actor=actor,
    )
    await session.commit()
    await session.refresh(user)
    return user


def user_response(user: User) -> dict[str, Any]:
    return UserRead.model_validate(user).model_dump(mode="json")
