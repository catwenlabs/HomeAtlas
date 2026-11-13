"""Pydantic schemas for the asset summary and net worth snapshots (2C-1)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AssetBuckets(BaseModel):
    """Display buckets; the net worth formula never reads them."""

    idle: Decimal
    invested: Decimal
    matured: Decimal


class CurrencyAssetLine(BaseModel):
    currency: str
    cash: Decimal
    invested: Decimal
    liabilities: Decimal
    fx_rate: Decimal


class AssetsSummary(BaseModel):
    base_currency: str
    net_worth: Decimal
    buckets: AssetBuckets
    total_liabilities: Decimal
    unrealized_pnl: Decimal
    unmapped_cash: Decimal
    daily_interest_income: Decimal
    daily_interest_expense: Decimal
    inactive_count: int
    matured_investments: list[dict[str, Any]]
    currency_breakdown: list[CurrencyAssetLine]
    fx_rates_used: dict[str, Decimal]


class NetWorthSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    household_id: UUID
    snapshot_date: date
    base_currency: str
    total_cash: Decimal
    total_invested: Decimal
    total_liabilities: Decimal
    net_worth: Decimal
    unrealized_pnl: Decimal
    unmapped_cash: Decimal
    daily_interest_income: Decimal
    daily_interest_expense: Decimal
    currency_breakdown: list[dict[str, Any]]
    fx_rates_used: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class MonthlyBucket(BaseModel):
    month: str
    snapshot_count: int
    net_worth_start: Decimal
    net_worth_end: Decimal
    net_change: Decimal
    daily_interest_income: Decimal
    daily_interest_expense: Decimal


class MonthlySummary(BaseModel):
    year: int
    months: list[MonthlyBucket]
