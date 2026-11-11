"""Pydantic schemas for finance transfers (spec section 4.6)."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

CurrencyCode = Annotated[str, Field(pattern=r"^[A-Za-z]{3}$")]
Description = Annotated[str | None, Field(max_length=2000)]
PositiveAmount = Annotated[Decimal, Field(gt=0)]


def _upper_currency(value: str | None) -> str | None:
    return value.upper() if value is not None else None


class TransferCreate(BaseModel):
    from_account_id: UUID
    to_account_id: UUID
    from_amount: PositiveAmount
    from_currency: CurrencyCode | None = None
    to_amount: PositiveAmount
    to_currency: CurrencyCode | None = None
    exchange_rate: Annotated[Decimal | None, Field(gt=0)] = None
    base_exchange_rate: Annotated[Decimal | None, Field(gt=0)] = None
    fee: Annotated[Decimal, Field(ge=0)] = Decimal("0")
    fee_currency: CurrencyCode | None = None
    fee_exchange_rate: Annotated[Decimal | None, Field(gt=0)] = None
    transfer_date: datetime | None = None
    description: Description = None
    status: Literal["draft", "confirmed"] = "draft"

    _currency = field_validator("from_currency", "to_currency", "fee_currency")(_upper_currency)


class TransferUpdate(BaseModel):
    from_account_id: UUID | None = None
    to_account_id: UUID | None = None
    from_amount: Annotated[Decimal | None, Field(gt=0)] = None
    from_currency: CurrencyCode | None = None
    to_amount: Annotated[Decimal | None, Field(gt=0)] = None
    to_currency: CurrencyCode | None = None
    exchange_rate: Annotated[Decimal | None, Field(gt=0)] = None
    base_exchange_rate: Annotated[Decimal | None, Field(gt=0)] = None
    fee: Annotated[Decimal | None, Field(ge=0)] = None
    fee_currency: CurrencyCode | None = None
    fee_exchange_rate: Annotated[Decimal | None, Field(gt=0)] = None
    transfer_date: datetime | None = None
    description: Description = None
    status: Literal["draft", "confirmed"] | None = None

    _currency = field_validator("from_currency", "to_currency", "fee_currency")(_upper_currency)


class TransferReverse(BaseModel):
    description: Description = None
    transfer_date: datetime | None = None


class TransferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    household_id: UUID
    from_account_id: UUID
    to_account_id: UUID
    from_amount: Decimal
    from_currency: str
    to_amount: Decimal
    to_currency: str
    exchange_rate: Decimal
    base_amount: Decimal | None
    base_currency: str | None
    fee: Decimal
    fee_currency: str
    transfer_date: datetime
    description: str | None
    status: str
    reverses_transfer_id: UUID | None
    created_at: datetime
    updated_at: datetime
