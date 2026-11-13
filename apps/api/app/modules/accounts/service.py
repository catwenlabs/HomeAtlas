"""Account, reconciliation snapshot, and live-balance use cases."""

from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import TransactionStatus, TransactionType
from app.core.exceptions import AppError, NotFoundError
from app.core.pagination import Pagination, resolve_sort
from app.modules.accounts.models import Account, AccountBalance
from app.modules.accounts.schemas import (
    AccountBalanceSnapshotRead,
    AccountBalancesRead,
    AccountCreate,
    AccountUpdate,
    BalanceLine,
)
from app.modules.currencies.service import get_currency
from app.modules.transactions.models import Transaction
from app.modules.transfers.models import Transfer

_SORTABLE = {
    "name": Account.name,
    "created_at": Account.created_at,
    "updated_at": Account.updated_at,
    "is_active": Account.is_active,
}

_BALANCE_STATUSES = (TransactionStatus.CONFIRMED.value, TransactionStatus.REVERSED.value)


async def list_accounts(
    session: AsyncSession,
    household_id: UUID,
    pagination: Pagination,
    *,
    is_active: bool | None = None,
) -> tuple[list[Account], int]:
    filters = [Account.household_id == household_id]
    if is_active is not None:
        filters.append(Account.is_active == is_active)
    total = await session.scalar(select(func.count()).select_from(Account).where(*filters))
    column, descending = resolve_sort(
        pagination.sort_by, pagination.sort_order, _SORTABLE, "created_at"
    )
    stmt = (
        select(Account)
        .where(*filters)
        .order_by(column.desc() if descending else column.asc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return list((await session.scalars(stmt)).all()), int(total or 0)


async def get_account(session: AsyncSession, household_id: UUID, account_id: UUID) -> Account:
    account = await session.scalar(
        select(Account).where(
            Account.id == account_id,
            Account.household_id == household_id,
        )
    )
    if account is None:
        raise NotFoundError("Account not found", error_code="ACCOUNT_NOT_FOUND")
    return account


async def create_account(
    session: AsyncSession, household_id: UUID, payload: AccountCreate
) -> Account:
    await get_currency(session, payload.currency)
    account = Account(
        household_id=household_id,
        name=payload.name,
        institution=payload.institution,
        account_type=payload.account_type.value,
        currency=payload.currency,
        external_ref=payload.external_ref,
        is_active=payload.is_active,
        annual_rate=payload.annual_rate,
        liquidity=payload.liquidity.value if payload.liquidity else None,
        credit_limit=payload.credit_limit,
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


async def update_account(
    session: AsyncSession,
    household_id: UUID,
    account_id: UUID,
    payload: AccountUpdate,
) -> Account:
    account = await get_account(session, household_id, account_id)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("currency") is not None:
        await get_currency(session, changes["currency"])
        account.currency = changes["currency"]
    if changes.get("account_type") is not None:
        new_type = changes["account_type"]
        if new_type != account.account_type:
            await _ensure_account_type_changeable(session, account)
        account.account_type = new_type.value
    if changes.get("name") is not None:
        account.name = changes["name"]
    if changes.get("is_active") is not None:
        account.is_active = changes["is_active"]
    if "institution" in changes:
        account.institution = changes["institution"]
    if "external_ref" in changes:
        account.external_ref = changes["external_ref"]
    if "annual_rate" in changes:
        account.annual_rate = changes["annual_rate"]
    if "liquidity" in changes:
        account.liquidity = changes["liquidity"].value if changes["liquidity"] else None
    if "credit_limit" in changes:
        account.credit_limit = changes["credit_limit"]
    await session.commit()
    await session.refresh(account)
    return account


async def _ensure_account_type_changeable(session: AsyncSession, account: Account) -> None:
    """Lock account_type once the account carries any history (H8)."""
    transaction_count = (
        await session.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.account_id == account.id)
        )
        or 0
    )
    transfer_count = (
        await session.scalar(
            select(func.count())
            .select_from(Transfer)
            .where(
                or_(
                    Transfer.from_account_id == account.id,
                    Transfer.to_account_id == account.id,
                )
            )
        )
        or 0
    )
    if transaction_count or transfer_count:
        raise AppError(
            "Account type cannot change after transactions or transfers exist",
            status_code=409,
            error_code="ACCOUNT_TYPE_IMMUTABLE",
        )


async def delete_account(session: AsyncSession, household_id: UUID, account_id: UUID) -> None:
    account = await get_account(session, household_id, account_id)
    transaction_count = await session.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.account_id == account.id)
    )
    transfer_count = await session.scalar(
        select(func.count())
        .select_from(Transfer)
        .where(
            or_(
                Transfer.from_account_id == account.id,
                Transfer.to_account_id == account.id,
            )
        )
    )
    if (transaction_count or 0) + (transfer_count or 0) > 0:
        raise AppError(
            "Account has historical transactions; deactivate it instead",
            status_code=409,
            error_code="ACCOUNT_HAS_TRANSACTIONS",
        )
    await session.delete(account)
    await session.commit()


