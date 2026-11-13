"""Net worth summary, daily snapshots, and monthly aggregation (2C-1).

Implements the asset-design 5.2 net worth formula with the investment and
loan terms pinned to zero (they arrive in 2C-2 / 2C-3): cash keeps the
positive balances of non-investment accounts, investment account balances
count at book value, credit overdrafts become liabilities.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AccountType, InvestmentStatus
from app.core.money import daily_interest, quantize_money
from app.core.pagination import Pagination, resolve_sort
from app.core.serialization import jsonable
from app.modules.accounts.models import Account
from app.modules.accounts.service import get_household_book_balances
from app.modules.assets.models import NetWorthSnapshot
from app.modules.audit.service import write_audit
from app.modules.exchange_rates.service import resolve_rates_to_base
from app.modules.households.models import Household
from app.modules.households.service import household_today
from app.modules.investments.models import Investment
from app.modules.loans.service import active_loan_interest, active_loan_liabilities

_SORTABLE = {
    "snapshot_date": NetWorthSnapshot.snapshot_date,
    "created_at": NetWorthSnapshot.created_at,
}


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
    investment_account_balances: dict[str, Decimal] = defaultdict(Decimal)
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
                investment_account_balances[currency] += balance
            elif balance >= 0:
                cash[currency] += balance
            else:
                liabilities[currency] += -balance
        if not is_investment and account.annual_rate is not None:
            # Decision: interest accrues on the account's own currency only.
            own_balance = balances.get(str(account.currency).strip(), Decimal("0"))
            if own_balance > 0:
                interest_income[str(account.currency).strip()] += daily_interest(
                    own_balance, account.annual_rate
                )

    # Every investment sits on an investment account, so the account balance
    # already includes principal. Net worth adds only the floating PnL
    # (current_value - principal). Matured rows stay in net worth but move
    # to the matured bucket for display.
    investments = list(
        (
            await session.scalars(
                select(Investment).where(
                    Investment.household_id == household.id,
                    Investment.status != InvestmentStatus.REDEEMED.value,
                )
            )
        ).all()
    )
    invested_bucket: dict[str, Decimal] = defaultdict(Decimal)
    matured_bucket: dict[str, Decimal] = defaultdict(Decimal)
    managed_pnl: dict[str, Decimal] = defaultdict(Decimal)
    managed_principal: dict[str, Decimal] = defaultdict(Decimal)
    matured_list: list[dict[str, Any]] = []
    for investment in investments:
        currency = str(investment.currency).strip()
        measure = investment.principal
        end_date = investment.end_date
        matured = end_date is not None and end_date <= as_of
        if matured:
            matured_bucket[currency] += measure
            matured_list.append(
                {
                    "id": str(investment.id),
                    "name": investment.name,
                    "end_date": end_date.isoformat() if end_date else None,
                    "current_value": str(investment.current_value),
                    "currency": currency,
                }
            )
        else:
            invested_bucket[currency] += measure
        managed_pnl[currency] += investment.current_value - investment.principal
        managed_principal[currency] += investment.principal
        if investment.annual_rate is not None:
            interest_income[currency] += daily_interest(
                investment.current_value, investment.annual_rate
            )

    # Loan side (2C-3): active loans add their remaining principal to the
    # liabilities and their accrued daily interest to the expense estimate.
    loan_liabilities = await active_loan_liabilities(session, household.id)
    for currency, amount in loan_liabilities.items():
        liabilities[currency] += amount
    loan_interest = await active_loan_interest(session, household.id)

    currencies = (
        set(cash)
        | set(investment_account_balances)
        | set(invested_bucket)
        | set(matured_bucket)
        | set(managed_pnl)
        | set(liabilities)
        | set(loan_interest)
        | set(interest_income)
    )
    rates = await resolve_rates_to_base(session, household.id, base, currencies, as_of)

    total_cash = _convert(cash, rates)
    total_invested_accounts = _convert(investment_account_balances, rates)
    total_invested = _convert(invested_bucket, rates)
    total_matured = _convert(matured_bucket, rates)
    total_liabilities = _convert(liabilities, rates)
    total_managed_pnl = _convert(managed_pnl, rates)
    net_worth = quantize_money(
        total_cash + total_invested_accounts + total_managed_pnl - total_liabilities
    )
    unmapped_cash = quantize_money(total_invested_accounts - _convert(managed_principal, rates))

    breakdown = []
    for currency in sorted(currencies):
        bucket_measure = invested_bucket.get(currency, Decimal("0")) + matured_bucket.get(
            currency, Decimal("0")
        )
        breakdown.append(
            {
                "currency": currency,
                "cash": quantize_money(cash.get(currency, Decimal("0"))),
                "invested": quantize_money(bucket_measure),
                "liabilities": quantize_money(liabilities.get(currency, Decimal("0"))),
                "fx_rate": rates.get(currency, Decimal("1")),
            }
        )

    return {
        "base_currency": base,
        "total_cash": total_cash,
        "total_invested": total_invested,
        "total_matured": total_matured,
        "total_liabilities": total_liabilities,
        "net_worth": net_worth,
        "unrealized_pnl": total_managed_pnl,
        "unmapped_cash": unmapped_cash,
        "daily_interest_income": _convert(interest_income, rates),
        "daily_interest_expense": _convert(loan_interest, rates),
        "inactive_count": inactive_count,
        "matured_investments": matured_list,
        "currency_breakdown": breakdown,
        "fx_rates_used": rates,
    }


async def build_summary(session: AsyncSession, household: Household) -> dict[str, Any]:
    metrics = await _compute_metrics(session, household, household_today(household))
    return {
        "base_currency": metrics["base_currency"],
        "net_worth": metrics["net_worth"],
        "buckets": {
            "idle": metrics["total_cash"],
            "invested": metrics["total_invested"],
            "matured": metrics["total_matured"],
        },
        "total_liabilities": metrics["total_liabilities"],
        "unrealized_pnl": metrics["unrealized_pnl"],
        "unmapped_cash": metrics["unmapped_cash"],
        "daily_interest_income": metrics["daily_interest_income"],
        "daily_interest_expense": metrics["daily_interest_expense"],
        "inactive_count": metrics["inactive_count"],
        "matured_investments": metrics["matured_investments"],
        "currency_breakdown": metrics["currency_breakdown"],
        "fx_rates_used": metrics["fx_rates_used"],
    }


async def create_snapshot(
    session: AsyncSession, household: Household
) -> tuple[NetWorthSnapshot, bool]:
    """Upsert today's snapshot (household timezone). Returns (row, created)."""
    snapshot_date = household_today(household)
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
