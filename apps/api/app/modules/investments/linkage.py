"""Reversal linkage between transfers and investments (asset-design 4.6).

Called from transfers.service.reverse_transfer inside the same transaction:
reversing a fund transfer decrements the investment principal, reversing a
redeem transfer rolls the investment back to its pre-redeem state.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import InvestmentLinkDirection, InvestmentStatus
from app.core.exceptions import AppError
from app.modules.audit.service import write_audit
from app.modules.households.models import Household
from app.modules.investments.models import Investment, InvestmentTransfer
from app.modules.transfers.models import Transfer


async def get_link(session: AsyncSession, transfer_id: uuid.UUID) -> InvestmentTransfer | None:
    return await session.scalar(
        select(InvestmentTransfer).where(InvestmentTransfer.transfer_id == transfer_id)
    )


async def _investment(session: AsyncSession, link: InvestmentTransfer) -> Investment:
    investment = await session.scalar(select(Investment).where(Investment.id == link.investment_id))
    if investment is None:  # pragma: no cover - FK guarantees existence
        raise AppError(
            "Linked investment no longer exists",
            status_code=409,
            error_code="INVESTMENT_NOT_FOUND",
        )
    return investment


async def apply_reversal_linkage(
    session: AsyncSession,
    household: Household,
    original: Transfer,
) -> None:
    """Mutate the linked investment when its transfer is being reversed.

    Must run before any reversal rows are written so a rejection aborts
    the whole reversal with no partial state.
    """
    link = await get_link(session, original.id)
    if link is None:
        return
    investment = await _investment(session, link)

    if link.direction == InvestmentLinkDirection.FUND.value:
        if investment.status != InvestmentStatus.ACTIVE.value:
            raise AppError(
                "The investment is already redeemed; reverse the redeem "
                "transfer before reversing its funding",
                status_code=409,
                error_code="TRANSFER_LINKED_TO_INVESTMENT",
            )
        decremented = investment.principal - original.to_amount
        if decremented < 0:
            raise AppError(
                "Reversing this fund transfer would drive the investment "
                "principal below zero; reverse the redeem transfer first",
                status_code=409,
                error_code="TRANSFER_LINKED_TO_INVESTMENT",
            )
        before: dict[str, Any] = {
            "principal": str(investment.principal),
            "current_value": str(investment.current_value),
        }
        investment.principal = decremented
        # The funding seeded current_value from the principal (5.2 / §15):
        # the cost basis leaves with the cash, user-asserted markup stays,
        # floored at zero to respect the column constraint.
        investment.current_value = max(investment.current_value - original.to_amount, Decimal("0"))
        write_audit(
            session,
            household_id=household.id,
            action="investment.fund_reverse",
            entity_type="investment",
            entity_id=investment.id,
            before=before,
            after={
                "principal": str(investment.principal),
                "current_value": str(investment.current_value),
            },
        )
        return

    # direction == redeem: restore the pre-redeem state; the derived PnL
    # rows are reversed by the generic transfer-derived mechanism.
    before_state: dict[str, Any] = {
        "status": investment.status,
        "realized_pnl": (
            str(investment.realized_pnl) if investment.realized_pnl is not None else None
        ),
        "current_value": str(investment.current_value),
    }
    pre_redeem = investment.pre_redeem_value or Decimal("0")
    investment.status = InvestmentStatus.ACTIVE.value
    investment.realized_pnl = None
    investment.pre_redeem_value = None
    investment.current_value = pre_redeem
    write_audit(
        session,
        household_id=household.id,
        action="investment.redeem_reverse",
        entity_type="investment",
        entity_id=investment.id,
        before=before_state,
        after={
            "status": investment.status,
            "current_value": str(investment.current_value),
        },
    )
