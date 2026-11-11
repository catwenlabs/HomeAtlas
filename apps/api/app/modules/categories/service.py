"""Category use cases, including the two-level hierarchy rules (spec 4.4)."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import CategoryType
from app.core.exceptions import AppError, NotFoundError
from app.core.pagination import Pagination, resolve_sort
from app.modules.categories.defaults import FINANCIAL_FEE_NAME
from app.modules.categories.models import Category
from app.modules.categories.schemas import CategoryCreate, CategoryUpdate
from app.modules.transactions.models import Transaction

_SORTABLE = {
    "sort_order": Category.sort_order,
    "name": Category.name,
    "created_at": Category.created_at,
    "updated_at": Category.updated_at,
}


async def list_categories(
    session: AsyncSession,
    household_id: UUID,
    pagination: Pagination,
    *,
    category_type: CategoryType | None = None,
    parent_id: UUID | None = None,
    is_active: bool | None = None,
) -> tuple[list[Category], int]:
    filters = [Category.household_id == household_id]
    if category_type is not None:
        filters.append(Category.category_type == category_type.value)
    if parent_id is not None:
        filters.append(Category.parent_id == parent_id)
    if is_active is not None:
        filters.append(Category.is_active == is_active)
    total = await session.scalar(select(func.count()).select_from(Category).where(*filters))
    column, descending = resolve_sort(
        pagination.sort_by, pagination.sort_order, _SORTABLE, "sort_order"
    )
    stmt = (
        select(Category)
        .where(*filters)
        .order_by(column.desc() if descending else column.asc(), Category.name.asc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return list((await session.scalars(stmt)).all()), int(total or 0)


async def get_category(session: AsyncSession, household_id: UUID, category_id: UUID) -> Category:
    category = await session.scalar(
        select(Category).where(
            Category.id == category_id,
            Category.household_id == household_id,
        )
    )
    if category is None:
        raise NotFoundError("Category not found", error_code="CATEGORY_NOT_FOUND")
    return category


async def _validate_parent(
    session: AsyncSession,
    household_id: UUID,
    parent_id: UUID,
    *,
    category_type: CategoryType,
    self_id: UUID | None = None,
) -> Category:
    if self_id is not None and parent_id == self_id:
        raise AppError(
            "A category cannot be its own parent",
            status_code=400,
            error_code="CATEGORY_PARENT_INVALID",
        )
    parent = await session.get(Category, parent_id)
    if parent is None:
        raise NotFoundError("Parent category not found", error_code="CATEGORY_NOT_FOUND")
    if parent.household_id != household_id:
        raise AppError(
            "Parent category belongs to another household",
            status_code=400,
            error_code="CATEGORY_PARENT_MISMATCH",
        )
    if parent.category_type != category_type.value:
        raise AppError(
            "Parent and child categories must have the same type",
            status_code=400,
            error_code="CATEGORY_TYPE_MISMATCH",
        )
    if parent.parent_id is not None:
        raise AppError(
            "Categories support at most two levels",
            status_code=400,
            error_code="CATEGORY_LEVEL_EXCEEDED",
        )
    return parent


async def _has_children(session: AsyncSession, category_id: UUID) -> bool:
    total = await session.scalar(
        select(func.count()).select_from(Category).where(Category.parent_id == category_id)
    )
    return bool(total)


async def create_category(
    session: AsyncSession,
    household_id: UUID,
    payload: CategoryCreate,
) -> Category:
    if payload.parent_id is not None:
        await _validate_parent(
            session,
            household_id,
            payload.parent_id,
            category_type=payload.category_type,
        )
    category = Category(
        household_id=household_id,
        name=payload.name,
        category_type=payload.category_type.value,
        parent_id=payload.parent_id,
        icon=payload.icon,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
    )
    session.add(category)
    await session.commit()
    await session.refresh(category)
    return category


async def update_category(
    session: AsyncSession,
    household_id: UUID,
    category_id: UUID,
    payload: CategoryUpdate,
) -> Category:
    category = await get_category(session, household_id, category_id)
    changes = payload.model_dump(exclude_unset=True)
    children = await _has_children(session, category.id)

    if category.name == FINANCIAL_FEE_NAME and (
        "name" in changes
        or (
            changes.get("category_type") is not None
            and changes["category_type"] is not CategoryType.EXPENSE
        )
    ):
        raise AppError(
            "The built-in financial fee category cannot be renamed or retyped",
            status_code=409,
            error_code="CATEGORY_SYSTEM_PROTECTED",
        )

    new_type = changes.get("category_type")
    if new_type is not None and children and new_type != category.category_type:
        raise AppError(
            "Cannot change the type of a category that has children",
            status_code=400,
            error_code="CATEGORY_HAS_CHILDREN",
        )

    parent_provided = "parent_id" in changes
    parent_id = changes.get("parent_id")
    if parent_provided and parent_id is not None:
        await _validate_parent(
            session,
            household_id,
            parent_id,
            category_type=CategoryType(new_type or category.category_type),
            self_id=category.id,
        )
        if children:
            raise AppError(
                "Cannot move a category that has children under another parent",
                status_code=400,
                error_code="CATEGORY_HAS_CHILDREN",
            )
    elif parent_provided and parent_id is None and children:
        # Moving to root is always valid; children stay at level two.
        pass

    for field, value in changes.items():
        if field == "category_type" and value is not None:
            setattr(category, field, CategoryType(value).value)
        elif value is not None or field in {"parent_id", "icon"}:
            setattr(category, field, value)

    await session.commit()
    await session.refresh(category)
    return category


async def delete_category(
    session: AsyncSession,
    household_id: UUID,
    category_id: UUID,
) -> None:
    category = await get_category(session, household_id, category_id)
    if category.name == FINANCIAL_FEE_NAME:
        raise AppError(
            "The built-in financial fee category cannot be deleted",
            status_code=409,
            error_code="CATEGORY_SYSTEM_PROTECTED",
        )
    if await _has_children(session, category.id):
        raise AppError(
            "Delete child categories first",
            status_code=409,
            error_code="CATEGORY_HAS_CHILDREN",
        )
    references = await session.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.category_id == category.id)
    )
    if references:
        raise AppError(
            "Category is referenced by transactions; deactivate it instead",
            status_code=409,
            error_code="CATEGORY_IN_USE",
        )
    await session.delete(category)
    await session.commit()
