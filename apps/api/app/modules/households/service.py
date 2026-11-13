"""Household use cases."""

from datetime import date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.core.serialization import jsonable
from app.modules.audit.service import write_audit
from app.modules.currencies.service import get_currency
from app.modules.households.models import Household
from app.modules.households.schemas import HouseholdUpdate
from app.modules.transactions.models import Transaction
from app.modules.transfers.models import Transfer


def household_today(household: Household) -> date:
    """Calendar date right now in the household's timezone."""
    return datetime.now(ZoneInfo(str(household.timezone).strip())).date()


def _audit_data(household: Household) -> dict[str, Any]:
    return {
        "name": household.name,
        "base_currency": household.base_currency,
        "timezone": household.timezone,
    }


async def get_household(session: AsyncSession, household_id: UUID) -> Household:
    household = await session.get(Household, household_id)
    if household is None:
        raise NotFoundError("Household not found", error_code="HOUSEHOLD_NOT_FOUND")
    return household


async def update_household(
    session: AsyncSession,
    household_id: UUID,
    payload: HouseholdUpdate,
    *,
    actor: str | None = None,
) -> Household:
    household = await get_household(session, household_id)
    changes = payload.model_dump(exclude_unset=True)
    before = _audit_data(household)

    new_base_currency = changes.get("base_currency")
    if new_base_currency is not None and new_base_currency != household.base_currency:
        await get_currency(session, new_base_currency)
        transactions = await session.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.household_id == household_id)
        )
        transfers = await session.scalar(
            select(func.count()).select_from(Transfer).where(Transfer.household_id == household_id)
        )
        if (transactions or 0) + (transfers or 0) > 0:
            raise AppError(
                "base_currency cannot change after transactions or transfers exist",
                status_code=409,
                error_code="BASE_CURRENCY_LOCKED",
            )
        household.base_currency = new_base_currency

    for field in ("name", "timezone"):
        value = changes.get(field)
        if value is not None:
            setattr(household, field, value)

    after = _audit_data(household)
    if before != after:
        write_audit(
            session,
            household_id=household.id,
            action="household.update",
            entity_type="household",
            entity_id=household.id,
            before=before,
            after=jsonable(after),
            actor=actor,
        )
    await session.commit()
    await session.refresh(household)
    return household
