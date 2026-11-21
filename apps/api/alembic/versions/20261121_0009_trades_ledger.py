"""trades ledger: append-only trade history; holdings become derived views

Revision ID: 0009_trades_ledger
Revises: 0008_force_managed
Create Date: 2026-11-21

Creates finance.trades (append-only securities trade ledger) and backfills
every existing finance.holdings row into one opening buy trade, so positions
computed from the ledger match the previous stored snapshots. The holdings
table is kept (no longer written by the API) until a later cleanup release.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_trades_ledger"
down_revision: str | None = "0008_force_managed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trades",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("core.households.id"),
            nullable=False,
        ),
        sa.Column(
            "investment_id",
            sa.Uuid(),
            sa.ForeignKey("finance.investments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("market", sa.String(10), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("price", sa.Numeric(24, 8), nullable=False),
        sa.Column("fee", sa.Numeric(24, 8), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("remark", sa.String(500)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="side_valid"),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
        sa.CheckConstraint("price >= 0", name="price_non_negative"),
        sa.CheckConstraint("fee >= 0", name="fee_non_negative"),
        sa.CheckConstraint("market IN ('SH', 'SZ', 'HK', 'US')", name="market_valid"),
        sa.Index("ix_trades_household", "household_id"),
        schema="finance",
    )

    # Backfill: one opening buy trade per existing holdings snapshot.
    op.execute(
        """
        INSERT INTO finance.trades (
            id, household_id, investment_id, market, symbol, side,
            quantity, price, fee, trade_date, source,
            created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            h.household_id,
            h.investment_id,
            h.market,
            h.symbol,
            'buy',
            h.quantity,
            h.cost_price,
            0,
            h.created_at::date,
            'opening',
            h.created_at,
            now()
        FROM finance.holdings h
        """
    )


def downgrade() -> None:
    op.drop_table("trades", schema="finance")
