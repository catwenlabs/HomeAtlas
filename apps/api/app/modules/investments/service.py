"""Investment registration use cases (asset-design sections 4.4, 5.5, 6.3)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AccountType, InvestmentStatus, TransactionStatus
from app.core.exceptions import AppError, NotFoundError
from app.core.money import quantize_money
from app.core.pagination import Pagination, resolve_sort
from app.modules.accounts.models import Account
from app.modules.accounts.service import get_account
from app.modules.audit.service import write_audit
from app.modules.currencies.service import get_currency
from app.modules.households.models import Household
from app.modules.investments import flows
from app.modules.investments.models import (
    Holding,
    Investment,
    InvestmentTag,
    InvestmentTagLink,
    InvestmentTransfer,
)
from app.modules.investments.schemas import (
    InvestmentCreate,
    InvestmentUpdate,
    InvestmentValueUpdate,
)
from app.modules.transfers.models import Transfer

_SORTABLE = {
    "created_at": Investment.created_at,
    "start_date": Investment.start_date,
    "name": Investment.name,
    "current_value": Investment.current_value,
}

HOLDING_TYPES = ("stock", "fund")


def household_today(household: Household) -> date:
    return datetime.now(ZoneInfo(str(household.timezone).strip())).date()


def is_matured(investment: Investment, today: date) -> bool:
    return (
        investment.status == InvestmentStatus.ACTIVE.value
        and investment.end_date is not None
        and investment.end_date <= today
    )


def _audit_data(investment: Investment) -> dict[str, Any]:
    return {
        "name": investment.name,
        "investment_type": investment.investment_type,
        "account_id": str(investment.account_id) if investment.account_id else None,
        "principal": str(investment.principal),
        "current_value": str(investment.current_value),
        "currency": str(investment.currency).strip(),
        "status": investment.status,
    }


async def get_investment(
    session: AsyncSession, household_id: UUID, investment_id: UUID
) -> Investment:
    investment = await session.scalar(
        select(Investment).where(
            Investment.id == investment_id,
            Investment.household_id == household_id,
        )
    )
    if investment is None:
        raise NotFoundError("Investment not found", error_code="INVESTMENT_NOT_FOUND")
    return investment


async def _resolve_investment_account(
    session: AsyncSession, household_id: UUID, account_id: UUID, currency: str
) -> Account:
    account = await get_account(session, household_id, account_id)
    if not account.is_active:
        raise AppError(
            "Account is inactive",
            status_code=409,
            error_code="ACCOUNT_INACTIVE",
        )
    if str(account.account_type).strip() != AccountType.INVESTMENT.value:
        raise AppError(
            "account_id must reference an investment-type account",
            status_code=422,
            error_code="INVESTMENT_ACCOUNT_INVALID",
        )
    if str(account.currency).strip() != currency:
        raise AppError(
            "The investment account currency must equal the investment currency",
            status_code=422,
            error_code="INVESTMENT_ACCOUNT_INVALID",
        )
    return account


async def _resolve_tags(
    session: AsyncSession, household_id: UUID, tag_ids: list[UUID]
) -> list[InvestmentTag]:
    tags: list[InvestmentTag] = []
    for tag_id in tag_ids:
        tag = await session.scalar(
            select(InvestmentTag).where(
                InvestmentTag.id == tag_id,
                InvestmentTag.household_id == household_id,
            )
        )
        if tag is None:
            raise NotFoundError("Investment tag not found", error_code="TAG_NOT_FOUND")
        tags.append(tag)
    return tags


async def create_investment(
    session: AsyncSession, household: Household, payload: InvestmentCreate
) -> Investment:
    await get_currency(session, payload.currency)
    account: Account | None = None
    if payload.account_id is not None:
        account = await _resolve_investment_account(
            session, household.id, payload.account_id, payload.currency
        )

    investment = Investment(
        household_id=household.id,
        name=payload.name,
        investment_type=payload.investment_type.value,
        account_id=account.id if account else None,
        principal=payload.principal,
        current_value=(
            payload.current_value if payload.current_value is not None else payload.principal
        ),
        currency=payload.currency,
        annual_rate=payload.annual_rate,
        start_date=payload.start_date,
        end_date=payload.end_date,
        liquidity=payload.liquidity.value if payload.liquidity else None,
        remark=payload.remark,
    )
    session.add(investment)
    await session.flush()

    for tag in await _resolve_tags(session, household.id, payload.tag_ids):
        session.add(InvestmentTagLink(investment_id=investment.id, tag_id=tag.id))

    if payload.fund_transfer is not None:
        # Account presence is enforced inside the flow (409 when unmanaged).
        await flows.execute_fund(session, household, investment, payload.fund_transfer)

    await session.flush()
    write_audit(
        session,
        household_id=household.id,
        action="investment.create",
        entity_type="investment",
        entity_id=investment.id,
        after=_audit_data(investment),
    )
    await session.commit()
    await session.refresh(investment)
    return investment


async def update_investment(
    session: AsyncSession,
    household: Household,
    investment_id: UUID,
    payload: InvestmentUpdate,
) -> Investment:
    investment = await get_investment(session, household.id, investment_id)
    flows.ensure_active(investment)
    changes = payload.model_dump(exclude_unset=True)

    if "principal" in changes:
        if investment.account_id is not None:
            raise AppError(
                "principal is derived from fund transfers on a managed "
                "investment; adjust it by funding or reversing a fund transfer",
                status_code=409,
                error_code="INVESTMENT_NOT_EDITABLE",
            )
        investment.principal = changes["principal"]

    if changes.get("name") is not None:
        investment.name = changes["name"]
    if changes.get("investment_type") is not None:
        investment.investment_type = changes["investment_type"].value
    if "annual_rate" in changes:
        investment.annual_rate = changes["annual_rate"]
    if changes.get("start_date") is not None:
        investment.start_date = changes["start_date"]
    if "end_date" in changes:
        investment.end_date = changes["end_date"]
    if "liquidity" in changes:
        investment.liquidity = changes["liquidity"].value if changes["liquidity"] else None
    if "remark" in changes:
        investment.remark = changes["remark"]

    await session.flush()
    write_audit(
        session,
        household_id=household.id,
        action="investment.update",
        entity_type="investment",
        entity_id=investment.id,
        after=_audit_data(investment),
    )
    await session.commit()
    await session.refresh(investment)
    return investment


async def set_value(
    session: AsyncSession,
    household: Household,
    investment_id: UUID,
    payload: InvestmentValueUpdate,
) -> Investment:
    """The only write path for current_value (floating PnL is not a flow)."""
    investment = await get_investment(session, household.id, investment_id)
    flows.ensure_active(investment)
    before = str(investment.current_value)
    investment.current_value = payload.current_value
    await session.flush()
    write_audit(
        session,
        household_id=household.id,
        action="investment.value",
        entity_type="investment",
        entity_id=investment.id,
        before={"current_value": before},
        after={"current_value": str(investment.current_value)},
    )
    await session.commit()
    await session.refresh(investment)
    return investment


async def set_tags(
    session: AsyncSession,
    household: Household,
    investment_id: UUID,
    tag_ids: list[UUID],
) -> Investment:
    investment = await get_investment(session, household.id, investment_id)
    flows.ensure_active(investment)
    tags = await _resolve_tags(session, household.id, tag_ids)
    await session.execute(
        delete(InvestmentTagLink).where(InvestmentTagLink.investment_id == investment.id)
    )
    for tag in tags:
        session.add(InvestmentTagLink(investment_id=investment.id, tag_id=tag.id))
    await session.flush()
    write_audit(
        session,
        household_id=household.id,
        action="investment.tags",
        entity_type="investment",
        entity_id=investment.id,
        after={"tag_ids": [str(tag.id) for tag in tags]},
    )
    await session.commit()
    await session.refresh(investment)
    return investment


async def delete_investment(
    session: AsyncSession, household: Household, investment_id: UUID
) -> None:
    investment = await get_investment(session, household.id, investment_id)
    if investment.status != InvestmentStatus.ACTIVE.value:
        raise AppError(
            "Only active investments can be deleted",
            status_code=409,
            error_code="INVESTMENT_NOT_DELETABLE",
        )
    unreversed = (
        await session.scalar(
            select(func.count())
            .select_from(InvestmentTransfer)
            .join(Transfer, Transfer.id == InvestmentTransfer.transfer_id)
            .where(
                InvestmentTransfer.investment_id == investment.id,
                Transfer.status != TransactionStatus.REVERSED.value,
            )
        )
        or 0
    )
    if unreversed:
        raise AppError(
            f"Investment has {unreversed} unreversed linked transfer(s); "
            "reverse them first (fund reversals adjust the principal)",
            status_code=409,
            error_code="INVESTMENT_HAS_TRANSFERS",
        )
    before = _audit_data(investment)
    # Link rows keep plain FKs (they are audit-relevant), so remove them
    # explicitly; tag links and holdings cascade at the DB level.
    await session.execute(
        delete(InvestmentTransfer).where(InvestmentTransfer.investment_id == investment.id)
    )
    await session.delete(investment)
    write_audit(
        session,
        household_id=household.id,
        action="investment.delete",
        entity_type="investment",
        entity_id=investment.id,
        before=before,
    )
    await session.commit()


async def list_investments(
    session: AsyncSession,
    household: Household,
    pagination: Pagination,
    *,
    status: str | None = None,
    investment_type: str | None = None,
    tag_id: UUID | None = None,
    account_id: UUID | None = None,
) -> tuple[list[Investment], int]:
    filters = [Investment.household_id == household.id]
    today = household_today(household)

    if status == InvestmentStatus.REDEEMED.value:
        filters.append(Investment.status == InvestmentStatus.REDEEMED.value)
    elif status == "matured":
        filters.extend(
            [
                Investment.status == InvestmentStatus.ACTIVE.value,
                Investment.end_date.is_not(None),
                Investment.end_date <= today,
            ]
        )
    elif status == InvestmentStatus.ACTIVE.value:
        filters.append(Investment.status == InvestmentStatus.ACTIVE.value)
        filters.append((Investment.end_date.is_(None)) | (Investment.end_date > today))
    elif status is not None:
        raise AppError(
            "status must be one of active, matured, redeemed",
            status_code=422,
            error_code="VALIDATION_ERROR",
        )

    if investment_type is not None:
        filters.append(Investment.investment_type == investment_type)
    if account_id is not None:
        filters.append(Investment.account_id == account_id)
    if tag_id is not None:
        filters.append(
            Investment.id.in_(
                select(InvestmentTagLink.investment_id).where(InvestmentTagLink.tag_id == tag_id)
            )
        )

    total = await session.scalar(select(func.count()).select_from(Investment).where(*filters)) or 0
    column, descending = resolve_sort(
        pagination.sort_by, pagination.sort_order, _SORTABLE, "created_at"
    )
    stmt = (
        select(Investment)
        .where(*filters)
        .order_by(column.desc() if descending else column.asc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return list((await session.scalars(stmt)).all()), int(total)


async def holdings_cost(session: AsyncSession, investment_id: UUID) -> Decimal:
    total = await session.scalar(
        select(func.sum(Holding.quantity * Holding.cost_price)).where(
            Holding.investment_id == investment_id
        )
    )
    return quantize_money(total or Decimal("0"))


async def tag_ids_for(session: AsyncSession, investment_ids: list[UUID]) -> dict[UUID, list[UUID]]:
    if not investment_ids:
        return {}
    rows = (
        await session.execute(
            select(InvestmentTagLink.investment_id, InvestmentTagLink.tag_id).where(
                InvestmentTagLink.investment_id.in_(investment_ids)
            )
        )
    ).all()
    mapping: dict[UUID, list[UUID]] = {}
    for investment_id, tag_id in rows:
        mapping.setdefault(investment_id, []).append(tag_id)
    return mapping
