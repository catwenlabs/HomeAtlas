"""Transfer use cases: multi-currency moves, fees, and reversal (spec 4.6, 5.2)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import CategoryType, TransactionSource, TransactionStatus, TransactionType
from app.core.exceptions import AppError, NotFoundError
from app.core.money import quantize_amount, quantize_money
from app.core.pagination import Pagination, resolve_sort
from app.modules.accounts.guards import ensure_withdrawable
from app.modules.accounts.models import Account
from app.modules.accounts.service import get_account
from app.modules.audit.service import write_audit
from app.modules.categories.defaults import FINANCIAL_FEE_NAME
from app.modules.categories.models import Category
from app.modules.currencies.service import get_currency
from app.modules.households.models import Household
from app.modules.investments.linkage import apply_reversal_linkage
from app.modules.transactions.models import Transaction
from app.modules.transfers.models import Transfer
from app.modules.transfers.schemas import (
    TransferCreate,
    TransferRead,
    TransferReverse,
    TransferUpdate,
)

EXCHANGE_RATE_PLACES = 12

_SORTABLE = {
    "transfer_date": Transfer.transfer_date,
    "from_amount": Transfer.from_amount,
    "to_amount": Transfer.to_amount,
    "fee": Transfer.fee,
    "created_at": Transfer.created_at,
    "updated_at": Transfer.updated_at,
}


@dataclass(frozen=True)
class TransferTerms:
    """Resolved accounts, currencies, amounts, and base-currency values."""

    from_account: Account
    to_account: Account
    from_currency: str
    to_currency: str
    from_amount: Decimal
    to_amount: Decimal
    exchange_rate: Decimal
    base_amount: Decimal
    base_currency: str
    fee: Decimal
    fee_currency: str
    fee_base_amount: Decimal
    fee_exchange_rate: Decimal


def _audit_data(transfer: Transfer) -> dict[str, Any]:
    return {
        "from_account_id": transfer.from_account_id,
        "to_account_id": transfer.to_account_id,
        "from_amount": transfer.from_amount,
        "from_currency": transfer.from_currency,
        "to_amount": transfer.to_amount,
        "to_currency": transfer.to_currency,
        "exchange_rate": transfer.exchange_rate,
        "base_amount": transfer.base_amount,
        "base_currency": transfer.base_currency,
        "fee": transfer.fee,
        "fee_currency": transfer.fee_currency,
        "transfer_date": transfer.transfer_date,
        "description": transfer.description,
        "status": transfer.status,
        "reverses_transfer_id": transfer.reverses_transfer_id,
    }


def _fee_audit_data(transaction: Transaction) -> dict[str, Any]:
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
        "status": transaction.status,
        "reverses_transaction_id": transaction.reverses_transaction_id,
        "transfer_id": transaction.transfer_id,
    }


def _transfer_response(transfer: Transfer) -> dict[str, Any]:
    return TransferRead.model_validate(transfer).model_dump(mode="json")


async def get_transfer(session: AsyncSession, household_id: UUID, transfer_id: UUID) -> Transfer:
    transfer = await session.scalar(
        select(Transfer).where(
            Transfer.id == transfer_id,
            Transfer.household_id == household_id,
        )
    )
    if transfer is None:
        raise NotFoundError("Transfer not found", error_code="TRANSFER_NOT_FOUND")
    return transfer


async def _active_account(session: AsyncSession, household_id: UUID, account_id: UUID) -> Account:
    account = await get_account(session, household_id, account_id)
    if not account.is_active:
        raise AppError(
            "Account is inactive",
            status_code=409,
            error_code="ACCOUNT_INACTIVE",
        )
    return account


async def _ensure_balance(
    session: AsyncSession,
    *,
    account: Account,
    currency: str,
    decrease: Decimal,
) -> None:
    await ensure_withdrawable(session, account=account, currency=currency, decrease=decrease)


async def _ensure_transfer_funds(session: AsyncSession, terms: TransferTerms) -> None:
    """Reject transfers (principal + same-currency fee) that overdraw the source."""
    if terms.fee > 0 and terms.fee_currency == terms.from_currency:
        await _ensure_balance(
            session,
            account=terms.from_account,
            currency=terms.from_currency,
            decrease=terms.from_amount + terms.fee,
        )
        return
    await _ensure_balance(
        session,
        account=terms.from_account,
        currency=terms.from_currency,
        decrease=terms.from_amount,
    )
    if terms.fee > 0:
        await _ensure_balance(
            session,
            account=terms.from_account,
            currency=terms.fee_currency,
            decrease=terms.fee,
        )


async def _resolve_terms(
    session: AsyncSession,
    household: Household,
    *,
    from_account_id: UUID,
    to_account_id: UUID,
    from_amount: Decimal,
    from_currency: str | None,
    to_amount: Decimal,
    to_currency: str | None,
    exchange_rate: Decimal | None,
    base_exchange_rate: Decimal | None,
    fee: Decimal,
    fee_currency: str | None,
    fee_exchange_rate: Decimal | None,
) -> TransferTerms:
    household_base = await get_currency(session, str(household.base_currency).strip())
    from_account = await _active_account(session, household.id, from_account_id)
    to_account = await _active_account(session, household.id, to_account_id)

    from_curr = await get_currency(session, from_currency or str(from_account.currency).strip())
    to_curr = await get_currency(session, to_currency or str(to_account.currency).strip())
    if from_account.id == to_account.id and from_curr.code == to_curr.code:
        raise AppError(
            "A transfer must change either the account or the currency",
            status_code=400,
            error_code="TRANSFER_SOURCE_SAME",
        )

    rounded_from = quantize_amount(from_amount, from_curr.decimal_places)
    rounded_to = quantize_amount(to_amount, to_curr.decimal_places)
    if rounded_from <= 0 or rounded_to <= 0:
        raise AppError(
            "Transfer amounts must be positive after currency rounding",
            status_code=400,
            error_code="AMOUNT_INVALID",
        )

    if exchange_rate is not None:
        rate = quantize_amount(exchange_rate, EXCHANGE_RATE_PLACES)
    elif from_curr.code == to_curr.code:
        rate = Decimal("1")
    else:
        # to_amount is authoritative; the recorded rate only mirrors execution.
        rate = quantize_amount(rounded_to / rounded_from, EXCHANGE_RATE_PLACES)

    if from_curr.code == household_base.code:
        base_amount = rounded_from
    elif to_curr.code == household_base.code:
        base_amount = rounded_to
    else:
        if base_exchange_rate is None:
            raise AppError(
                "base_exchange_rate is required when neither currency is the "
                "household base currency",
                status_code=400,
                error_code="BASE_EXCHANGE_RATE_REQUIRED",
            )
        base_amount = quantize_money(
            rounded_from * quantize_amount(base_exchange_rate, EXCHANGE_RATE_PLACES)
        )

    fee_curr = await get_currency(session, fee_currency or from_curr.code)
    rounded_fee = quantize_amount(fee, fee_curr.decimal_places)
    fee_rounded_rate = Decimal("1")
    if rounded_fee == 0:
        fee_base_amount = Decimal("0")
    elif fee_curr.code == household_base.code:
        fee_base_amount = rounded_fee
    elif fee_curr.code == from_curr.code:
        fee_rounded_rate = quantize_amount(base_amount / rounded_from, EXCHANGE_RATE_PLACES)
        fee_base_amount = quantize_money(rounded_fee * base_amount / rounded_from)
    elif fee_curr.code == to_curr.code:
        fee_rounded_rate = quantize_amount(base_amount / rounded_to, EXCHANGE_RATE_PLACES)
        fee_base_amount = quantize_money(rounded_fee * base_amount / rounded_to)
    else:
        if fee_exchange_rate is None:
            raise AppError(
                "fee_exchange_rate is required when the fee currency differs "
                "from both transfer currencies and the household base currency",
                status_code=400,
                error_code="FEE_EXCHANGE_RATE_REQUIRED",
            )
        fee_rounded_rate = quantize_amount(fee_exchange_rate, EXCHANGE_RATE_PLACES)
        fee_base_amount = quantize_money(rounded_fee * fee_rounded_rate)

    return TransferTerms(
        from_account=from_account,
        to_account=to_account,
        from_currency=from_curr.code,
        to_currency=to_curr.code,
        from_amount=rounded_from,
        to_amount=rounded_to,
        exchange_rate=rate,
        base_amount=base_amount,
        base_currency=household_base.code,
        fee=rounded_fee,
        fee_currency=fee_curr.code,
        fee_base_amount=fee_base_amount,
        fee_exchange_rate=fee_rounded_rate,
    )


async def _fee_category(session: AsyncSession, household_id: UUID) -> Category:
    category = await session.scalar(
        select(Category)
        .where(
            Category.household_id == household_id,
            Category.name == FINANCIAL_FEE_NAME,
            Category.category_type == CategoryType.EXPENSE.value,
        )
        .order_by(Category.created_at.asc())
        .limit(1)
    )
    if category is None:  # pragma: no cover - default categories always include it
        category = Category(
            household_id=household_id,
            name=FINANCIAL_FEE_NAME,
            category_type=CategoryType.EXPENSE.value,
            parent_id=None,
            icon="receipt",
            sort_order=990,
            is_active=True,
        )
        session.add(category)
        await session.flush()
    return category


async def _create_fee_transaction(
    session: AsyncSession,
    household: Household,
    transfer: Transfer,
    terms: TransferTerms,
    occurred_at: datetime,
) -> Transaction:
    category = await _fee_category(session, household.id)
    fee_transaction = Transaction(
        household_id=household.id,
        account_id=terms.from_account.id,
        category_id=category.id,
        transaction_type=TransactionType.EXPENSE.value,
        amount=terms.fee,
        currency=terms.fee_currency,
        base_amount=terms.fee_base_amount,
        base_currency=terms.base_currency,
        exchange_rate=terms.fee_exchange_rate,
        exchange_rate_date=occurred_at.date(),
        transaction_date=occurred_at,
        description=f"Transfer fee for transfer {transfer.id}",
        source=TransactionSource.SYSTEM.value,
        status=TransactionStatus.CONFIRMED.value,
        transfer_id=transfer.id,
    )
    session.add(fee_transaction)
    await session.flush()
    write_audit(
        session,
        household_id=household.id,
        action="transaction.create",
        entity_type="transaction",
        entity_id=fee_transaction.id,
        after=_fee_audit_data(fee_transaction),
    )
    return fee_transaction


async def _persist_transfer(
    session: AsyncSession,
    household: Household,
    terms: TransferTerms,
    *,
    description: str | None,
    occurred_at: datetime,
    status: TransactionStatus,
) -> Transfer:
    """Build the transfer row (and its fee leg) WITHOUT committing.

    Composers of larger flows (investment fund/redeem) call this inside
    their own transaction so the whole business action is atomic.
    """
    if status is TransactionStatus.CONFIRMED:
        await _ensure_transfer_funds(session, terms)

    transfer = Transfer(
        household_id=household.id,
        from_account_id=terms.from_account.id,
        to_account_id=terms.to_account.id,
        from_amount=terms.from_amount,
        from_currency=terms.from_currency,
        to_amount=terms.to_amount,
        to_currency=terms.to_currency,
        exchange_rate=terms.exchange_rate,
        base_amount=terms.base_amount,
        base_currency=terms.base_currency,
        fee=terms.fee,
        fee_currency=terms.fee_currency,
        transfer_date=occurred_at,
        description=description,
        status=status.value,
    )
    session.add(transfer)
    await session.flush()

    fee_transaction: Transaction | None = None
    if status is TransactionStatus.CONFIRMED and terms.fee > 0:
        fee_transaction = await _create_fee_transaction(
            session, household, transfer, terms, occurred_at
        )

    after = _audit_data(transfer)
    if fee_transaction is not None:
        after["fee_transaction_id"] = fee_transaction.id
    write_audit(
        session,
        household_id=household.id,
        action="transfer.create",
        entity_type="transfer",
        entity_id=transfer.id,
        after=after,
    )
    return transfer


async def create_transfer(
    session: AsyncSession,
    household: Household,
    payload: TransferCreate,
) -> Transfer:
    terms = await _resolve_terms(
        session,
        household,
        from_account_id=payload.from_account_id,
        to_account_id=payload.to_account_id,
        from_amount=payload.from_amount,
        from_currency=payload.from_currency,
        to_amount=payload.to_amount,
        to_currency=payload.to_currency,
        exchange_rate=payload.exchange_rate,
        base_exchange_rate=payload.base_exchange_rate,
        fee=payload.fee,
        fee_currency=payload.fee_currency,
        fee_exchange_rate=payload.fee_exchange_rate,
    )
    transfer = await _persist_transfer(
        session,
        household,
        terms,
        description=payload.description,
        occurred_at=payload.transfer_date or datetime.now(UTC),
        status=TransactionStatus(payload.status),
    )
    await session.commit()
    await session.refresh(transfer)
    return transfer


async def update_transfer(
    session: AsyncSession,
    household: Household,
    transfer_id: UUID,
    payload: TransferUpdate,
) -> Transfer:
    transfer = await get_transfer(session, household.id, transfer_id)
    if transfer.status != TransactionStatus.DRAFT.value:
        raise AppError(
            "Only draft transfers can be modified",
            status_code=409,
            error_code="TRANSFER_NOT_EDITABLE",
        )

    changes = payload.model_dump(exclude_unset=True)
    before = _audit_data(transfer)

    from_account_id = changes.get("from_account_id") or transfer.from_account_id
    to_account_id = changes.get("to_account_id") or transfer.to_account_id
    from_amount = changes.get("from_amount") or transfer.from_amount
    to_amount = changes.get("to_amount") or transfer.to_amount
    from_currency = (
        changes.get("from_currency")
        if "from_currency" in changes
        else str(transfer.from_currency).strip()
    )
    to_currency = (
        changes.get("to_currency")
        if "to_currency" in changes
        else str(transfer.to_currency).strip()
    )
    fee_currency = (
        changes.get("fee_currency")
        if "fee_currency" in changes
        else str(transfer.fee_currency).strip()
    )
    fee = changes["fee"] if changes.get("fee") is not None else transfer.fee
    if "exchange_rate" in changes:
        exchange_rate = changes["exchange_rate"]
    else:
        same_pair = (
            from_account_id == transfer.from_account_id
            and to_account_id == transfer.to_account_id
            and from_currency == str(transfer.from_currency).strip()
            and to_currency == str(transfer.to_currency).strip()
            and from_amount == transfer.from_amount
            and to_amount == transfer.to_amount
        )
        exchange_rate = transfer.exchange_rate if same_pair else None

    if "base_exchange_rate" in changes:
        base_exchange_rate = changes["base_exchange_rate"]
    elif (
        transfer.base_amount is not None
        and str(transfer.base_currency).strip() == str(household.base_currency).strip()
        and from_currency == str(transfer.from_currency).strip()
    ):
        base_exchange_rate = transfer.base_amount / transfer.from_amount
    else:
        base_exchange_rate = None

    terms = await _resolve_terms(
        session,
        household,
        from_account_id=from_account_id,
        to_account_id=to_account_id,
        from_amount=from_amount,
        from_currency=from_currency,
        to_amount=to_amount,
        to_currency=to_currency,
        exchange_rate=exchange_rate,
        base_exchange_rate=base_exchange_rate,
        fee=fee,
        fee_currency=fee_currency,
        fee_exchange_rate=changes.get("fee_exchange_rate"),
    )

    new_status_value = changes.get("status")
    new_status = TransactionStatus(new_status_value) if new_status_value is not None else None
    final_status = new_status or TransactionStatus(transfer.status)
    if final_status is TransactionStatus.CONFIRMED:
        await _ensure_transfer_funds(session, terms)

    transfer.from_account_id = terms.from_account.id
    transfer.to_account_id = terms.to_account.id
    transfer.from_amount = terms.from_amount
    transfer.from_currency = terms.from_currency
    transfer.to_amount = terms.to_amount
    transfer.to_currency = terms.to_currency
    transfer.exchange_rate = terms.exchange_rate
    transfer.base_amount = terms.base_amount
    transfer.base_currency = terms.base_currency
    transfer.fee = terms.fee
    transfer.fee_currency = terms.fee_currency
    if changes.get("transfer_date") is not None:
        transfer.transfer_date = changes["transfer_date"]
    if "description" in changes:
        transfer.description = changes["description"]
    transfer.status = final_status.value
    await session.flush()

    fee_transaction: Transaction | None = None
    confirming = (
        final_status is TransactionStatus.CONFIRMED
        and before["status"] == TransactionStatus.DRAFT.value
    )
    if confirming and terms.fee > 0:
        fee_transaction = await _create_fee_transaction(
            session, household, transfer, terms, transfer.transfer_date
        )

    after = _audit_data(transfer)
    if fee_transaction is not None:
        after["fee_transaction_id"] = fee_transaction.id
    if before != after:
        write_audit(
            session,
            household_id=household.id,
            action="transfer.confirm" if confirming else "transfer.update",
            entity_type="transfer",
            entity_id=transfer.id,
            before=before,
            after=after,
        )
    await session.commit()
    await session.refresh(transfer)
    return transfer


async def delete_transfer(session: AsyncSession, household: Household, transfer_id: UUID) -> None:
    transfer = await get_transfer(session, household.id, transfer_id)
    if transfer.status != TransactionStatus.DRAFT.value:
        raise AppError(
            "Only draft transfers can be deleted",
            status_code=409,
            error_code="TRANSFER_NOT_DELETABLE",
        )
    write_audit(
        session,
        household_id=household.id,
        action="transfer.delete",
        entity_type="transfer",
        entity_id=transfer.id,
        before=_audit_data(transfer),
    )
    await session.delete(transfer)
    await session.commit()


async def _reverse_derived_transaction(
    session: AsyncSession,
    household: Household,
    reversal: Transfer,
    derived: Transaction,
) -> Transaction:
    """Reverse one transfer-derived row (fee expense or redeem PnL).

    The reversal flips the direction: an expense un-posts as income and
    vice versa, mirroring the original amounts exactly.
    """
    reversed_type = (
        TransactionType.INCOME.value
        if derived.transaction_type == TransactionType.EXPENSE.value
        else TransactionType.EXPENSE.value
    )
    derived.status = TransactionStatus.REVERSED.value
    derived_reversal = Transaction(
        household_id=household.id,
        account_id=derived.account_id,
        category_id=derived.category_id,
        transaction_type=reversed_type,
        amount=derived.amount,
        currency=str(derived.currency).strip(),
        base_amount=derived.base_amount,
        base_currency=str(derived.base_currency).strip(),
        exchange_rate=derived.exchange_rate,
        exchange_rate_date=reversal.transfer_date.date(),
        transaction_date=reversal.transfer_date,
        description=f"Reversal of transfer-derived transaction {derived.id}",
        source=TransactionSource.SYSTEM.value,
        status=TransactionStatus.CONFIRMED.value,
        reverses_transaction_id=derived.id,
        transfer_id=reversal.id,
    )
    session.add(derived_reversal)
    await session.flush()
    write_audit(
        session,
        household_id=household.id,
        action="transaction.reverse",
        entity_type="transaction",
        entity_id=derived.id,
        before=_fee_audit_data(derived),
        after={
            "status": derived.status,
            "reversal_id": derived_reversal.id,
            "reversal": _fee_audit_data(derived_reversal),
        },
    )
    return derived_reversal


async def reverse_transfer(
    session: AsyncSession,
    household: Household,
    transfer_id: UUID,
    payload: TransferReverse,
) -> Transfer:
    original = await get_transfer(session, household.id, transfer_id)
    if original.status != TransactionStatus.CONFIRMED.value:
        raise AppError(
            "Only confirmed transfers can be reversed",
            status_code=409,
            error_code="TRANSFER_NOT_REVERSIBLE",
        )
    if original.reverses_transfer_id is not None:
        raise AppError(
            "A reversal transfer cannot be reversed again",
            status_code=409,
            error_code="TRANSFER_NOT_REVERSIBLE",
        )

    # Investment linkage runs first so a rejection (e.g. principal would go
    # negative) aborts the reversal before any rows are written.
    await apply_reversal_linkage(session, household, original)

    from_currency = str(original.to_currency).strip()
    to_currency = str(original.from_currency).strip()
    from_amount = original.to_amount
    to_amount = original.from_amount
    if from_currency == to_currency:
        exchange_rate = Decimal("1")
    else:
        exchange_rate = quantize_amount(to_amount / from_amount, EXCHANGE_RATE_PLACES)

    to_account = await get_account(session, household.id, original.to_account_id)
    await _ensure_balance(
        session,
        account=to_account,
        currency=from_currency,
        decrease=from_amount,
    )

    before = _audit_data(original)
    original.status = TransactionStatus.REVERSED.value
    occurred_at = payload.transfer_date or datetime.now(UTC)
    reversal = Transfer(
        household_id=household.id,
        from_account_id=original.to_account_id,
        to_account_id=original.from_account_id,
        from_amount=from_amount,
        from_currency=from_currency,
        to_amount=to_amount,
        to_currency=to_currency,
        exchange_rate=exchange_rate,
        base_amount=original.base_amount,
        base_currency=original.base_currency,
        fee=Decimal("0"),
        fee_currency=str(original.fee_currency).strip(),
        transfer_date=occurred_at,
        description=payload.description or f"Reversal of transfer {original.id}",
        status=TransactionStatus.CONFIRMED.value,
        reverses_transfer_id=original.id,
    )
    session.add(reversal)
    await session.flush()

    derived_transactions = list(
        (
            await session.scalars(
                select(Transaction)
                .where(
                    Transaction.transfer_id == original.id,
                    Transaction.status == TransactionStatus.CONFIRMED.value,
                )
                .order_by(Transaction.created_at.asc())
            )
        ).all()
    )
    derived_reversal_ids = [
        (await _reverse_derived_transaction(session, household, reversal, derived)).id
        for derived in derived_transactions
    ]

    after = {
        "status": original.status,
        "reversal_id": reversal.id,
        "reversal": _audit_data(reversal),
    }
    if derived_reversal_ids:
        after["derived_reversal_ids"] = derived_reversal_ids
    write_audit(
        session,
        household_id=household.id,
        action="transfer.reverse",
        entity_type="transfer",
        entity_id=original.id,
        before=before,
        after=after,
    )
    await session.commit()
    await session.refresh(reversal)
    return reversal


async def list_transfers(
    session: AsyncSession,
    household: Household,
    pagination: Pagination,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    account_id: UUID | None = None,
    from_account_id: UUID | None = None,
    to_account_id: UUID | None = None,
    status: TransactionStatus | None = None,
    from_currency: str | None = None,
    to_currency: str | None = None,
) -> tuple[list[Transfer], int]:
    filters = [Transfer.household_id == household.id]
    tz = ZoneInfo(household.timezone)
    if start_date is not None:
        filters.append(Transfer.transfer_date >= datetime.combine(start_date, time.min, tzinfo=tz))
    if end_date is not None:
        filters.append(
            Transfer.transfer_date
            < datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=tz)
        )
    if account_id is not None:
        filters.append(
            or_(
                Transfer.from_account_id == account_id,
                Transfer.to_account_id == account_id,
            )
        )
    if from_account_id is not None:
        filters.append(Transfer.from_account_id == from_account_id)
    if to_account_id is not None:
        filters.append(Transfer.to_account_id == to_account_id)
    if status is not None:
        filters.append(Transfer.status == status.value)
    if from_currency is not None:
        filters.append(Transfer.from_currency == from_currency.upper())
    if to_currency is not None:
        filters.append(Transfer.to_currency == to_currency.upper())

    total = await session.scalar(select(func.count()).select_from(Transfer).where(*filters))
    column, descending = resolve_sort(
        pagination.sort_by, pagination.sort_order, _SORTABLE, "transfer_date"
    )
    stmt = (
        select(Transfer)
        .where(*filters)
        .order_by(column.desc() if descending else column.asc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return list((await session.scalars(stmt)).all()), int(total or 0)


def transfer_response(transfer: Transfer) -> dict[str, Any]:
    return _transfer_response(transfer)
