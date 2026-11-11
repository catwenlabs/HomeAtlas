"""Transaction use cases: opening balances, income/expense lifecycle, reversal."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import TransactionSource, TransactionStatus, TransactionType
from app.core.exceptions import AppError, NotFoundError
from app.core.money import quantize_amount, quantize_money
from app.core.pagination import Pagination, resolve_sort
from app.modules.accounts.models import Account
from app.modules.accounts.service import (
    get_account,
    get_account_currency_balance,
)
from app.modules.audit.service import write_audit
from app.modules.categories.models import Category
from app.modules.currencies.service import get_currency
from app.modules.households.models import Household
from app.modules.transactions.models import Transaction
from app.modules.transactions.schemas import (
    TransactionCreate,
    TransactionRead,
    TransactionReverse,
    TransactionUpdate,
)

OPENING_BALANCE_SOURCE = TransactionSource.MANUAL.value
EXCHANGE_RATE_PLACES = 12

_MANUAL_TYPES = (TransactionType.INCOME.value, TransactionType.EXPENSE.value)
_SORTABLE = {
    "transaction_date": Transaction.transaction_date,
    "amount": Transaction.amount,
    "created_at": Transaction.created_at,
    "updated_at": Transaction.updated_at,
}


def _audit_data(transaction: Transaction) -> dict[str, Any]:
    return {
        "account_id": transaction.account_id,
        "category_id": transaction.category_id,
        "transaction_type": transaction.transaction_type,
        "amount": transaction.amount,
        "currency": transaction.currency,
        "base_amount": transaction.base_amount,
        "base_currency": transaction.base_currency,
        "exchange_rate": transaction.exchange_rate,
        "exchange_rate_date": transaction.exchange_rate_date,
        "transaction_date": transaction.transaction_date,
        "description": transaction.description,
        "external_id": transaction.external_id,
        "status": transaction.status,
        "reverses_transaction_id": transaction.reverses_transaction_id,
        "transfer_id": transaction.transfer_id,
    }


def _transaction_response(transaction: Transaction) -> dict[str, Any]:
    return TransactionRead.model_validate(transaction).model_dump(mode="json")


async def get_transaction(
    session: AsyncSession, household_id: UUID, transaction_id: UUID
) -> Transaction:
    transaction = await session.scalar(
        select(Transaction).where(
            Transaction.id == transaction_id,
            Transaction.household_id == household_id,
        )
    )
    if transaction is None:
        raise NotFoundError("Transaction not found", error_code="TRANSACTION_NOT_FOUND")
    return transaction


async def _resolve_account(session: AsyncSession, household_id: UUID, account_id: UUID) -> Account:
    account = await get_account(session, household_id, account_id)
    if not account.is_active:
        raise AppError(
            "Account is inactive",
            status_code=409,
            error_code="ACCOUNT_INACTIVE",
        )
    return account


async def _resolve_category(
    session: AsyncSession,
    household_id: UUID,
    category_id: UUID,
    transaction_type: str,
) -> Category:
    category = await session.scalar(
        select(Category).where(
            Category.id == category_id,
            Category.household_id == household_id,
        )
    )
    if category is None:
        raise NotFoundError("Category not found", error_code="CATEGORY_NOT_FOUND")
    if not category.is_active:
        raise AppError(
            "Category is inactive",
            status_code=409,
            error_code="CATEGORY_INACTIVE",
        )
    if category.category_type != transaction_type:
        raise AppError(
            "Category type must match the transaction type",
            status_code=400,
            error_code="CATEGORY_TYPE_MISMATCH",
        )
    return category


def _validate_transaction_type(transaction_type: str) -> None:
    if transaction_type not in _MANUAL_TYPES:
        raise AppError(
            "Only income and expense transactions can be created through this endpoint",
            status_code=400,
            error_code="TRANSACTION_TYPE_INVALID",
        )


async def _resolve_amounts(
    session: AsyncSession,
    household: Household,
    *,
    amount: Decimal,
    currency_code: str | None,
    exchange_rate: Decimal | None,
    account: Account,
) -> tuple[str, Decimal, Decimal, str, Decimal]:
    currency = await get_currency(session, currency_code or str(account.currency).strip())
    base_currency = await get_currency(session, str(household.base_currency).strip())

    if currency.code == base_currency.code:
        if exchange_rate is not None and exchange_rate != Decimal("1"):
            raise AppError(
                f"exchange_rate must be 1 for {currency.code} (household base currency)",
                status_code=400,
                error_code="EXCHANGE_RATE_INVALID",
            )
        rate = Decimal("1")
    else:
        if exchange_rate is None:
            raise AppError(
                "exchange_rate is required when the currency differs "
                "from the household base currency",
                status_code=400,
                error_code="EXCHANGE_RATE_REQUIRED",
            )
        rate = exchange_rate

    rate = quantize_amount(rate, EXCHANGE_RATE_PLACES)
    rounded_amount = quantize_amount(amount, currency.decimal_places)
    base_amount = quantize_money(rounded_amount * rate)
    return currency.code, rate, rounded_amount, base_currency.code, base_amount


async def _ensure_sufficient_balance(
    session: AsyncSession,
    *,
    account_id: UUID,
    currency: str,
    decrease: Decimal,
) -> None:
    balance = await get_account_currency_balance(session, account_id, currency)
    if balance - decrease < 0:
        raise AppError(
            f"Insufficient {currency} balance: available {balance}, required {decrease}",
            status_code=409,
            error_code="INSUFFICIENT_BALANCE",
        )


async def set_opening_balance(
    session: AsyncSession,
    account: Account,
    household: Household,
    *,
    amount: Decimal,
    currency_code: str | None,
    exchange_rate: Decimal | None,
    exchange_rate_date: date | None,
    transaction_date: datetime | None,
    description: str | None,
) -> Transaction:
    """Create or replace the opening-balance entry for one account currency.

    Opening balances are confirmed single-sided rows and are explicitly
    modifiable during Phase 1.1 (with an audit record), unlike ordinary
    confirmed transactions.
    """
    currency_code, rate, rounded_amount, base_currency, base_amount = await _resolve_amounts(
        session,
        household,
        amount=amount,
        currency_code=currency_code,
        exchange_rate=exchange_rate,
        account=account,
    )
    occurred_at = transaction_date or datetime.now(UTC)
    rate_date = exchange_rate_date or occurred_at.date()

    existing = await session.scalar(
        select(Transaction)
        .where(
            Transaction.account_id == account.id,
            Transaction.currency == currency_code,
            Transaction.transaction_type == TransactionType.OPENING_BALANCE.value,
        )
        .order_by(Transaction.created_at.asc())
        .limit(1)
    )

    before: dict[str, Any] | None = None
    if existing is None:
        transaction = Transaction(
            household_id=account.household_id,
            account_id=account.id,
            category_id=None,
            transaction_type=TransactionType.OPENING_BALANCE.value,
            amount=rounded_amount,
            currency=currency_code,
            base_amount=base_amount,
            base_currency=base_currency,
            exchange_rate=rate,
            exchange_rate_date=rate_date,
            transaction_date=occurred_at,
            description=description,
            source=OPENING_BALANCE_SOURCE,
            status=TransactionStatus.CONFIRMED.value,
        )
        session.add(transaction)
        action = "opening_balance.set"
    else:
        transaction = existing
        before = _audit_data(transaction)
        transaction.amount = rounded_amount
        transaction.base_amount = base_amount
        transaction.base_currency = base_currency
        transaction.exchange_rate = rate
        transaction.exchange_rate_date = rate_date
        transaction.transaction_date = occurred_at
        transaction.description = description
        transaction.status = TransactionStatus.CONFIRMED.value
        transaction.source = OPENING_BALANCE_SOURCE
        action = "opening_balance.update"

    await session.flush()
    write_audit(
        session,
        household_id=account.household_id,
        action=action,
        entity_type="transaction",
        entity_id=transaction.id,
        before=before,
        after=_audit_data(transaction),
    )
    await session.commit()
    await session.refresh(transaction)
    return transaction


async def create_transaction(
    session: AsyncSession,
    household: Household,
    payload: TransactionCreate,
) -> Transaction:
    _validate_transaction_type(payload.transaction_type.value)
    account = await _resolve_account(session, household.id, payload.account_id)
    category_id = payload.category_id
    if category_id is not None:
        await _resolve_category(session, household.id, category_id, payload.transaction_type.value)

    currency, rate, amount, base_currency, base_amount = await _resolve_amounts(
        session,
        household,
        amount=payload.amount,
        currency_code=payload.currency,
        exchange_rate=payload.exchange_rate,
        account=account,
    )
    status = TransactionStatus(payload.status)
    if (
        status is TransactionStatus.CONFIRMED
        and payload.transaction_type is TransactionType.EXPENSE
    ):
        await _ensure_sufficient_balance(
            session, account_id=account.id, currency=currency, decrease=amount
        )

    occurred_at = payload.transaction_date or datetime.now(UTC)
    transaction = Transaction(
        household_id=household.id,
        account_id=account.id,
        category_id=category_id,
        transaction_type=payload.transaction_type.value,
        amount=amount,
        currency=currency,
        base_amount=base_amount,
        base_currency=base_currency,
        exchange_rate=rate,
        exchange_rate_date=payload.exchange_rate_date or occurred_at.date(),
        transaction_date=occurred_at,
        description=payload.description,
        source=TransactionSource.MANUAL.value,
        external_id=payload.external_id,
        status=status.value,
    )
    session.add(transaction)
    await session.flush()
    write_audit(
        session,
        household_id=household.id,
        action="transaction.create",
        entity_type="transaction",
        entity_id=transaction.id,
        after=_audit_data(transaction),
    )
    await session.commit()
    await session.refresh(transaction)
    return transaction


async def update_transaction(
    session: AsyncSession,
    household: Household,
    transaction_id: UUID,
    payload: TransactionUpdate,
) -> Transaction:
    transaction = await get_transaction(session, household.id, transaction_id)
    if transaction.status != TransactionStatus.DRAFT.value:
        raise AppError(
            "Only draft transactions can be modified",
            status_code=409,
            error_code="TRANSACTION_NOT_EDITABLE",
        )

    changes = payload.model_dump(exclude_unset=True)
    before = _audit_data(transaction)

    transaction_type = str(changes.get("transaction_type", transaction.transaction_type))
    _validate_transaction_type(transaction_type)

    new_status = changes.get("status")
    if new_status is not None:
        new_status = TransactionStatus(new_status).value
    final_status = new_status or transaction.status

    account_id = changes.get("account_id", transaction.account_id)
    account = await _resolve_account(session, household.id, account_id)

    category_id = changes["category_id"] if "category_id" in changes else transaction.category_id
    if category_id is not None:
        await _resolve_category(session, household.id, category_id, transaction_type)

    currency_input = changes.get("currency")
    if currency_input is None and "currency" not in changes:
        currency_input = str(transaction.currency).strip()
    rate_input = changes.get("exchange_rate")
    if "exchange_rate" not in changes:
        rate_input = (
            transaction.exchange_rate
            if currency_input == str(transaction.currency).strip()
            else None
        )
    amount_input = changes["amount"] if "amount" in changes else transaction.amount

    currency, rate, amount, base_currency, base_amount = await _resolve_amounts(
        session,
        household,
        amount=amount_input,
        currency_code=currency_input,
        exchange_rate=rate_input,
        account=account,
    )

    if (
        final_status == TransactionStatus.CONFIRMED.value
        and transaction_type == TransactionType.EXPENSE.value
    ):
        await _ensure_sufficient_balance(
            session, account_id=account.id, currency=currency, decrease=amount
        )

    transaction.account_id = account.id
    transaction.category_id = category_id
    transaction.transaction_type = transaction_type
    transaction.amount = amount
    transaction.currency = currency
    transaction.base_amount = base_amount
    transaction.base_currency = base_currency
    transaction.exchange_rate = rate
    if changes.get("exchange_rate_date") is not None:
        transaction.exchange_rate_date = changes["exchange_rate_date"]
    if changes.get("transaction_date") is not None:
        transaction.transaction_date = changes["transaction_date"]
    if "description" in changes:
        transaction.description = changes["description"]
    if "external_id" in changes:
        transaction.external_id = changes["external_id"]
    transaction.status = final_status

    after = _audit_data(transaction)
    if before != after:
        action = (
            "transaction.confirm"
            if final_status == TransactionStatus.CONFIRMED.value
            and before["status"] == TransactionStatus.DRAFT.value
            else "transaction.update"
        )
        write_audit(
            session,
            household_id=household.id,
            action=action,
            entity_type="transaction",
            entity_id=transaction.id,
            before=before,
            after=after,
        )
    await session.commit()
    await session.refresh(transaction)
    return transaction


async def delete_transaction(
    session: AsyncSession, household: Household, transaction_id: UUID
) -> None:
    transaction = await get_transaction(session, household.id, transaction_id)
    if transaction.status != TransactionStatus.DRAFT.value:
        raise AppError(
            "Only draft transactions can be deleted",
            status_code=409,
            error_code="TRANSACTION_NOT_DELETABLE",
        )
    write_audit(
        session,
        household_id=household.id,
        action="transaction.delete",
        entity_type="transaction",
        entity_id=transaction.id,
        before=_audit_data(transaction),
    )
    await session.delete(transaction)
    await session.commit()


async def reverse_transaction(
    session: AsyncSession,
    household: Household,
    transaction_id: UUID,
    payload: TransactionReverse,
) -> Transaction:
    original = await get_transaction(session, household.id, transaction_id)
    if original.status != TransactionStatus.CONFIRMED.value:
        raise AppError(
            "Only confirmed transactions can be reversed",
            status_code=409,
            error_code="TRANSACTION_NOT_REVERSIBLE",
        )
    if original.transaction_type not in _MANUAL_TYPES:
        raise AppError(
            "Opening-balance transactions cannot be reversed here",
            status_code=409,
            error_code="TRANSACTION_NOT_REVERSIBLE",
        )
    if original.transfer_id is not None:
        raise AppError(
            "Transfer-derived transactions must be reversed with their transfer",
            status_code=409,
            error_code="TRANSACTION_LINKED_TO_TRANSFER",
        )

    reversed_type = (
        TransactionType.EXPENSE.value
        if original.transaction_type == TransactionType.INCOME.value
        else TransactionType.INCOME.value
    )
    if reversed_type == TransactionType.EXPENSE.value:
        await _ensure_sufficient_balance(
            session,
            account_id=original.account_id,
            currency=str(original.currency).strip(),
            decrease=original.amount,
        )

    before = _audit_data(original)
    original.status = TransactionStatus.REVERSED.value
    occurred_at = payload.transaction_date or datetime.now(UTC)
    reversal = Transaction(
        household_id=household.id,
        account_id=original.account_id,
        category_id=original.category_id,
        transaction_type=reversed_type,
        amount=original.amount,
        currency=str(original.currency).strip(),
        base_amount=original.base_amount,
        base_currency=str(original.base_currency).strip(),
        exchange_rate=original.exchange_rate,
        exchange_rate_date=original.exchange_rate_date,
        transaction_date=occurred_at,
        description=payload.description or f"Reversal of transaction {original.id}",
        source=TransactionSource.SYSTEM.value,
        status=TransactionStatus.CONFIRMED.value,
        reverses_transaction_id=original.id,
    )
    session.add(reversal)
    await session.flush()
    write_audit(
        session,
        household_id=household.id,
        action="transaction.reverse",
        entity_type="transaction",
        entity_id=original.id,
        before=before,
        after={
            "status": original.status,
            "reversal_id": reversal.id,
            "reversal": _audit_data(reversal),
        },
    )
    await session.commit()
    await session.refresh(reversal)
    return reversal


async def list_transactions(
    session: AsyncSession,
    household: Household,
    pagination: Pagination,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    account_id: UUID | None = None,
    category_id: UUID | None = None,
    transaction_type: TransactionType | None = None,
    currency: str | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    keyword: str | None = None,
    status: TransactionStatus | None = None,
) -> tuple[list[Transaction], int]:
    filters = [Transaction.household_id == household.id]
    tz = ZoneInfo(household.timezone)
    if start_date is not None:
        filters.append(
            Transaction.transaction_date >= datetime.combine(start_date, time.min, tzinfo=tz)
        )
    if end_date is not None:
        filters.append(
            Transaction.transaction_date
            < datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=tz)
        )
    if account_id is not None:
        filters.append(Transaction.account_id == account_id)
    if category_id is not None:
        filters.append(Transaction.category_id == category_id)
    if transaction_type is not None:
        filters.append(Transaction.transaction_type == transaction_type.value)
    if currency is not None:
        filters.append(Transaction.currency == currency.upper())
    if min_amount is not None:
        filters.append(Transaction.amount >= min_amount)
    if max_amount is not None:
        filters.append(Transaction.amount <= max_amount)
    if keyword:
        pattern = f"%{keyword}%"
        filters.append(
            or_(
                Transaction.description.ilike(pattern),
                Transaction.external_id.ilike(pattern),
            )
        )
    if status is not None:
        filters.append(Transaction.status == status.value)

    total = await session.scalar(select(func.count()).select_from(Transaction).where(*filters))
    column, descending = resolve_sort(
        pagination.sort_by, pagination.sort_order, _SORTABLE, "transaction_date"
    )
    stmt = (
        select(Transaction)
        .where(*filters)
        .order_by(column.desc() if descending else column.asc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return list((await session.scalars(stmt)).all()), int(total or 0)


def opening_balance_response(transaction: Transaction) -> dict[str, Any]:
    return _transaction_response(transaction)


def transaction_response(transaction: Transaction) -> dict[str, Any]:
    return _transaction_response(transaction)