async def _book_balances(session: AsyncSession, account_id: UUID) -> dict[str, Decimal]:
    signed_amount = case(
        (Transaction.transaction_type == TransactionType.EXPENSE.value, -Transaction.amount),
        else_=Transaction.amount,
    )
    transaction_rows = (
        await session.execute(
            select(Transaction.currency, func.sum(signed_amount))
            .where(
                Transaction.account_id == account_id,
                Transaction.status.in_(_BALANCE_STATUSES),
            )
            .group_by(Transaction.currency)
        )
    ).all()
    book: dict[str, Decimal] = defaultdict(Decimal)
    for currency, total in transaction_rows:
        book[str(currency).strip()] += total or Decimal("0")

    transfers = list(
        (
            await session.scalars(
                select(Transfer).where(
                    or_(
                        Transfer.from_account_id == account_id,
                        Transfer.to_account_id == account_id,
                    ),
                    Transfer.status.in_(_BALANCE_STATUSES),
                )
            )
        ).all()
    )
    for transfer in transfers:
        # Transfer fees are represented by a derived expense transaction
        # (spec 5.2), so only the principal moves are applied here.
        if transfer.from_account_id == account_id:
            book[str(transfer.from_currency).strip()] -= transfer.from_amount
        if transfer.to_account_id == account_id:
            book[str(transfer.to_currency).strip()] += transfer.to_amount
    return book


async def get_household_book_balances(
    session: AsyncSession, household_id: UUID
) -> dict[UUID, dict[str, Decimal]]:
    """Return account_id -> {currency: book balance} for one household.

    Same accounting rules as ``_book_balances``: confirmed + reversed
    transactions (opening balances included) plus transfer principals.
    Transfer fees stay represented by their derived expense transaction.
    """
    signed_amount = case(
        (Transaction.transaction_type == TransactionType.EXPENSE.value, -Transaction.amount),
        else_=Transaction.amount,
    )
    book: dict[UUID, dict[str, Decimal]] = {}
    transaction_rows = (
        await session.execute(
            select(Transaction.account_id, Transaction.currency, func.sum(signed_amount))
            .where(
                Transaction.household_id == household_id,
                Transaction.status.in_(_BALANCE_STATUSES),
            )
            .group_by(Transaction.account_id, Transaction.currency)
        )
    ).all()
    for account_id, currency, total in transaction_rows:
        book.setdefault(account_id, {})[str(currency).strip()] = total or Decimal("0")

    transfer_moves = union_all(
        select(
            Transfer.from_account_id.label("account_id"),
            Transfer.from_currency.label("currency"),
            (-Transfer.from_amount).label("delta"),
        ).where(
            Transfer.household_id == household_id,
            Transfer.status.in_(_BALANCE_STATUSES),
        ),
        select(
            Transfer.to_account_id.label("account_id"),
            Transfer.to_currency.label("currency"),
            Transfer.to_amount.label("delta"),
        ).where(
            Transfer.household_id == household_id,
            Transfer.status.in_(_BALANCE_STATUSES),
        ),
    ).subquery()
    transfer_rows = (
        await session.execute(
            select(
                transfer_moves.c.account_id,
                transfer_moves.c.currency,
                func.sum(transfer_moves.c.delta),
            ).group_by(transfer_moves.c.account_id, transfer_moves.c.currency)
        )
    ).all()
    for account_id, currency, total in transfer_rows:
        balances = book.setdefault(account_id, {})
        code = str(currency).strip()
        balances[code] = balances.get(code, Decimal("0")) + (total or Decimal("0"))
    return book


