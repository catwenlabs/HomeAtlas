"""Credit-card repayment flow (asset-design section 5.1).

Repayment composes the no-commit transfer kernel from transfers.service so
the transfer (and its derived rows) lands atomically as one ordinary
confirmed, fee-free transfer into the credit account. No schema change:
a repayment is identifiable only by its default description, and reversal
reuses the standard transfer reversal.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AccountType, TransactionStatus
from app.core.exceptions import AppError
from app.modules.accounts.models import Account
from app.modules.accounts.schemas import AccountRepay
from app.modules.accounts.service import get_account, get_account_currency_balance
from app.modules.audit.service import write_audit
from app.modules.currencies.service import get_currency
from app.modules.exchange_rates.service import resolve_rate
from app.modules.households.models import Household
from app.modules.households.service import household_today
from app.modules.transfers import service as transfers_service
from app.modules.transfers.models import Transfer

REPAYMENT_DESCRIPTION = "信用卡还款"


def _ensure_repayable(card: Account) -> None:
    if str(card.account_type).strip() != AccountType.CREDIT.value:
        raise AppError(
            "Only credit accounts can be repaid; use a normal transfer otherwise",
            status_code=400,
            error_code="REPAY_TARGET_NOT_CREDIT",
        )
    if not card.is_active:
        raise AppError(
            "Credit account is inactive",
            status_code=409,
            error_code="ACCOUNT_INACTIVE",
        )


def _ensure_funding_account(card: Account, from_account: Account) -> None:
    if not from_account.is_active:
        raise AppError(
            "Funding account is inactive",
            status_code=409,
            error_code="ACCOUNT_INACTIVE",
        )
    if from_account.id == card.id:
        raise AppError(
            "A credit card cannot repay itself",
            status_code=400,
            error_code="REPAY_SOURCE_SAME",
        )
    if str(from_account.account_type).strip() == AccountType.INVESTMENT.value:
        raise AppError(
            "Investment accounts cannot fund repayments directly",
            status_code=400,
            error_code="REPAY_SOURCE_INVESTMENT",
        )
    if str(from_account.currency).strip() != str(card.currency).strip():
        raise AppError(
            "The funding account must use the credit card currency "
            "(cross-currency repayment uses a normal transfer)",
            status_code=400,
            error_code="REPAY_CURRENCY_MISMATCH",
        )


async def _base_exchange_rate(
    session: AsyncSession, household: Household, currency_code: str
) -> Decimal | None:
    """Fix the base-currency value for a card outside the household base.

    Neither transfer leg touches the household base currency in the
    same-currency repayment case, so resolve_terms would demand an explicit
    base rate; source it from the household rate table instead (missing
    rate -> explicit 400), mirroring the investment fund flow.
    """
    base_code = str(household.base_currency).strip()
    if currency_code == base_code:
        return None
    rate = await resolve_rate(
        session, household.id, currency_code, base_code, household_today(household)
    )
    if rate is None:
        raise AppError(
            f"Missing exchange rate for {currency_code}/{base_code}",
            status_code=400,
            error_code="EXCHANGE_RATE_NOT_FOUND",
            details={"missing": [f"{currency_code}/{base_code}"]},
        )
    return rate


async def execute_repay(
    session: AsyncSession,
    household: Household,
    card: Account,
    payload: AccountRepay,
) -> Transfer:
    """Record one repayment as a confirmed fee-free transfer into the card.

    Caller owns the transaction boundary (no commit here).
    """
    _ensure_repayable(card)
    from_account = await get_account(session, household.id, payload.from_account_id)
    _ensure_funding_account(card, from_account)

    card_currency = await get_currency(session, str(card.currency).strip())
    base_exchange_rate = await _base_exchange_rate(session, household, card_currency.code)

    # Aggregate balance query: capture BEFORE the transfer is flushed, or
    # the in-session row would be double-counted. Audit trail only.
    debt_before = await get_account_currency_balance(session, card.id, card_currency.code)

    terms = await transfers_service.resolve_terms(
        session,
        household,
        from_account_id=from_account.id,
        to_account_id=card.id,
        from_amount=payload.amount,
        from_currency=card_currency.code,
        to_amount=payload.amount,
        to_currency=card_currency.code,
        exchange_rate=None,
        base_exchange_rate=base_exchange_rate,
        fee=Decimal("0"),
        fee_currency=None,
        fee_exchange_rate=None,
    )
    transfer = await transfers_service.persist_transfer(
        session,
        household,
        terms,
        description=payload.description or REPAYMENT_DESCRIPTION,
        occurred_at=payload.transfer_date or datetime.now(UTC),
        status=TransactionStatus.CONFIRMED,
    )
    write_audit(
        session,
        household_id=household.id,
        action="account.repay",
        entity_type="account",
        entity_id=card.id,
        after={
            "transfer_id": str(transfer.id),
            "from_account_id": str(from_account.id),
            "amount": str(terms.to_amount),
            "currency": card_currency.code,
            "balance_before": str(debt_before),
            "balance_after": str(debt_before + terms.to_amount),
        },
    )
    return transfer


async def repay_credit_card(
    session: AsyncSession,
    household: Household,
    account_id: UUID,
    payload: AccountRepay,
) -> Transfer:
    """Load the card and run the repayment flow in one transaction."""
    card = await get_account(session, household.id, account_id)
    transfer = await execute_repay(session, household, card, payload)
    await session.commit()
    await session.refresh(transfer)
    return transfer
