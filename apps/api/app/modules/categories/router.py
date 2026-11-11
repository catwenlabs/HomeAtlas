"""Category endpoints (spec section 6.4)."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.enums import CategoryType
from app.core.pagination import PaginationDep, page_payload
from app.core.responses import success_response
from app.modules.categories import service
from app.modules.categories.models import Category
from app.modules.categories.schemas import CategoryCreate, CategoryRead, CategoryUpdate
from app.modules.households.dependencies import CurrentHousehold

router = APIRouter(prefix="/categories", tags=["categories"])

SessionDep = Annotated[AsyncSession, Depends(get_db)]


def _payload(category: Category) -> dict[str, Any]:
    return CategoryRead.model_validate(category).model_dump(mode="json")


@router.get("")
async def list_categories(
    session: SessionDep,
    household: CurrentHousehold,
    pagination: PaginationDep,
    category_type: Annotated[CategoryType | None, Query()] = None,
    parent_id: Annotated[UUID | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> dict[str, Any]:
    categories, total = await service.list_categories(
        session,
        household.id,
        pagination,
        category_type=category_type,
        parent_id=parent_id,
        is_active=is_active,
    )
    return success_response(
        page_payload([_payload(category) for category in categories], total, pagination)
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_category(
    session: SessionDep, household: CurrentHousehold, payload: CategoryCreate
) -> dict[str, Any]:
    category = await service.create_category(session, household.id, payload)
    return success_response(_payload(category))


@router.get("/{category_id}")
async def get_category(
    session: SessionDep, household: CurrentHousehold, category_id: UUID
) -> dict[str, Any]:
    category = await service.get_category(session, household.id, category_id)
    return success_response(_payload(category))


@router.put("/{category_id}")
async def update_category(
    session: SessionDep,
    household: CurrentHousehold,
    category_id: UUID,
    payload: CategoryUpdate,
) -> dict[str, Any]:
    category = await service.update_category(session, household.id, category_id, payload)
    return success_response(_payload(category))


@router.delete("/{category_id}")
async def delete_category(
    session: SessionDep, household: CurrentHousehold, category_id: UUID
) -> dict[str, Any]:
    await service.delete_category(session, household.id, category_id)
    return success_response(None, "Category deleted")