async def get_account_currency_balance(
    session: AsyncSession, account_id: UUID, currency: str
) -> Decimal:
    """Return the live book balance for one account currency."""
    book = await _book_balances(session, account_id)
    return book.get(currency.upper(), Decimal("0"))


async def get_account_balances(
    session: AsyncSession, household_id: UUID, account_id: UUID
) -> AccountBalancesRead:
    account = await get_account(session, household_id, account_id)
    book = await _book_balances(session, account.id)

    snapshots = list(
        (
            await session.scalars(
                select(AccountBalance)
                .where(AccountBalance.account_id == account.id)
                .order_by(AccountBalance.snapshot_at.desc(), AccountBalance.created_at.desc())
            )
        ).all()
    )
    latest: dict[str, AccountBalance] = {}
    for row in snapshots:
        latest.setdefault(str(row.currency).strip(), row)

    currencies = sorted(set(book) | set(latest))
    lines = []
    for currency in currencies:
        book_balance = book.get(currency, Decimal("0"))
        snapshot_row = latest.get(currency)
        difference = None if snapshot_row is None else snapshot_row.balance - book_balance
        lines.append(
            BalanceLine(
                currency=currency,
                book_balance=book_balance,
                latest_snapshot=(
                    None
                    if snapshot_row is None
                    else AccountBalanceSnapshotRead.model_validate(snapshot_row)
                ),
                difference=difference,
            )
        )
    return AccountBalancesRead(account_id=account.id, balances=lines)


async def list_account_transactions(
    session: AsyncSession,
    household_id: UUID,
    account_id: UUID,
    pagination: Pagination,
    *,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    transaction_type: TransactionType | None = None,
    status: TransactionStatus | None = None,
) -> tuple[list[Transaction], int]:
    account = await get_account(session, household_id, account_id)
    filters = [Transaction.account_id == account.id]
    if start_date is not None:
        filters.append(Transaction.transaction_date >= start_date)
    if end_date is not None:
        filters.append(Transaction.transaction_date <= end_date)
    if transaction_type is not None:
        filters.append(Transaction.transaction_type == transaction_type.value)
    if status is not None:
        filters.append(Transaction.status == status.value)

    total = await session.scalar(select(func.count()).select_from(Transaction).where(*filters))
    sortable = {
        "transaction_date": Transaction.transaction_date,
        "amount": Transaction.amount,
        "created_at": Transaction.created_at,
    }
    column, descending = resolve_sort(
        pagination.sort_by, pagination.sort_order, sortable, "transaction_date"
    )
    stmt = (
        select(Transaction)
        .where(*filters)
        .order_by(column.desc() if descending else column.asc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return list((await session.scalars(stmt)).all()), int(total or 0)


async def list_balance_history(
    session: AsyncSession,
    household_id: UUID,
    account_id: UUID,
    pagination: Pagination,
    *,
    currency: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[list[AccountBalance], int]:
    account = await get_account(session, household_id, account_id)
    filters = [AccountBalance.account_id == account.id]
    if currency is not None:
        filters.append(AccountBalance.currency == currency.upper())
    if start_date is not None:
        filters.append(
            AccountBalance.snapshot_at
            >= datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
        )
    if end_date is not None:
        filters.append(
            AccountBalance.snapshot_at
            <= datetime.combine(end_date, datetime.max.time(), tzinfo=UTC)
        )
    total = await session.scalar(select(func.count()).select_from(AccountBalance).where(*filters))
    stmt = (
        select(AccountBalance)
        .where(*filters)
        .order_by(AccountBalance.snapshot_at.desc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return list((await session.scalars(stmt)).all()), int(total or 0)
