"""Trade ledger: append-only securities trades; positions are derived here.

Design: the `trades` table is the single source of truth for stock/fund
positions. Quantity, weighted-average cost, cost subtotal, and realized PnL
are all computed by replaying trades in chronological order — never stored.
A position may legitimately sit at zero (fully closed); its history remains.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.core.money import quantize_amount, quantize_money
from app.modules.audit.service import write_audit
from app.modules.currencies.service import get_currency
from app.modules.investments import flows
from app.modules.investments import service as investment_service
from app.modules.investments.models import Investment, Trade
from app.modules.investments.schemas import TradeCreate
from app.modules.market.provider import MARKET_CURRENCY

HOLDING_TYPES = ("stock", "fund")

ZERO = Decimal("0")


async def get_trade(session: AsyncSession, investment_id: UUID, trade_id: UUID) -> Trade:
    trade = await session.scalar(
        select(Trade).where(Trade.id == trade_id, Trade.investment_id == investment_id)
    )
    if trade is None:
        raise NotFoundError("Trade not found", error_code="TRADE_NOT_FOUND")
    return trade


async def list_trades(session: AsyncSession, household: Any, investment_id: UUID) -> list[Trade]:
    investment = await investment_service.get_investment(session, household.id, investment_id)
    return list(
        (
            await session.scalars(
                select(Trade)
                .where(Trade.investment_id == investment.id)
                .order_by(Trade.trade_date.asc(), Trade.created_at.asc())
            )
        ).all()
    )


async def create_trade(
    session: AsyncSession,
    household: Any,
    investment_id: UUID,
    payload: TradeCreate,
) -> Trade:
    investment = await investment_service.get_investment(session, household.id, investment_id)
    _ensure_trades_supported(investment, payload.market.value)
    currency = await get_currency(session, str(investment.currency).strip())

    symbol = payload.symbol.upper()
    trade_date = payload.trade_date or date.today()

    # A sell may close a position to exactly zero but never go negative.
    if payload.side.value == "sell":
        current_qty = await position_quantity(session, investment.id, payload.market.value, symbol)
        if payload.quantity > current_qty:
            raise AppError(
                f"Cannot sell {payload.quantity} {symbol}: position is only {current_qty}",
                status_code=422,
                error_code="TRADE_INSUFFICIENT_POSITION",
            )

    trade = Trade(
        household_id=household.id,
        investment_id=investment.id,
        market=payload.market.value,
        symbol=symbol,
        side=payload.side.value,
        quantity=quantize_amount(payload.quantity, 8),
        price=quantize_amount(payload.price, currency.decimal_places),
        fee=quantize_amount(payload.fee, currency.decimal_places),
        trade_date=trade_date,
        source=payload.source or "manual",
        remark=payload.remark,
    )
    session.add(trade)
    await session.flush()
    write_audit(
        session,
        household_id=household.id,
        action="investment.trade.create",
        entity_type="trade",
        entity_id=trade.id,
        after=_trade_audit(trade),
    )
    await session.commit()
    await session.refresh(trade)
    return trade


async def delete_trade(
    session: AsyncSession, household: Any, investment_id: UUID, trade_id: UUID
) -> None:
    """Remove an erroneous trade; positions recompute from the ledger."""
    investment = await investment_service.get_investment(session, household.id, investment_id)
    flows.ensure_active(investment)
    trade = await get_trade(session, investment.id, trade_id)
    before = _trade_audit(trade)
    await session.delete(trade)
    write_audit(
        session,
        household_id=household.id,
        action="investment.trade.delete",
        entity_type="trade",
        entity_id=trade.id,
        before=before,
    )
    await session.commit()


# ---------------------------------------------------------------- positions


async def _investment_trades(session: AsyncSession, investment_id: UUID) -> list[Trade]:
    return list(
        (
            await session.scalars(
                select(Trade)
                .where(Trade.investment_id == investment_id)
                .order_by(Trade.trade_date.asc(), Trade.created_at.asc())
            )
        ).all()
    )


def replay_positions(trades_list: list[Trade]) -> list[dict[str, Any]]:
    """Replay trades into per-symbol positions (weighted-average cost).

    Returns every symbol ever traded, including fully closed ones
    (quantity == 0, realized_pnl kept). Fee accounting: buy fees are
    capitalized into cost basis; sell fees reduce realized proceeds.
    """
    groups: dict[tuple[str, str], list[Trade]] = {}
    for t in trades_list:
        groups.setdefault((str(t.market).strip(), str(t.symbol).strip()), []).append(t)

    result: list[dict[str, Any]] = []
    for (market, symbol), symbol_trades in groups.items():
        qty = ZERO
        cost_basis = ZERO  # total cost of currently open quantity (fees included)
        avg_cost = ZERO
        realized = ZERO
        for t in symbol_trades:
            if t.side == "buy":
                total_in = quantize_money(t.quantity * t.price + t.fee)
                new_qty = qty + t.quantity
                cost_basis += total_in
                qty = new_qty
                avg_cost = quantize_amount(cost_basis / qty, 8) if qty > 0 else ZERO
            else:  # sell
                sell_qty = min(t.quantity, qty)
                proceeds = quantize_money(sell_qty * t.price - t.fee)
                realized += proceeds - quantize_money(sell_qty * avg_cost)
                qty -= sell_qty
                cost_basis = quantize_money(qty * avg_cost)
        result.append(
            {
                "market": market,
                "symbol": symbol,
                "quantity": quantize_amount(qty, 8),
                "cost_price": avg_cost,
                "cost_subtotal": quantize_money(qty * avg_cost),
                "realized_pnl": quantize_money(realized),
                "closed": qty == 0,
                "trade_count": len(symbol_trades),
                "remark": None,
            }
        )
    result.sort(key=lambda p: (p["market"], p["symbol"]))
    return result


async def position_quantity(
    session: AsyncSession, investment_id: UUID, market: str, symbol: str
) -> Decimal:
    """Current net quantity for one symbol (buys minus sells)."""
    trades = await _investment_trades(session, investment_id)
    qty = ZERO
    for t in trades:
        if t.market == market and t.symbol == symbol:
            qty += t.quantity if t.side == "buy" else -t.quantity
    return qty


async def positions(session: AsyncSession, investment: Investment) -> list[dict[str, Any]]:
    """Replay all trades for one investment into per-symbol positions."""
    return replay_positions(await _investment_trades(session, investment.id))


async def batch_positions(
    session: AsyncSession, investment_ids: list[UUID]
) -> dict[UUID, list[dict[str, Any]]]:
    """Replay trades for multiple investments in one DB round-trip."""
    if not investment_ids:
        return {}
    rows = list(
        (
            await session.scalars(
                select(Trade)
                .where(Trade.investment_id.in_(investment_ids))
                .order_by(Trade.trade_date.asc(), Trade.created_at.asc())
            )
        ).all()
    )
    by_investment: dict[UUID, list[Trade]] = {}
    for trade in rows:
        by_investment.setdefault(trade.investment_id, []).append(trade)
    return {inv_id: replay_positions(inv_trades) for inv_id, inv_trades in by_investment.items()}


def total_cost(rows: list[dict[str, Any]]) -> Decimal:
    """Sum of open-position cost subtotals (closed positions contribute 0)."""
    return quantize_money(sum((r["cost_subtotal"] for r in rows if not r["closed"]), ZERO))


def _ensure_trades_supported(investment: Investment, market: str) -> None:
    flows.ensure_active(investment)
    if investment.investment_type not in HOLDING_TYPES:
        raise AppError(
            "Trades are only supported on stock or fund investments",
            status_code=422,
            error_code="TRADE_NOT_SUPPORTED",
        )
    expected_currency = MARKET_CURRENCY.get(market)
    if expected_currency is None or str(investment.currency).strip() != expected_currency:
        raise AppError(
            f"Market {market} settles in {expected_currency}; the investment "
            f"currency is {str(investment.currency).strip()}",
            status_code=422,
            error_code="HOLDING_CURRENCY_MISMATCH",
        )


def _trade_audit(trade: Trade) -> dict[str, Any]:
    return {
        "market": str(trade.market).strip(),
        "symbol": str(trade.symbol).strip(),
        "side": trade.side,
        "quantity": str(trade.quantity),
        "price": str(trade.price),
        "fee": str(trade.fee),
        "trade_date": str(trade.trade_date),
    }
