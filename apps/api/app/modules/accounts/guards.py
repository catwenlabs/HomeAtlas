"""Withdrawal guard shared by transactions, transfers, and imports.

Single source of truth for the negative-balance rule (spec 5.4) and the
credit-account extension (asset-design 5.1): non-credit accounts reject any
overdraft with INSUFFICIENT_BALANCE, credit accounts allow a negative balance
up to credit_limit (NULL limit = no check).
"""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AccountType
from app.core.exceptions import AppError
from app.modules.accounts.models import Account
from app.modules.accounts.service import get_account_currency_balance


def withdrawal_violation(
    balance: Decimal,
    decrease: Decimal,
    *,
    account_type: str,
    credit_limit: Decimal | None,
) -> str | None:
    """Return the error_code violated by this withdrawal, or None."""
    new_balance = balance - decrease
    if account_type != AccountType.CREDIT.value:
        if new_balance < 0:
            return "INSUFFICIENT_BALANCE"
        return None
    if credit_limit is not None and -new_balance > credit_limit:
        return "CREDIT_LIMIT_EXCEEDED"
    return None


async def ensure_withdrawable(
    session: AsyncSession,
    *,
    account: Account,
    currency: str,
    decrease: Decimal,
) -> None:
    """Raise when the account cannot absorb this withdrawal."""
    balance = await get_account_currency_balance(session, account.id, currency)
    account_type = str(account.account_type).strip()
    code = withdrawal_violation(
        balance,
        decrease,
        account_type=account_type,
        credit_limit=account.credit_limit,
    )
    if code is None:
        return
    if code == "CREDIT_LIMIT_EXCEEDED":
        raise AppError(
            f"Credit limit exceeded: limit {account.credit_limit}, "
            f"balance {balance}, required {decrease}",
            status_code=409,
            error_code=code,
        )
    raise AppError(
        f"Insufficient {currency} balance: available {balance}, required {decrease}",
        status_code=409,
        error_code=code,
    )
