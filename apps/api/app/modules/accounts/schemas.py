"""Pydantic schemas for accounts, reconciliation snapshots, and opening balances."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import AccountType, BalanceSource, Liquidity

Name = Annotated[str, Field(min_length=1, max_length=100)]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Za-z]{3}$")]
AnnualRate = Annotated[Decimal, Field(ge=0)]
CreditLimit = Annotated[Decimal, Field(ge=0)]


class AccountCreate(BaseModel):
    name: Name
    institution: Annotated[str | None, Field(max_length=100)] = None
    account_type: AccountType = AccountType.BANK
    currency: CurrencyCode = "CNY"
    external_ref: Annotated[str | None, Field(max_length=255)] = None
    is_active: bool = True
    annual_rate: AnnualRate | None = None
    liquidity: Liquidity | None = None
    credit_limit: CreditLimit | None = None

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return value.upper()


class AccountUpdate(BaseModel):
    name: Name | None = None
    institution: Annotated[str | None, Field(max_length=100)] = None
    account_type: AccountType | None = None
    currency: CurrencyCode | None = None
    external_ref: Annotated[str | None, Field(max_length=255)] = None
    is_active: bool | None = None
    annual_rate: AnnualRate | None = None
    liquidity: Liquidity | None = None
    credit_limit: CreditLimit | None = None

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return value.upper() if value is not None else None


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    household_id: UUID
    name: str
    institution: str | None
    account_type: str
    currency: str
    external_ref: str | None
    is_active: bool
    annual_rate: Decimal | None
    liquidity: str | None
    credit_limit: Decimal | None
    created_at: datetime
    updated_at: datetime


class OpeningBalanceUpsert(BaseModel):
    amount: Decimal
    currency: CurrencyCode | None = None
    exchange_rate: Annotated[Decimal | None, Field(gt=0)] = None
    exchange_rate_date: date | None = None
    transaction_date: datetime | None = None
    description: Annotated[str | None, Field(max_length=2000)] = None

    @field_validator("amount")
    @classmethod
    def _finite_amount(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("Amount must be finite")
        return value

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None


class AccountBalanceSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    currency: str
    balance: Decimal
    snapshot_at: datetime
    source: BalanceSource
    created_at: datetime


class BalanceLine(BaseModel):
    currency: str
    book_balance: Decimal
    latest_snapshot: AccountBalanceSnapshotRead | None = None
    difference: Decimal | None = None


class AccountBalancesRead(BaseModel):
    account_id: UUID
    balances: list[BalanceLine]
