"""Holdings view: computed from the trade ledger (see trades.py).

Historically this module stored position snapshots directly. Now the
`trades` table is the source of truth and everything here is derived:
`list_holdings` replays trades into open positions, `refresh_value`
fetches quotes for those positions. The response shape is unchanged so
the web layer keeps working.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_OID, UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.money import quantize_money
from app.modules.audit.service import write_audit
from app.modules.investments import flows
from app.modules.investments import service as investment_service
from app.modules.investments import trades as trade_service
from app.modules.market import service as market_service
from app.modules.market.provider import quote_key


def _position_id(investment_id: UUID, market: str, symbol: str) -> UUID:
    """Deterministic id per open position (stable React keys, audit refs)."""
    return uuid5(NAMESPACE_OID, f"holding:{investment_id}:{market}:{symbol}")


async def list_holdings(
    session: AsyncSession, household: Any, investment_id: UUID
) -> list[dict[str, Any]]:
    """Open positions derived from trades (closed positions are omitted)."""
    investment = await investment_service.get_investment(session, household.id, investment_id)
    positions = await trade_service.positions(session, investment)
    now = datetime.now(UTC)
    items = []
    for p in positions:
        if p["closed"]:
            continue
        items.append(
            {
                "id": _position_id(investment.id, p["market"], p["symbol"]),
                "investment_id": investment.id,
                "market": p["market"],
                "symbol": p["symbol"],
                "quantity": p["quantity"],
                "cost_price": p["cost_price"],
                "cost_subtotal": p["cost_subtotal"],
                "remark": p["remark"],
                "created_at": now,
                "updated_at": now,
            }
        )
    return items


def holding_cost(row: dict[str, Any]) -> Decimal:
    return quantize_money(Decimal(str(row["quantity"])) * Decimal(str(row["cost_price"])))


def total_cost(rows: list[dict[str, Any]]) -> Decimal:
    return quantize_money(sum((holding_cost(row) for row in rows), Decimal("0")))


async def refresh_value(
    session: AsyncSession,
    household: Any,
    investment_id: UUID,
) -> dict[str, Any]:
    """Fetch quotes for every open position and write current_value (audited)."""
    investment = await investment_service.get_investment(session, household.id, investment_id)
    flows.ensure_active(investment)
    positions = await trade_service.positions(session, investment)
    holdings = [p for p in positions if not p["closed"]]
    if not holdings:
        raise AppError(
            "The investment has no open positions to value",
            status_code=422,
            error_code="HOLDING_NOT_FOUND",
        )
    refs = [(p["market"], p["symbol"]) for p in holdings]
    quotes = await market_service.fetch_quotes(refs)

    items: list[dict[str, Any]] = []
    total = Decimal("0")
    for p in holdings:
        quote = quotes[quote_key(p["market"], p["symbol"])]
        market_service.validate_quote_currency(quote)
        subtotal = market_service.money(Decimal(str(p["quantity"])) * quote.price)
        total += subtotal
        items.append(
            {
                "market": p["market"],
                "symbol": p["symbol"],
                "name": quote.name,
                "quantity": str(p["quantity"]),
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
