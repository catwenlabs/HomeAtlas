"""Pydantic schemas for investments, tags, holdings, and redeem flows."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import (
    InvestmentType,
    Liquidity,
    Market,
)

Name = Annotated[str, Field(min_length=1, max_length=100)]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Za-z]{3}$")]
Amount = Annotated[Decimal, Field(ge=0)]
PositiveAmount = Annotated[Decimal, Field(gt=0)]


class FundTransferSpec(BaseModel):
    """Cash leg of an investment action: money leaves from_account."""

    from_account_id: UUID
    from_amount: PositiveAmount
    exchange_rate: Annotated[Decimal | None, Field(gt=0)] = None


class InvestmentCreate(BaseModel):
    name: Name
    investment_type: InvestmentType
    account_id: UUID
    principal: Amount = Decimal("0")
    current_value: Amount | None = None
    currency: CurrencyCode = "CNY"
    annual_rate: Annotated[Decimal | None, Field(ge=0)] = None
    start_date: date
    end_date: date | None = None
    liquidity: Liquidity | None = None
    remark: Annotated[str | None, Field(max_length=500)] = None
    tag_ids: list[UUID] = Field(default_factory=list)
    fund_transfer: FundTransferSpec | None = None
    # Legacy positions whose cash source is not tracked: the principal is
    # booked as an opening balance on the investment account instead of a
    # transfer. Mutually exclusive with fund_transfer.
    opening_position: bool = False
    opening_exchange_rate: Annotated[Decimal | None, Field(gt=0)] = None

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return value.upper()


class InvestmentUpdate(BaseModel):
    """Metadata only: principal always comes from funding or an opening position."""

    name: Name | None = None
    investment_type: InvestmentType | None = None
    annual_rate: Annotated[Decimal | None, Field(ge=0)] = None
    start_date: date | None = None
    end_date: date | None = None
    liquidity: Liquidity | None = None
    remark: Annotated[str | None, Field(max_length=500)] = None
    principal: Amount | None = None


class InvestmentValueUpdate(BaseModel):
    current_value: Amount


class InvestmentFund(BaseModel):
    fund_transfer: FundTransferSpec


class InvestmentRedeem(BaseModel):
    to_account_id: UUID
    to_amount: PositiveAmount
    exchange_rate: Annotated[Decimal | None, Field(gt=0)] = None


class InvestmentTagsUpdate(BaseModel):
    tag_ids: list[UUID] = Field(default_factory=list)


class InvestmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    household_id: UUID
    name: str
    investment_type: str
    account_id: UUID
    principal: Decimal
    current_value: Decimal
    currency: str
    annual_rate: Decimal | None
    start_date: date
    end_date: date | None
    liquidity: str | None
    status: str
    realized_pnl: Decimal | None
    pre_redeem_value: Decimal | None
    remark: str | None
    created_at: datetime
    updated_at: datetime

    # Derived / enrichment fields filled by the router layer.
    matured: bool = False
    tag_ids: list[UUID] = Field(default_factory=list)
    holdings_cost: Decimal | None = None


class HoldingCreate(BaseModel):
    market: Market
    symbol: Annotated[str, Field(min_length=1, max_length=20)]
    quantity: PositiveAmount
    cost_price: Amount
    remark: Annotated[str | None, Field(max_length=500)] = None


class HoldingUpdate(BaseModel):
    quantity: PositiveAmount | None = None
    cost_price: Amount | None = None
    remark: Annotated[str | None, Field(max_length=500)] = None


class HoldingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    investment_id: UUID
    market: str
    symbol: str
    quantity: Decimal
    cost_price: Decimal
    cost_subtotal: Decimal | None = None  # derived, filled by the router
    remark: str | None
    created_at: datetime
    updated_at: datetime


class TagCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=50)]
    color: Annotated[str | None, Field(pattern=r"^#[0-9A-Fa-f]{6}$")] = None


class TagUpdate(BaseModel):
    name: Annotated[str | None, Field(min_length=1, max_length=50)] = None
    color: Annotated[str | None, Field(pattern=r"^#[0-9A-Fa-f]{6}$")] = None


class TagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    household_id: UUID
    name: str
    color: str | None
    created_at: datetime
    updated_at: datetime


class QuoteRead(BaseModel):
    market: str
    symbol: str
    name: str
    price: Decimal
    currency: str
    quoted_at: datetime


class RefreshValueItem(BaseModel):
    market: str
    symbol: str
    name: str
    quantity: Decimal
    price: Decimal
    currency: str
    subtotal: Decimal


class RefreshValueResult(BaseModel):
    current_value: Decimal
    previous_value: Decimal
    items: list[RefreshValueItem]
