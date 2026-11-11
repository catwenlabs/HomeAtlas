"""Unified list pagination (spec v1.3 section 6.8)."""

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Query

from app.core.enums import SortOrder
from app.core.exceptions import AppError


@dataclass(frozen=True)
class Pagination:
    page: int
    page_size: int
    sort_by: str | None
    sort_order: SortOrder

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


async def pagination_params(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort_by: Annotated[str | None, Query()] = None,
    sort_order: Annotated[SortOrder, Query()] = SortOrder.ASC,
) -> Pagination:
    return Pagination(
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
    )


PaginationDep = Annotated[Pagination, Depends(pagination_params)]


def page_payload(items: list[Any], total: int, pagination: Pagination) -> dict[str, Any]:
    return {
        "items": items,
        "total": total,
        "page": pagination.page,
        "page_size": pagination.page_size,
    }


def resolve_sort(
    sort_by: str | None,
    sort_order: SortOrder,
    allowed: dict[str, Any],
    default: str,
) -> tuple[Any, bool]:
    """Map a client sort field to a whitelisted column; reject unknown fields."""
    field = sort_by or default
    column = allowed.get(field)
    if column is None:
        raise AppError(
            f"Unsupported sort field: {field}",
            status_code=400,
            error_code="INVALID_SORT_FIELD",
        )
    return column, sort_order is SortOrder.DESC
