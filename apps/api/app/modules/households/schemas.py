"""Pydantic schemas for households."""

from datetime import datetime
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

HouseholdName = Annotated[str, Field(min_length=1, max_length=100)]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Za-z]{3}$")]
Timezone = Annotated[str, Field(min_length=1, max_length=64)]


def _normalize_currency(value: str) -> str:
    return value.upper()


def _validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown timezone: {value}") from exc
    return value


class HouseholdCreate(BaseModel):
    name: HouseholdName
    base_currency: CurrencyCode = "CNY"
    timezone: Timezone = "Asia/Shanghai"

    _upper_currency = field_validator("base_currency")(_normalize_currency)
    _timezone = field_validator("timezone")(_validate_timezone)


class HouseholdUpdate(BaseModel):
    name: HouseholdName | None = None
    base_currency: CurrencyCode | None = None
    timezone: Timezone | None = None

    _upper_currency = field_validator("base_currency")(_normalize_currency)
    _timezone = field_validator("timezone")(_validate_timezone)


class HouseholdRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    base_currency: str
    timezone: str
    created_at: datetime
    updated_at: datetime
