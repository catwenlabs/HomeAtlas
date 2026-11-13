"""Loan use cases (asset-design sections 4.3, 5.5, 6.4)."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import money
from app.core.enums import LoanStatus
from app.core.exceptions import AppError, NotFoundError
from app.core.money import quantize_amount, quantize_money
from app.core.pagination import Pagination, resolve_sort
from app.modules.accounts.service import get_account
from app.modules.audit.service import write_audit
from app.modules.currencies.service import get_currency
from app.modules.households.models import Household
from app.modules.loans.models import Loan, loan_audit_data
from app.modules.loans.schemas import LoanCreate, LoanSettle, LoanUpdate

_SORTABLE = {
    "created_at": Loan.created_at,
    "start_date": Loan.start_date,
    "name": Loan.name,
    "principal": Loan.principal,
    "remaining_principal": Loan.remaining_principal,
}


def daily_interest(loan: Loan) -> Decimal:
    """remaining_principal x annual_rate / 365 (estimate, no flows)."""
    return quantize_money(money.daily_interest(loan.remaining_principal, loan.annual_rate))


async def get_loan(session: AsyncSession, household_id: UUID, loan_id: UUID) -> Loan:
    loan = await session.scalar(
        select(Loan).where(
            Loan.id == loan_id,
            Loan.household_id == household_id,
        )
    )
    if loan is None:
        raise NotFoundError("Loan not found", error_code="LOAN_NOT_FOUND")
    return loan


def _ensure_active(loan: Loan, *, error_code: str = "LOAN_ALREADY_SETTLED") -> None:
    if loan.status != LoanStatus.ACTIVE.value:
        raise AppError(
            "Loan is already settled",
            status_code=409,
            error_code=error_code,
        )


async def create_loan(session: AsyncSession, household: Household, payload: LoanCreate) -> Loan:
    currency = await get_currency(session, payload.currency)
    if payload.linked_account_id is not None:
        await get_account(session, household.id, payload.linked_account_id)
    remaining = (
        payload.remaining_principal
        if payload.remaining_principal is not None
        else payload.principal
    )
    loan = Loan(
        household_id=household.id,
        name=payload.name,
        institution=payload.institution,
        principal=quantize_amount(payload.principal, currency.decimal_places),
        currency=payload.currency,
        annual_rate=payload.annual_rate,
        start_date=payload.start_date,
        end_date=payload.end_date,
        due_day=payload.due_day,
        repayment_type=payload.repayment_type.value,
        linked_account_id=payload.linked_account_id,
        remaining_principal=quantize_amount(remaining, currency.decimal_places),
        remark=payload.remark,
    )
    session.add(loan)
    await session.flush()
    write_audit(
        session,
        household_id=household.id,
        action="loan.create",
        entity_type="loan",
        entity_id=loan.id,
        after=loan_audit_data(loan),
    )
    await session.commit()
    await session.refresh(loan)
    return loan


async def update_loan(
    session: AsyncSession,
    household: Household,
    loan_id: UUID,
    payload: LoanUpdate,
) -> Loan:
    loan = await get_loan(session, household.id, loan_id)
    _ensure_active(loan, error_code="LOAN_NOT_EDITABLE")
    before = loan_audit_data(loan)
    changes = payload.model_dump(exclude_unset=True)

    if changes.get("remaining_principal") is not None:
        if changes["remaining_principal"] > loan.principal:
            raise AppError(
                "remaining_principal cannot exceed principal",
                status_code=422,
                error_code="LOAN_REMAINING_INVALID",
            )
        currency = await get_currency(session, str(loan.currency).strip())
        loan.remaining_principal = quantize_amount(
            changes["remaining_principal"], currency.decimal_places
        )
    if changes.get("linked_account_id") is not None:
        await get_account(session, household.id, changes["linked_account_id"])
        loan.linked_account_id = changes["linked_account_id"]
    if changes.get("name") is not None:
        loan.name = changes["name"]
    if "institution" in changes:
        loan.institution = changes["institution"]
    if changes.get("annual_rate") is not None:
        loan.annual_rate = changes["annual_rate"]
    if "end_date" in changes:
        loan.end_date = changes["end_date"]
    if "due_day" in changes:
        loan.due_day = changes["due_day"]
    if changes.get("repayment_type") is not None:
        loan.repayment_type = changes["repayment_type"].value
    if "remark" in changes:
        loan.remark = changes["remark"]

    await session.flush()
    write_audit(
        session,
        household_id=household.id,
        action="loan.update",
        entity_type="loan",
        entity_id=loan.id,
        before=before,
        after=loan_audit_data(loan),
    )
    await session.commit()
    await session.refresh(loan)
    return loan


async def settle_loan(
    session: AsyncSession,
    household: Household,
    loan_id: UUID,
    payload: LoanSettle,
) -> Loan:
    """active -> settled; early payoff is allowed and zeroes the remainder."""
    loan = await get_loan(session, household.id, loan_id)
    _ensure_active(loan)
    before = loan_audit_data(loan)
    loan.status = LoanStatus.SETTLED.value
    loan.remaining_principal = Decimal("0")
    loan.settled_date = payload.settled_date
    await session.flush()
    write_audit(
        session,
        household_id=household.id,
        action="loan.settle",
        entity_type="loan",
        entity_id=loan.id,
        before=before,
        after=loan_audit_data(loan),
    )
    await session.commit()
    await session.refresh(loan)
    return loan


async def delete_loan(session: AsyncSession, household: Household, loan_id: UUID) -> None:
    """Repayments are ordinary expense flows with no FK to loans, so only
    the active state is checked (recorded as a 2C-3 boundary)."""
    loan = await get_loan(session, household.id, loan_id)
    _ensure_active(loan, error_code="LOAN_NOT_DELETABLE")
    before = loan_audit_data(loan)
    await session.delete(loan)
    write_audit(
        session,
        household_id=household.id,
        action="loan.delete",
        entity_type="loan",
        entity_id=loan.id,
        before=before,
    )
    await session.commit()


async def list_loans(
    session: AsyncSession,
    household: Household,
    pagination: Pagination,
    *,
    status: str | None = None,
) -> tuple[list[Loan], int]:
    filters = [Loan.household_id == household.id]
    if status is not None:
        if status not in {LoanStatus.ACTIVE.value, LoanStatus.SETTLED.value}:
            raise AppError(
                "status must be one of active, settled",
                status_code=422,
                error_code="VALIDATION_ERROR",
            )
        filters.append(Loan.status == status)
    total = await session.scalar(select(func.count()).select_from(Loan).where(*filters)) or 0
    column, descending = resolve_sort(
        pagination.sort_by, pagination.sort_order, _SORTABLE, "created_at"
    )
    stmt = (
        select(Loan)
        .where(*filters)
        .order_by(column.desc() if descending else column.asc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return list((await session.scalars(stmt)).all()), int(total)


async def active_loan_liabilities(session: AsyncSession, household_id: UUID) -> dict[str, Decimal]:
    """currency -> total remaining principal of active loans."""
    rows = (
        await session.execute(
            select(Loan.currency, func.sum(Loan.remaining_principal))
            .where(
                Loan.household_id == household_id,
                Loan.status == LoanStatus.ACTIVE.value,
            )
            .group_by(Loan.currency)
        )
    ).all()
    return {str(currency).strip(): total or Decimal("0") for currency, total in rows}


async def active_loan_interest(session: AsyncSession, household_id: UUID) -> dict[str, Decimal]:
    """currency -> total daily interest of active loans (estimate)."""
    rows = (
        await session.scalars(
            select(Loan).where(
                Loan.household_id == household_id,
                Loan.status == LoanStatus.ACTIVE.value,
            )
        )
    ).all()
    totals: dict[str, Decimal] = {}
    for loan in rows:
        currency = str(loan.currency).strip()
        totals[currency] = totals.get(currency, Decimal("0")) + money.daily_interest(
            loan.remaining_principal, loan.annual_rate
        )
    return totals
