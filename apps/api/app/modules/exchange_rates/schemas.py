"""Pydantic schemas for the household exchange-rate catalog."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

CurrencyCode = Annotated[str, Field(pattern=r"^[A-Za-z]{3}$")]


class ExchangeRateCreate(BaseModel):
    base_currency: CurrencyCode
    quote_currency: CurrencyCode
    rate: Decimal
    rate_date: date

    @field_validator("base_currency", "quote_currency")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()


class ExchangeRateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    household_id: UUID
    base_currency: str
    quote_currency: str
    rate: Decimal
    rate_date: date
    source: str
    created_at: datetime
    updated_at: datetime


class ExchangeRateLatest(BaseModel):
    base_currency: str
    quote_currency: str
    rate: Decimal
    rate_date: date
    direction: str  # "direct" | "inverse"
    source_pair: str  # e.g. "USD/CNY" — the stored pair actually consulted
