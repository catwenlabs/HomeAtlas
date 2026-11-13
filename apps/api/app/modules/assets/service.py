"""Net worth summary, daily snapshots, and monthly aggregation (2C-1).

Implements the asset-design 5.2 net worth formula with the investment and
loan terms pinned to zero (they arrive in 2C-2 / 2C-3): cash keeps the
positive balances of non-investment accounts, investment account balances
count at book value, credit overdrafts become liabilities.
"""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AccountType
from app.core.money import quantize_money
from app.core.pagination import Pagination, resolve_sort
from app.core.serialization import jsonable
from app.modules.accounts.models import Account
from app.modules.accounts.service import get_household_book_balances
from app.modules.assets.models import NetWorthSnapshot
from app.modules.audit.service import write_audit
from app.modules.exchange_rates.service import resolve_rates_to_base
from app.modules.households.models import Household

DAYS_PER_YEAR = Decimal("365")

_SORTABLE = {
    "snapshot_date": NetWorthSnapshot.snapshot_date,
    "created_at": NetWorthSnapshot.created_at,
}


def _household_today(household: Household) -> date:
    return datetime.now(ZoneInfo(str(household.timezone).strip())).date()


def _convert(amounts: dict[str, Decimal], rates: dict[str, Decimal]) -> Decimal:
    return quantize_money(
        sum(
            (amount * rates.get(currency, Decimal("1")) for currency, amount in amounts.items()),
            Decimal("0"),
        )
    )


async def _compute_metrics(
    session: AsyncSession, household: Household, as_of: date
) -> dict[str, Any]:
    base = str(household.base_currency).strip()
    book = await get_household_book_balances(session, household.id)
    accounts = {
        account.id: account
        for account in (
            await session.scalars(select(Account).where(Account.household_id == household.id))
        ).all()
    }

    cash: dict[str, Decimal] = defaultdict(Decimal)
    invested: dict[str, Decimal] = defaultdict(Decimal)
    liabilities: dict[str, Decimal] = defaultdict(Decimal)
    interest_income: dict[str, Decimal] = defaultdict(Decimal)
    inactive_count = 0

    for account_id, balances in book.items():
        account = accounts.get(account_id)
        if account is None:
            continue
        if not account.is_active:
            inactive_count += 1
        is_investment = str(account.account_type).strip() == AccountType.INVESTMENT.value
        for currency, balance in balances.items():
            if is_investment:
                invested[currency] += balance
            elif balance >= 0:
                cash[currency] += balance
            else:
                liabilities[currency] += -balance
        if not is_investment and account.annual_rate is not None:
            # Decision: interest accrues on the account's own currency only.
            own_balance = balances.get(str(account.currency).strip(), Decimal("0"))
            if own_balance > 0:
                interest_income[str(account.currency).strip()] += (
                    own_balance * account.annual_rate / DAYS_PER_YEAR
                )

    currencies = set(cash) | set(invested) | set(liabilities) | set(interest_income)
    rates = await resolve_rates_to_base(session, household.id, base, currencies, as_of)

    total_cash = _convert(cash, rates)
    total_invested = _convert(invested, rates)
    total_liabilities = _convert(liabilities, rates)
    net_worth = quantize_money(total_cash + total_invested - total_liabilities)

    breakdown = []
    for currency in sorted(currencies):
        breakdown.append(
            {
                "currency": currency,
                "cash": quantize_money(cash.get(currency, Decimal("0"))),
                "invested": quantize_money(invested.get(currency, Decimal("0"))),
                "liabilities": quantize_money(liabilities.get(currency, Decimal("0"))),
                "fx_rate": rates.get(currency, Decimal("1")),
            }
        )

    return {
        "base_currency": base,
        "total_cash": total_cash,
        "total_invested": total_invested,
        "total_liabilities": total_liabilities,
        "net_worth": net_worth,
        # 2C-2/2C-3 terms; fixed until investments and loans exist.
        "unrealized_pnl": quantize_money(Decimal("0")),
        "unmapped_cash": total_invested,
        "daily_interest_income": _convert(interest_income, rates),
        "daily_interest_expense": quantize_money(Decimal("0")),
        "inactive_count": inactive_count,
        "currency_breakdown": breakdown,
        "fx_rates_used": rates,
    }


async def build_summary(session: AsyncSession, household: Household) -> dict[str, Any]:
    metrics = await _compute_metrics(session, household, _household_today(household))
    return {
        "base_currency": metrics["base_currency"],
        "net_worth": metrics["net_worth"],
        "buckets": {
            "idle": metrics["total_cash"],
            "invested": metrics["total_invested"],
            "matured": quantize_money(Decimal("0")),
        },
        "total_liabilities": metrics["total_liabilities"],
        "unrealized_pnl": metrics["unrealized_pnl"],
        "unmapped_cash": metrics["unmapped_cash"],
        "daily_interest_income": metrics["daily_interest_income"],
        "daily_interest_expense": metrics["daily_interest_expense"],
        "inactive_count": metrics["inactive_count"],
        "matured_investments": [],
        "currency_breakdown": metrics["currency_breakdown"],
        "fx_rates_used": metrics["fx_rates_used"],
    }


