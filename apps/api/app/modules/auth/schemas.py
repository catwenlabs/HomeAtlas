"""Auth and setup schemas."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

Username = Annotated[str, Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")]
Password = Annotated[str, Field(min_length=8, max_length=128)]
DisplayName = Annotated[str, Field(min_length=1, max_length=100)]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Za-z]{3}$")]
Timezone = Annotated[str, Field(min_length=1, max_length=64)]
Role = Literal["owner", "member"]


def _normalize_username(value: str) -> str:
    return value.strip().lower()


def _normalize_currency(value: str) -> str:
    return value.upper()


def _validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown timezone: {value}") from exc
    return value


class LoginRequest(BaseModel):
    username: Username
    password: Password

    _username = field_validator("username")(_normalize_username)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    household_id: UUID
    username: str
    display_name: str
    role: Role
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int
    user: UserRead
    household: dict[str, Any]


class UserCreate(BaseModel):
    username: Username
    password: Password
    display_name: DisplayName
    role: Role = "member"

    _username = field_validator("username")(_normalize_username)


class UserUpdate(BaseModel):
    display_name: DisplayName | None = None
    password: Password | None = None
    role: Role | None = None
    is_active: bool | None = None


class SetupStatus(BaseModel):
    initialized: bool
    household_name: str | None = None


class SetupCategory(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    category_type: Literal["income", "expense"]
    sort_order: Annotated[int, Field(ge=0, le=10000)] = 0
    icon: Annotated[str | None, Field(max_length=50)] = None


class SetupRequest(BaseModel):
    username: Username
    password: Password
    display_name: DisplayName | None = None
    household_name: Annotated[str, Field(min_length=1, max_length=100)] = "我的家庭"
    base_currency: CurrencyCode = "CNY"
    timezone: Timezone = "Asia/Shanghai"
    currency_codes: list[CurrencyCode] | None = None
    categories: list[SetupCategory] | None = None

    _username = field_validator("username")(_normalize_username)
    _currency = field_validator("base_currency")(_normalize_currency)
    _timezone = field_validator("timezone")(_validate_timezone)

    @field_validator("currency_codes")
    @classmethod
    def _normalize_currency_codes(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return list(dict.fromkeys(code.upper() for code in value))

    @field_validator("categories")
    @classmethod
    def _unique_categories(cls, value: list[SetupCategory] | None) -> list[SetupCategory] | None:
        if value is None:
            return None
        seen = {(item.category_type, item.name) for item in value}
        if len(seen) != len(value):
            raise ValueError("Duplicate category name within the same type")
        return value
