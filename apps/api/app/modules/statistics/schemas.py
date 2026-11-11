"""Pydantic response schemas for income/expense statistics.

Money is returned as decimal strings (Pydantic JSON mode) so callers never see
binary floating-point rounding. Amounts aggregate the stored ``base_amount``
and keep the NUMERIC(24,8) scale.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, PlainSerializer


def _format_decimal(value: Decimal) -> str:
    return format(value, "f")


Money = Annotated[
    Decimal,
    PlainSerializer(_format_decimal, return_type=str, when_used="json"),
]


class IncomeExpenseSummary(BaseModel):
    start_date: date
    end_date: date
    base_currency: str
    income: Money
    expense: Money
    net: Money
    income_count: int
    expense_count: int
    transaction_count: int


class CategoryStatItem(BaseModel):
    category_id: UUID | None
    category_name: str
    category_type: str
    amount: Money
    percentage: Money
    transaction_count: int


class CategoryStatistics(BaseModel):
    start_date: date
    end_date: date
    base_currency: str
    income_total: Money
    expense_total: Money
    items: list[CategoryStatItem]


class PeriodStatisticsItem(BaseModel):
    period: str
    income: Money
    expense: Money
    net: Money
    income_count: int
    expense_count: int
    transaction_count: int


class MonthlyStatistics(BaseModel):
    start_date: date
    end_date: date
    base_currency: str
    granularity: Literal["month", "year"]
    income_total: Money
    expense_total: Money
    net_total: Money
    items: list[PeriodStatisticsItem]


class CashflowItem(PeriodStatisticsItem):
    cumulative_net: Money


class CashflowStatistics(BaseModel):
    start_date: date
    end_date: date
    base_currency: str
    granularity: Literal["day", "month", "year"]
    income_total: Money
    expense_total: Money
    net_total: Money
    items: list[CashflowItem]


class CurrencyBalance(BaseModel):
    currency: str
    book_balance: Money


class CurrencyBalanceTotal(CurrencyBalance):
    account_count: int


class AccountBalanceSummary(BaseModel):
    account_id: UUID
    name: str
    account_type: str
    is_active: bool
    balances: list[CurrencyBalance]


class AccountBalancesStatistics(BaseModel):
    base_currency: str
    balances: list[CurrencyBalanceTotal]
    accounts: list[AccountBalanceSummary]


class OverviewStatistics(BaseModel):
    start_date: date
    end_date: date
    base_currency: str
    income: Money
    expense: Money
    net: Money
    income_count: int
    expense_count: int
    transaction_count: int
    assets: list[CurrencyBalance]
    account_count: int
