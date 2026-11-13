"""Pydantic schemas for loans (asset-design sections 4.3, 6.4)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.enums import RepaymentType

Name = Annotated[str, Field(min_length=1, max_length=100)]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Za-z]{3}$")]


class LoanCreate(BaseModel):
    name: Name
    institution: Annotated[str | None, Field(max_length=100)] = None
    principal: Annotated[Decimal, Field(gt=0)]
    currency: CurrencyCode = "CNY"
    annual_rate: Annotated[Decimal, Field(ge=0)]
    start_date: date
    end_date: date | None = None
    due_day: Annotated[int | None, Field(ge=1, le=31)] = None
    repayment_type: RepaymentType
    linked_account_id: UUID | None = None
    remaining_principal: Annotated[Decimal, Field(ge=0)] | None = None
    remark: Annotated[str | None, Field(max_length=500)] = None

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def _remaining_within_principal(self) -> Self:
        if self.remaining_principal is not None and self.remaining_principal > self.principal:
            raise ValueError("remaining_principal cannot exceed principal")
        return self


class LoanUpdate(BaseModel):
    name: Name | None = None
    institution: Annotated[str | None, Field(max_length=100)] = None
    annual_rate: Annotated[Decimal | None, Field(ge=0)] = None
    end_date: date | None = None
    due_day: Annotated[int | None, Field(ge=1, le=31)] = None
    repayment_type: RepaymentType | None = None
    linked_account_id: UUID | None = None
    remaining_principal: Annotated[Decimal | None, Field(ge=0)] = None
    remark: Annotated[str | None, Field(max_length=500)] = None


class LoanSettle(BaseModel):
    settled_date: date


class LoanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    household_id: UUID
    name: str
    institution: str | None
    principal: Decimal
    currency: str
    annual_rate: Decimal
    start_date: date
    end_date: date | None
    due_day: int | None
    repayment_type: str
    linked_account_id: UUID | None
    remaining_principal: Decimal
    status: str
    settled_date: date | None
    remark: str | None
    created_at: datetime
    updated_at: datetime

    # Derived display field: daily interest at the current rate.
    daily_interest: Decimal | None = None
