"""Pydantic schemas for finance transactions."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import TransactionType

CurrencyCode = Annotated[str, Field(pattern=r"^[A-Za-z]{3}$")]
Description = Annotated[str | None, Field(max_length=2000)]


def _upper_currency(value: str | None) -> str | None:
    return value.upper() if value is not None else None


class TransactionCreate(BaseModel):
    account_id: UUID
    category_id: UUID | None = None
    transaction_type: TransactionType
    amount: Annotated[Decimal, Field(gt=0)]
    currency: CurrencyCode | None = None
    exchange_rate: Annotated[Decimal | None, Field(gt=0)] = None
    exchange_rate_date: date | None = None
    transaction_date: datetime | None = None
    description: Description = None
    external_id: Annotated[str | None, Field(max_length=255)] = None
    status: Literal["draft", "confirmed"] = "draft"

    _currency = field_validator("currency")(_upper_currency)


class TransactionUpdate(BaseModel):
    account_id: UUID | None = None
    category_id: UUID | None = None
    transaction_type: TransactionType | None = None
    amount: Annotated[Decimal | None, Field(gt=0)] = None
    currency: CurrencyCode | None = None
    exchange_rate: Annotated[Decimal | None, Field(gt=0)] = None
    exchange_rate_date: date | None = None
    transaction_date: datetime | None = None
    description: Description = None
    external_id: Annotated[str | None, Field(max_length=255)] = None
    status: Literal["draft", "confirmed"] | None = None
    # Optimistic concurrency guard: when provided, the write is rejected with
    # TRANSACTION_CONFLICT if the row's updated_at no longer matches.
    expected_updated_at: datetime | None = None

    _currency = field_validator("currency")(_upper_currency)


class TransactionReverse(BaseModel):
    description: Description = None
    transaction_date: datetime | None = None


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    household_id: UUID
    account_id: UUID
    category_id: UUID | None
    transaction_type: str
    amount: Decimal
    currency: str
    base_amount: Decimal
    base_currency: str
    exchange_rate: Decimal
    exchange_rate_date: date
    transaction_date: datetime
    description: str | None
    source: str
    external_id: str | None
    status: str
    reverses_transaction_id: UUID | None
    transfer_id: UUID | None
    created_at: datetime
    updated_at: datetime
