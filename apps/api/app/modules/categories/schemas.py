"""Pydantic schemas for finance categories."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import CategoryType

CategoryName = Annotated[str, Field(min_length=1, max_length=100)]


def _strip_name(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise ValueError("Category name must not be blank")
    return stripped


class CategoryCreate(BaseModel):
    name: CategoryName
    category_type: CategoryType
    parent_id: UUID | None = None
    icon: Annotated[str | None, Field(max_length=50)] = None
    sort_order: int = 0
    is_active: bool = True

    _name = field_validator("name")(_strip_name)


class CategoryUpdate(BaseModel):
    name: CategoryName | None = None
    category_type: CategoryType | None = None
    parent_id: UUID | None = None
    icon: Annotated[str | None, Field(max_length=50)] = None
    sort_order: int | None = None
    is_active: bool | None = None

    _name = field_validator("name")(_strip_name)


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    household_id: UUID
    name: str
    category_type: str
    parent_id: UUID | None
    icon: str | None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
