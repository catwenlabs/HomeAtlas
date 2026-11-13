"""Investment fund and redeem flows (asset-design section 5.2).

Both flows compose the no-commit transfer kernel from transfers.service so
the transfer, its derived rows, the link row, and the investment mutation
land in ONE transaction. Redeem follows the fixed C1 order: derived PnL
row first (so the investment account balance equals the proceeds), then
the transfer whose balance guard therefore passes.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    CategoryType,
    InvestmentLinkDirection,
    InvestmentStatus,
    TransactionSource,
    TransactionStatus,
    TransactionType,
)
from app.core.exceptions import AppError
from app.core.money import quantize_amount, quantize_money
from app.modules.accounts.guards import ensure_withdrawable
from app.modules.accounts.service import get_account
from app.modules.audit.service import write_audit
from app.modules.categories.defaults import INVESTMENT_INCOME_NAME, INVESTMENT_LOSS_NAME
from app.modules.categories.models import Category
from app.modules.currencies.service import get_currency
from app.modules.exchange_rates.service import EXCHANGE_RATE_PLACES, resolve_rate
from app.modules.households.models import Household
from app.modules.households.service import household_today
from app.modules.investments.models import Investment, InvestmentTransfer
from app.modules.investments.schemas import FundTransferSpec, InvestmentRedeem
from app.modules.transactions.models import Transaction
from app.modules.transfers import service as transfers_service


def ensure_managed(investment: Investment) -> UUID:
    if investment.account_id is None:
        raise AppError(
            "This action requires a managed investment (one with an investment account)",
            status_code=409,
            error_code="INVESTMENT_ACCOUNT_REQUIRED",
        )
    return investment.account_id


def ensure_active(investment: Investment) -> None:
    if investment.status != InvestmentStatus.ACTIVE.value:
        raise AppError(
            "Investment is already redeemed",
            status_code=409,
            error_code="INVESTMENT_ALREADY_REDEEMED",
        )


async def _investment_category(
    session: AsyncSession, household_id: UUID, *, profit: bool
) -> Category:
    """Runtime fallback for the built-in PnL categories (design section 7)."""
    name = INVESTMENT_INCOME_NAME if profit else INVESTMENT_LOSS_NAME
    category_type = CategoryType.INCOME.value if profit else CategoryType.EXPENSE.value
    category = await session.scalar(
        select(Category)
        .where(
            Category.household_id == household_id,
            Category.name == name,
            Category.category_type == category_type,
        )
        .order_by(Category.created_at.asc())
        .limit(1)
    )
    if category is None:
        category = Category(
            household_id=household_id,
            name=name,
            category_type=category_type,
            parent_id=None,
            icon="trending-up" if profit else "trending-down",
            sort_order=950 if profit else 951,
            is_active=True,
        )
        session.add(category)
        await session.flush()
    return category


async def execute_fund(
    session: AsyncSession,
    household: Household,
    investment: Investment,
    spec: FundTransferSpec,
) -> None:
    """Move cash into the investment account and grow the principal.

    Caller owns the transaction boundary (no commit here).
    """
    investment_account_id = ensure_managed(investment)
    ensure_active(investment)
    investment_currency = await get_currency(session, str(investment.currency).strip())
    base_currency = await get_currency(session, str(household.base_currency).strip())
    from_account = await get_account(session, household.id, spec.from_account_id)
    from_currency = await get_currency(session, str(from_account.currency).strip())

    if from_currency.code == investment_currency.code:
        if spec.exchange_rate is not None and spec.exchange_rate != Decimal("1"):
            raise AppError(
                "exchange_rate must be 1 when both sides share the currency",
                status_code=400,
                error_code="EXCHANGE_RATE_INVALID",
            )
        to_amount = quantize_amount(spec.from_amount, investment_currency.decimal_places)
    else:
        if spec.exchange_rate is None:
            raise AppError(
                "exchange_rate is required when the funding account currency "
                "differs from the investment currency",
                status_code=400,
                error_code="EXCHANGE_RATE_REQUIRED",
            )
        to_amount = quantize_amount(
            spec.from_amount * spec.exchange_rate, investment_currency.decimal_places
        )

    # Neither side in the household base currency: fix the base value with
    # the household's own rate table (missing rate -> explicit 400).
    base_exchange_rate: Decimal | None = None
    if from_currency.code != base_currency.code and investment_currency.code != base_currency.code:
        base_exchange_rate = await resolve_rate(
            session,
            household.id,
            from_currency.code,
            base_currency.code,
            household_today(household),
        )
        if base_exchange_rate is None:
            raise AppError(
                f"Missing exchange rate for {from_currency.code}/{base_currency.code}",
                status_code=400,
                error_code="EXCHANGE_RATE_NOT_FOUND",
                details={"missing": [f"{from_currency.code}/{base_currency.code}"]},
            )

    terms = await transfers_service.resolve_terms(
        session,
        household,
        from_account_id=spec.from_account_id,
        to_account_id=investment_account_id,
        from_amount=spec.from_amount,
        from_currency=from_currency.code,
        to_amount=to_amount,
        to_currency=investment_currency.code,
        exchange_rate=spec.exchange_rate,
        base_exchange_rate=base_exchange_rate,
        fee=Decimal("0"),
        fee_currency=None,
        fee_exchange_rate=None,
    )
    transfer = await transfers_service.persist_transfer(
        session,
        household,
        terms,
        description=f"Investment fund for {investment.id}",
        occurred_at=datetime.now(UTC),
        status=TransactionStatus.CONFIRMED,
    )
    session.add(
        InvestmentTransfer(
            investment_id=investment.id,
            transfer_id=transfer.id,
            direction=InvestmentLinkDirection.FUND.value,
        )
    )
    investment.principal = quantize_money(investment.principal + terms.to_amount)
    # Fresh principal is also the best first estimate of value until the
    # user (or a quote refresh) says otherwise.
    if investment.current_value == Decimal("0"):
        investment.current_value = investment.principal
    await session.flush()
    write_audit(
        session,
        household_id=household.id,
        action="investment.fund",
        entity_type="investment",
        entity_id=investment.id,
        after={
            "transfer_id": str(transfer.id),
            "to_amount": str(terms.to_amount),
            "principal": str(investment.principal),
        },
    )


async def execute_redeem(
    session: AsyncSession,
    household: Household,
    investment: Investment,
    payload: InvestmentRedeem,
) -> dict[str, Any]:
    """Full redemption with the fixed C1 ordering (design section 5.2).

    Caller owns the transaction boundary (no commit here).
    """
    ensure_active(investment)
    investment_account_id = ensure_managed(investment)
    investment_currency = await get_currency(session, str(investment.currency).strip())
    base_currency = await get_currency(session, str(household.base_currency).strip())

    to_amount = quantize_amount(payload.to_amount, investment_currency.decimal_places)
    if to_amount <= 0:
        raise AppError(
            "to_amount must be positive after currency rounding",
            status_code=422,
            error_code="REDEEM_AMOUNT_INVALID",
        )
    to_account = await get_account(session, household.id, payload.to_account_id)
    if not to_account.is_active:
        raise AppError(
            "Account is inactive",
            status_code=409,
            error_code="ACCOUNT_INACTIVE",
        )
    if str(to_account.currency).strip() != investment_currency.code:
        raise AppError(
            "The redeem target account must use the investment currency "
            "(cross-currency redeem arrives later)",
            status_code=422,
            error_code="REDEEM_AMOUNT_INVALID",
        )

    today = household_today(household)
    base_rate: Decimal
    if investment_currency.code == base_currency.code:
        base_rate = Decimal("1")
    elif payload.exchange_rate is not None:
        base_rate = quantize_amount(payload.exchange_rate, EXCHANGE_RATE_PLACES)
    else:
        resolved = await resolve_rate(
            session, household.id, investment_currency.code, base_currency.code, today
        )
        if resolved is None:
            raise AppError(
                f"Missing exchange rate for {investment_currency.code}/{base_currency.code}",
                status_code=400,
                error_code="EXCHANGE_RATE_NOT_FOUND",
                details={"missing": [f"{investment_currency.code}/{base_currency.code}"]},
            )
        base_rate = resolved

    pnl = quantize_money(to_amount - investment.principal)
    occurred_at = datetime.now(UTC)

    # 1. Derived PnL row lands on the investment account FIRST, so the
    #    account balance becomes principal + pnl == to_amount and the
    #    transfer guard below passes naturally. transfer_id is attached
    #    once the transfer row exists (FK satisfied at commit time).
    pnl_transaction: Transaction | None = None
    if pnl != Decimal("0"):
        profit = pnl > Decimal("0")
        if not profit:
            # The derived loss row is a withdrawal like any other: it must
            # pass the shared 5.1 guard before anything is written. Without
            # this, a drifted investment-account balance would go negative
            # mid-flow and only surface as a confusing transfer error.
            investment_account = await get_account(session, household.id, investment_account_id)
            await ensure_withdrawable(
                session,
                account=investment_account,
                currency=investment_currency.code,
                decrease=abs(pnl),
            )
        category = await _investment_category(session, household.id, profit=profit)
        pnl_transaction = Transaction(
            household_id=household.id,
            account_id=investment_account_id,
            category_id=category.id,
            transaction_type=(
                TransactionType.INCOME.value if profit else TransactionType.EXPENSE.value
            ),
            amount=abs(pnl),
            currency=investment_currency.code,
            base_amount=quantize_money(abs(pnl) * base_rate),
            base_currency=base_currency.code,
            exchange_rate=base_rate,
            exchange_rate_date=today,
            transaction_date=occurred_at,
            description=f"Investment redeem PnL for {investment.name} ({investment.id})",
            source=TransactionSource.SYSTEM.value,
            status=TransactionStatus.CONFIRMED.value,
        )
        session.add(pnl_transaction)
        await session.flush()
        write_audit(
            session,
            household_id=household.id,
            action="transaction.create",
            entity_type="transaction",
            entity_id=pnl_transaction.id,
            after={
                "transaction_type": pnl_transaction.transaction_type,
                "amount": str(pnl_transaction.amount),
                "investment_id": str(investment.id),
                "note": "redeem pnl",
            },
        )

    # 2. Transfer the proceeds back to the cash account.
    terms = await transfers_service.resolve_terms(
        session,
        household,
        from_account_id=investment_account_id,
        to_account_id=to_account.id,
        from_amount=to_amount,
        from_currency=investment_currency.code,
        to_amount=to_amount,
        to_currency=investment_currency.code,
        exchange_rate=None,
        base_exchange_rate=(None if investment_currency.code == base_currency.code else base_rate),
        fee=Decimal("0"),
        fee_currency=None,
        fee_exchange_rate=None,
    )
    transfer = await transfers_service.persist_transfer(
        session,
        household,
        terms,
        description=f"Investment redeem for {investment.id}",
        occurred_at=occurred_at,
        status=TransactionStatus.CONFIRMED,
    )
    if pnl_transaction is not None:
        pnl_transaction.transfer_id = transfer.id
        await session.flush()

    # 3. Terminal state with a pre-redeem snapshot for reversal rollback.
    investment.pre_redeem_value = investment.current_value
    investment.current_value = Decimal("0")
    investment.realized_pnl = pnl
    investment.status = InvestmentStatus.REDEEMED.value
    session.add(
        InvestmentTransfer(
            investment_id=investment.id,
            transfer_id=transfer.id,
            direction=InvestmentLinkDirection.REDEEM.value,
        )
    )
    await session.flush()
    write_audit(
        session,
        household_id=household.id,
        action="investment.redeem",
        entity_type="investment",
        entity_id=investment.id,
        after={
            "transfer_id": str(transfer.id),
            "to_amount": str(to_amount),
            "realized_pnl": str(pnl),
            "pre_redeem_value": str(investment.pre_redeem_value),
        },
    )
    return {
        "investment": investment,
        "transfer_id": transfer.id,
        "realized_pnl": pnl,
    }
