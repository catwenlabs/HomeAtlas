"""Income/expense statistics use cases (spec sections 5.1, 5.2 and 6.7).

Only effective confirmed income/expense rows are aggregated:

* ``transaction_type IN ('income', 'expense')`` — opening balances are excluded.
* ``status = 'confirmed'`` — drafts never count and a reversed original is
  already marked ``reversed``.
* ``reverses_transaction_id IS NULL`` — the reversal row is skipped as well, so
  a reversed pair cancels out instead of inflating gross income/expense.

Internal transfer principals live in ``finance.transfers`` rather than in
``transactions``, so they are naturally excluded. The transfer fee is a derived
``expense`` transaction and therefore counts exactly once (spec 5.2).

Amounts aggregate the stored ``base_amount`` (household base currency fixed at
entry time). Period grouping truncates timestamps in ``household.timezone`` and
never in UTC.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import Text, cast, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import CategoryType, TransactionStatus, TransactionType
from app.core.exceptions import AppError
from app.core.money import quantize_amount, quantize_money
from app.modules.accounts.models import Account
from app.modules.accounts.service import get_household_book_balances
from app.modules.categories.models import Category
from app.modules.households.models import Household
from app.modules.statistics.schemas import (
    AccountBalancesStatistics,
    AccountBalanceSummary,
    CashflowItem,
    CashflowStatistics,
    CategoryStatistics,
    CategoryStatItem,
    CurrencyBalance,
    CurrencyBalanceTotal,
    IncomeExpenseSummary,
    MonthlyStatistics,
    OverviewStatistics,
    PeriodStatisticsItem,
)
from app.modules.transactions.models import Transaction

Granularity = Literal["day", "month", "year"]
MonthlyGranularity = Literal["month", "year"]

_STAT_TYPES = (TransactionType.INCOME.value, TransactionType.EXPENSE.value)
_PERIOD_FORMATS: dict[str, str] = {
    "day": "YYYY-MM-DD",
    "month": "YYYY-MM",
    "year": "YYYY",
}
MAX_CASHFLOW_BUCKETS = 3660
UNCATEGORIZED_NAME = "未分类"


def _default_range(household: Household, *, yearly: bool) -> tuple[date, date]:
    today = datetime.now(ZoneInfo(household.timezone)).date()
    if yearly:
        return date(today.year, 1, 1), date(today.year, 12, 31)
    start = date(today.year, today.month, 1)
    next_month = date(today.year + (today.month == 12), today.month % 12 + 1, 1)
    return start, next_month - timedelta(days=1)


def _resolve_range(
    household: Household,
    start_date: date | None,
    end_date: date | None,
    *,
    yearly: bool = False,
) -> tuple[date, date]:
    default_start, default_end = _default_range(household, yearly=yearly)
    start = start_date or default_start
    end = end_date or default_end
    if end < start:
        raise AppError(
            "end_date must be on or after start_date",
            status_code=400,
            error_code="INVALID_DATE_RANGE",
        )
    return start, end


def _range_filters(
    household: Household,
    start_date: date,
    end_date: date,
    transaction_type: CategoryType | None = None,
) -> list[Any]:
    tz = ZoneInfo(household.timezone)
    filters: list[Any] = [
        Transaction.household_id == household.id,
        Transaction.transaction_type.in_(_STAT_TYPES),
        Transaction.status == TransactionStatus.CONFIRMED.value,
        Transaction.reverses_transaction_id.is_(None),
        Transaction.transaction_date >= datetime.combine(start_date, time.min, tzinfo=tz),
        Transaction.transaction_date
        < datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=tz),
    ]
    if transaction_type is not None:
        filters.append(Transaction.transaction_type == transaction_type.value)
    return filters


def _period_expression(household: Household, granularity: Granularity) -> Any:
    zone = cast(literal(household.timezone), Text)
    local_timestamp = func.timezone(zone, Transaction.transaction_date)
    return func.to_char(local_timestamp, _PERIOD_FORMATS[granularity])


def _iter_periods(start_date: date, end_date: date, granularity: Granularity) -> list[str]:
    periods: list[str] = []
    if granularity == "day":
        current = start_date
        while current <= end_date:
            periods.append(current.isoformat())
            current += timedelta(days=1)
        return periods

    if granularity == "month":
        year, month = start_date.year, start_date.month
        while (year, month) <= (end_date.year, end_date.month):
            periods.append(f"{year:04d}-{month:02d}")
            if month == 12:
                year, month = year + 1, 1
            else:
                month += 1
        return periods

    return [f"{year:04d}" for year in range(start_date.year, end_date.year + 1)]


def _aggregate_periods(
    rows: Sequence[Any],
) -> tuple[dict[str, Decimal], dict[str, Decimal], dict[str, int], dict[str, int]]:
    income: dict[str, Decimal] = defaultdict(Decimal)
    expense: dict[str, Decimal] = defaultdict(Decimal)
    income_count: dict[str, int] = defaultdict(int)
    expense_count: dict[str, int] = defaultdict(int)
    for period, transaction_type, total, count in rows:
        amount = quantize_money(total or Decimal("0"))
        if transaction_type == TransactionType.INCOME.value:
            income[period] += amount
            income_count[period] += int(count)
        else:
            expense[period] += amount
            expense_count[period] += int(count)
    return income, expense, income_count, expense_count


async def _income_expense_totals(
    session: AsyncSession,
    household: Household,
    start: date,
    end: date,
) -> tuple[Decimal, Decimal, int, int]:
    rows = (
        await session.execute(
            select(
                Transaction.transaction_type,
                func.sum(Transaction.base_amount),
                func.count(),
            )
            .where(*_range_filters(household, start, end))
            .group_by(Transaction.transaction_type)
        )
    ).all()

    income = Decimal("0")
    expense = Decimal("0")
    income_count = 0
    expense_count = 0
    for transaction_type, total, count in rows:
        amount = quantize_money(total or Decimal("0"))
        if transaction_type == TransactionType.INCOME.value:
            income += amount
            income_count += int(count)
        else:
            expense += amount
            expense_count += int(count)
    return quantize_money(income), quantize_money(expense), income_count, expense_count


async def income_expense(
    session: AsyncSession,
    household: Household,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    start, end = _resolve_range(household, start_date, end_date)
    income, expense, income_count, expense_count = await _income_expense_totals(
        session, household, start, end
    )

    summary = IncomeExpenseSummary(
        start_date=start,
        end_date=end,
        base_currency=str(household.base_currency).strip(),
        income=income,
        expense=expense,
        net=quantize_money(income - expense),
        income_count=income_count,
        expense_count=expense_count,
        transaction_count=income_count + expense_count,
    )
    return summary.model_dump(mode="json")


async def overview(
    session: AsyncSession,
    household: Household,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    start, end = _resolve_range(household, start_date, end_date)
    income, expense, income_count, expense_count = await _income_expense_totals(
        session, household, start, end
    )
    book = await get_household_book_balances(session, household.id)
    currency_totals: dict[str, Decimal] = defaultdict(Decimal)
    for balances in book.values():
        for currency, amount in balances.items():
            currency_totals[currency] += amount

    account_count = int(
        await session.scalar(
            select(func.count()).select_from(Account).where(Account.household_id == household.id)
        )
        or 0
    )
    summary = OverviewStatistics(
        start_date=start,
        end_date=end,
        base_currency=str(household.base_currency).strip(),
        income=income,
        expense=expense,
        net=quantize_money(income - expense),
        income_count=income_count,
        expense_count=expense_count,
        transaction_count=income_count + expense_count,
        assets=[
            CurrencyBalance(currency=currency, book_balance=quantize_money(amount))
            for currency, amount in sorted(currency_totals.items())
        ],
        account_count=account_count,
    )
    return summary.model_dump(mode="json")


async def account_balances(
    session: AsyncSession,
    household: Household,
) -> dict[str, Any]:
    book = await get_household_book_balances(session, household.id)
    accounts = list(
        (
            await session.scalars(
                select(Account)
                .where(Account.household_id == household.id)
                .order_by(Account.created_at.asc(), Account.name.asc())
            )
        ).all()
    )

    currency_totals: dict[str, Decimal] = defaultdict(Decimal)
    currency_counts: dict[str, int] = defaultdict(int)
    account_items: list[AccountBalanceSummary] = []
    for account in accounts:
        lines = [
            CurrencyBalance(currency=currency, book_balance=quantize_money(amount))
            for currency, amount in sorted(book.get(account.id, {}).items())
        ]
        for line in lines:
            currency_totals[line.currency] += line.book_balance
            currency_counts[line.currency] += 1
        account_items.append(
            AccountBalanceSummary(
                account_id=account.id,
                name=account.name,
                account_type=account.account_type,
                is_active=account.is_active,
                balances=lines,
            )
        )

    statistics = AccountBalancesStatistics(
        base_currency=str(household.base_currency).strip(),
        balances=[
            CurrencyBalanceTotal(
                currency=currency,
                book_balance=quantize_money(amount),
                account_count=currency_counts[currency],
            )
            for currency, amount in sorted(currency_totals.items())
        ],
        accounts=account_items,
    )
    return statistics.model_dump(mode="json")


async def category_statistics(
    session: AsyncSession,
    household: Household,
    start_date: date | None = None,
    end_date: date | None = None,
    transaction_type: CategoryType | None = None,
) -> dict[str, Any]:
    start, end = _resolve_range(household, start_date, end_date)
    category_type = func.coalesce(Category.category_type, Transaction.transaction_type)
    rows = (
        await session.execute(
            select(
                Transaction.category_id,
                Category.name,
                category_type,
                func.sum(Transaction.base_amount),
                func.count(),
            )
            .select_from(Transaction)
            .outerjoin(Category, Category.id == Transaction.category_id)
            .where(*_range_filters(household, start, end, transaction_type))
            .group_by(
                Transaction.category_id,
                Category.name,
                Category.category_type,
                Transaction.transaction_type,
            )
        )
    ).all()

    totals: dict[str, Decimal] = defaultdict(Decimal)
    items: list[CategoryStatItem] = []
    for category_id, name, item_type, total, count in rows:
        amount = quantize_money(total or Decimal("0"))
        type_name = str(item_type)
        totals[type_name] += amount
        items.append(
            CategoryStatItem(
                category_id=category_id,
                category_name=str(name) if name else UNCATEGORIZED_NAME,
                category_type=type_name,
                amount=amount,
                percentage=Decimal("0.00"),
                transaction_count=int(count),
            )
        )

    for item in items:
        type_total = totals[item.category_type]
        item.percentage = (
            quantize_amount(item.amount * Decimal("100") / type_total, 2)
            if type_total
            else Decimal("0.00")
        )
    items.sort(key=lambda item: (-item.amount, item.category_type, item.category_name))

    statistics = CategoryStatistics(
        start_date=start,
        end_date=end,
        base_currency=str(household.base_currency).strip(),
        income_total=quantize_money(totals[TransactionType.INCOME.value]),
        expense_total=quantize_money(totals[TransactionType.EXPENSE.value]),
        items=items,
    )
    return statistics.model_dump(mode="json")


async def monthly_statistics(
    session: AsyncSession,
    household: Household,
    start_date: date | None = None,
    end_date: date | None = None,
    granularity: MonthlyGranularity = "month",
) -> dict[str, Any]:
    start, end = _resolve_range(household, start_date, end_date, yearly=True)
    period = _period_expression(household, granularity)
    rows = (
        await session.execute(
            select(
                period,
                Transaction.transaction_type,
                func.sum(Transaction.base_amount),
                func.count(),
            )
            .where(*_range_filters(household, start, end))
            .group_by(period, Transaction.transaction_type)
        )
    ).all()
    income, expense, income_count, expense_count = _aggregate_periods(rows)

    items: list[PeriodStatisticsItem] = []
    income_total = Decimal("0")
    expense_total = Decimal("0")
    for label in _iter_periods(start, end, granularity):
        period_income = quantize_money(income[label])
        period_expense = quantize_money(expense[label])
        income_total += period_income
        expense_total += period_expense
        items.append(
            PeriodStatisticsItem(
                period=label,
                income=period_income,
                expense=period_expense,
                net=quantize_money(period_income - period_expense),
                income_count=income_count[label],
                expense_count=expense_count[label],
                transaction_count=income_count[label] + expense_count[label],
            )
        )

    statistics = MonthlyStatistics(
        start_date=start,
        end_date=end,
        base_currency=str(household.base_currency).strip(),
        granularity=granularity,
        income_total=quantize_money(income_total),
        expense_total=quantize_money(expense_total),
        net_total=quantize_money(income_total - expense_total),
        items=items,
    )
    return statistics.model_dump(mode="json")


async def cashflow(
    session: AsyncSession,
    household: Household,
    start_date: date | None = None,
    end_date: date | None = None,
    granularity: Granularity = "day",
) -> dict[str, Any]:
    start, end = _resolve_range(household, start_date, end_date)
    periods = _iter_periods(start, end, granularity)
    if len(periods) > MAX_CASHFLOW_BUCKETS:
        raise AppError(
            f"cashflow range produces more than {MAX_CASHFLOW_BUCKETS} periods; "
            "narrow the date range or use a coarser granularity",
            status_code=400,
            error_code="DATE_RANGE_TOO_LARGE",
        )

    period = _period_expression(household, granularity)
    rows = (
        await session.execute(
            select(
                period,
                Transaction.transaction_type,
                func.sum(Transaction.base_amount),
                func.count(),
            )
            .where(*_range_filters(household, start, end))
            .group_by(period, Transaction.transaction_type)
        )
    ).all()
    income, expense, income_count, expense_count = _aggregate_periods(rows)

    items: list[CashflowItem] = []
    income_total = Decimal("0")
    expense_total = Decimal("0")
    cumulative = Decimal("0")
    for label in periods:
        period_income = quantize_money(income[label])
        period_expense = quantize_money(expense[label])
        net = quantize_money(period_income - period_expense)
        income_total += period_income
        expense_total += period_expense
        cumulative += net
        items.append(
            CashflowItem(
                period=label,
                income=period_income,
                expense=period_expense,
                net=net,
                income_count=income_count[label],
                expense_count=expense_count[label],
                transaction_count=income_count[label] + expense_count[label],
                cumulative_net=quantize_money(cumulative),
            )
        )

    statistics = CashflowStatistics(
        start_date=start,
        end_date=end,
        base_currency=str(household.base_currency).strip(),
        granularity=granularity,
        income_total=quantize_money(income_total),
        expense_total=quantize_money(expense_total),
        net_total=quantize_money(income_total - expense_total),
        items=items,
    )
    return statistics.model_dump(mode="json")
