"""Holdings (stock/fund position snapshots) and quote-driven valuation."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.core.money import quantize_amount, quantize_money
from app.modules.audit.service import write_audit
from app.modules.currencies.service import get_currency
from app.modules.households.models import Household
from app.modules.investments import flows
from app.modules.investments import service as investment_service
from app.modules.investments.models import Holding, Investment
from app.modules.investments.schemas import (
    HoldingCreate,
    HoldingUpdate,
)
from app.modules.market import service as market_service
from app.modules.market.provider import MARKET_CURRENCY, quote_key

HOLDING_TYPES = ("stock", "fund")


def holding_cost(holding: Holding) -> Decimal:
    """quantity x cost_price quantized to the money scale."""
    return quantize_money(holding.quantity * holding.cost_price)


def total_cost(rows: list[Holding]) -> Decimal:
    """Sum of quantity x cost_price, quantized once at the end."""
    return quantize_money(sum((row.quantity * row.cost_price for row in rows), Decimal("0")))


async def get_holding(session: AsyncSession, investment_id: UUID, holding_id: UUID) -> Holding:
    holding = await session.scalar(
        select(Holding).where(
            Holding.id == holding_id,
            Holding.investment_id == investment_id,
        )
    )
    if holding is None:
        raise NotFoundError("Holding not found", error_code="HOLDING_NOT_FOUND")
    return holding


async def _ensure_holdings_supported(
    session: AsyncSession, household: Household, investment: Investment, market: str
) -> None:
    flows.ensure_active(investment)
    if investment.investment_type not in HOLDING_TYPES:
        raise AppError(
            "Holdings are only supported on stock or fund investments",
            status_code=422,
            error_code="HOLDING_NOT_SUPPORTED",
        )
    expected_currency = MARKET_CURRENCY.get(market)
    if expected_currency is None or str(investment.currency).strip() != expected_currency:
        raise AppError(
            f"Market {market} settles in {expected_currency}; the investment "
            f"currency is {str(investment.currency).strip()}",
            status_code=422,
            error_code="HOLDING_CURRENCY_MISMATCH",
        )


async def create_holding(
    session: AsyncSession,
    household: Household,
    investment_id: UUID,
    payload: HoldingCreate,
) -> Holding:
    investment = await investment_service.get_investment(session, household.id, investment_id)
    await _ensure_holdings_supported(session, household, investment, payload.market.value)
    currency = await get_currency(session, str(investment.currency).strip())
    duplicate = await session.scalar(
        select(Holding.id).where(
            Holding.investment_id == investment.id,
            Holding.market == payload.market.value,
            Holding.symbol == payload.symbol.upper(),
        )
    )
    if duplicate is not None:
        raise AppError(
            f"Holding {payload.market.value}:{payload.symbol} already exists on this investment",
            status_code=409,
            error_code="HOLDING_DUPLICATE",
        )
    holding = Holding(
        household_id=household.id,
        investment_id=investment.id,
        market=payload.market.value,
        symbol=payload.symbol.upper(),
        quantity=quantize_amount(payload.quantity, currency.decimal_places),
        cost_price=quantize_amount(payload.cost_price, currency.decimal_places),
        remark=payload.remark,
    )
    session.add(holding)
    await session.flush()
    write_audit(
        session,
        household_id=household.id,
        action="investment.holding.create",
        entity_type="holding",
        entity_id=holding.id,
        after=_holding_audit(holding),
    )
    await session.commit()
    await session.refresh(holding)
    return holding


async def update_holding(
    session: AsyncSession,
    household: Household,
    investment_id: UUID,
    holding_id: UUID,
    payload: HoldingUpdate,
) -> Holding:
    investment = await investment_service.get_investment(session, household.id, investment_id)
    flows.ensure_active(investment)
    holding = await get_holding(session, investment.id, holding_id)
    before = _holding_audit(holding)
    changes = payload.model_dump(exclude_unset=True)
    currency = await get_currency(session, str(investment.currency).strip())
    if changes.get("quantity") is not None:
        holding.quantity = quantize_amount(changes["quantity"], currency.decimal_places)
    if changes.get("cost_price") is not None:
        holding.cost_price = quantize_amount(changes["cost_price"], currency.decimal_places)
    if "remark" in changes:
        holding.remark = changes["remark"]
    await session.flush()
    write_audit(
        session,
        household_id=household.id,
        action="investment.holding.update",
        entity_type="holding",
        entity_id=holding.id,
        before=before,
        after=_holding_audit(holding),
    )
    await session.commit()
    await session.refresh(holding)
    return holding


async def delete_holding(
    session: AsyncSession,
    household: Household,
    investment_id: UUID,
    holding_id: UUID,
) -> None:
    investment = await investment_service.get_investment(session, household.id, investment_id)
    flows.ensure_active(investment)
    holding = await get_holding(session, investment.id, holding_id)
    before = _holding_audit(holding)
    await session.delete(holding)
    write_audit(
        session,
        household_id=household.id,
        action="investment.holding.delete",
        entity_type="holding",
        entity_id=holding.id,
        before=before,
    )
    await session.commit()


async def list_holdings(
    session: AsyncSession, household: Household, investment_id: UUID
) -> list[Holding]:
    investment = await investment_service.get_investment(session, household.id, investment_id)
    return list(
        (
            await session.scalars(
                select(Holding)
                .where(Holding.investment_id == investment.id)
                .order_by(Holding.created_at.asc(), Holding.market.asc(), Holding.symbol.asc())
            )
        ).all()
    )


async def refresh_value(
    session: AsyncSession,
    household: Household,
    investment_id: UUID,
) -> dict[str, Any]:
    """Fetch quotes for every holding and write current_value (audited)."""
    investment = await investment_service.get_investment(session, household.id, investment_id)
    flows.ensure_active(investment)
    holdings = list(
        (await session.scalars(select(Holding).where(Holding.investment_id == investment.id))).all()
    )
    if not holdings:
        raise AppError(
            "The investment has no holdings to value",
            status_code=422,
            error_code="HOLDING_NOT_FOUND",
        )
    refs = [(str(h.market).strip(), str(h.symbol).strip()) for h in holdings]
    quotes = await market_service.fetch_quotes(refs)

    items: list[dict[str, Any]] = []
    total = Decimal("0")
    for holding in holdings:
        quote = quotes[quote_key(str(holding.market).strip(), str(holding.symbol).strip())]
        market_service.validate_quote_currency(quote)
        subtotal = market_service.money(holding.quantity * quote.price)
        total += subtotal
        items.append(
            {
                "market": holding.market,
                "symbol": holding.symbol,
                "name": quote.name,
                "quantity": str(holding.quantity),
                "price": str(quote.price.normalize()),
                "currency": quote.currency,
                "subtotal": str(subtotal),
            }
        )

    previous = investment.current_value
    investment.current_value = quantize_money(total)
    await session.flush()
    write_audit(
        session,
        household_id=household.id,
        action="investment.value",
        entity_type="investment",
        entity_id=investment.id,
        before={"current_value": str(previous)},
        after={
            "current_value": str(investment.current_value),
            "source": "quote",
            "breakdown": items,
        },
    )
    await session.commit()
    await session.refresh(investment)
    return {
        "current_value": str(investment.current_value),
        "previous_value": str(previous),
        "items": items,
    }


def _holding_audit(holding: Holding) -> dict[str, Any]:
    return {
        "market": str(holding.market).strip(),
        "symbol": str(holding.symbol).strip(),
        "quantity": str(holding.quantity),
        "cost_price": str(holding.cost_price),
    }