async def create_snapshot(
    session: AsyncSession, household: Household
) -> tuple[NetWorthSnapshot, bool]:
    """Upsert today's snapshot (household timezone). Returns (row, created)."""
    snapshot_date = _household_today(household)
    metrics = await _compute_metrics(session, household, snapshot_date)
    rates_used = {currency: str(rate) for currency, rate in metrics["fx_rates_used"].items()}
    values = {
        "household_id": household.id,
        "snapshot_date": snapshot_date,
        "base_currency": metrics["base_currency"],
        "total_cash": metrics["total_cash"],
        "total_invested": metrics["total_invested"],
        "total_liabilities": metrics["total_liabilities"],
        "net_worth": metrics["net_worth"],
        "unrealized_pnl": metrics["unrealized_pnl"],
        "unmapped_cash": metrics["unmapped_cash"],
        "daily_interest_income": metrics["daily_interest_income"],
        "daily_interest_expense": metrics["daily_interest_expense"],
        "currency_breakdown": jsonable(metrics["currency_breakdown"]),
        "fx_rates_used": rates_used,
    }

    existing = await session.scalar(
        select(NetWorthSnapshot).where(
            NetWorthSnapshot.household_id == household.id,
            NetWorthSnapshot.snapshot_date == snapshot_date,
        )
    )
    if existing is not None:
        for column, value in values.items():
            setattr(existing, column, value)
        snapshot = existing
        created = False
        action = "net_worth.snapshot.update"
    else:
        snapshot = NetWorthSnapshot(**values)
        session.add(snapshot)
        created = True
        action = "net_worth.snapshot.create"
    await session.flush()
    write_audit(
        session,
        household_id=household.id,
        action=action,
        entity_type="net_worth_snapshot",
        entity_id=snapshot.id,
        after={
            "snapshot_date": snapshot_date.isoformat(),
            "net_worth": str(snapshot.net_worth),
        },
    )
    await session.commit()
    await session.refresh(snapshot)
    return snapshot, created


async def list_snapshots(
    session: AsyncSession,
    household_id: UUID,
    pagination: Pagination,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[NetWorthSnapshot], int]:
    filters = [NetWorthSnapshot.household_id == household_id]
    if date_from is not None:
        filters.append(NetWorthSnapshot.snapshot_date >= date_from)
    if date_to is not None:
        filters.append(NetWorthSnapshot.snapshot_date <= date_to)
    total = (
        await session.scalar(select(func.count()).select_from(NetWorthSnapshot).where(*filters))
        or 0
    )
    column, descending = resolve_sort(
        pagination.sort_by, pagination.sort_order, _SORTABLE, "snapshot_date"
    )
    stmt = (
        select(NetWorthSnapshot)
        .where(*filters)
        .order_by(column.desc() if descending else column.asc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return list((await session.scalars(stmt)).all()), int(total)


async def monthly_summary(session: AsyncSession, household_id: UUID, year: int) -> dict[str, Any]:
    snapshots = list(
        (
            await session.scalars(
                select(NetWorthSnapshot)
                .where(
                    NetWorthSnapshot.household_id == household_id,
                    NetWorthSnapshot.snapshot_date >= date(year, 1, 1),
                    NetWorthSnapshot.snapshot_date <= date(year, 12, 31),
                )
                .order_by(NetWorthSnapshot.snapshot_date.asc())
            )
        ).all()
    )
    by_month: dict[str, list[NetWorthSnapshot]] = {}
    for snapshot in snapshots:
        by_month.setdefault(snapshot.snapshot_date.strftime("%Y-%m"), []).append(snapshot)

    months = []
    for month in sorted(by_month):
        rows = by_month[month]
        first, last = rows[0], rows[-1]
        months.append(
            {
                "month": month,
                "snapshot_count": len(rows),
                "net_worth_start": quantize_money(first.net_worth),
                "net_worth_end": quantize_money(last.net_worth),
                "net_change": quantize_money(last.net_worth - first.net_worth),
                "daily_interest_income": quantize_money(
                    sum((row.daily_interest_income for row in rows), Decimal("0"))
                ),
                "daily_interest_expense": quantize_money(
                    sum((row.daily_interest_expense for row in rows), Decimal("0"))
                ),
            }
        )
    return {"year": year, "months": months}
