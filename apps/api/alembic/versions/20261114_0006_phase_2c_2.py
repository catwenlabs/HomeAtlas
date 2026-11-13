"""phase 2c-2: investments, tags, holdings, investment-transfer links

Revision ID: 0006_phase_2c_2
Revises: 0005_phase_2c_1
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_phase_2c_2"
down_revision: str | None = "0005_phase_2c_1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "investments",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("core.households.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("investment_type", sa.String(20), nullable=False),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("core.accounts.id"),
            nullable=True,
        ),
        sa.Column("principal", sa.Numeric(24, 8), nullable=False),
        sa.Column("current_value", sa.Numeric(24, 8), nullable=False),
        sa.Column(
            "currency",
            sa.CHAR(3),
            sa.ForeignKey("core.currencies.code"),
            nullable=False,
        ),
        sa.Column("annual_rate", sa.Numeric(12, 8), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("liquidity", sa.String(10), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("realized_pnl", sa.Numeric(24, 8), nullable=True),
        sa.Column("pre_redeem_value", sa.Numeric(24, 8), nullable=True),
        sa.Column("remark", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "investment_type IN ('fixed', 'daily', 'fund', 'cash', 'stock', 'bond', 'other')",
            name="investment_type_valid",
        ),
        sa.CheckConstraint("principal >= 0", name="principal_non_negative"),
        sa.CheckConstraint("current_value >= 0", name="current_value_non_negative"),
        sa.CheckConstraint("status IN ('active', 'redeemed')", name="status_valid"),
        sa.CheckConstraint("annual_rate IS NULL OR annual_rate >= 0", name="rate_ok"),
        sa.CheckConstraint(
            "liquidity IS NULL OR liquidity IN ('none', 'T0', 'T1', 'T2', 'T3')",
            name="liquidity_valid",
        ),
        sa.Index("ix_investments_household_status", "household_id", "status"),
        schema="finance",
    )

    op.create_table(
        "investment_tags",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("core.households.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("color", sa.CHAR(7), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("household_id", "name", name="uq_investment_tags_name"),
        schema="finance",
    )

    op.create_table(
        "investment_tag_links",
        sa.Column(
            "investment_id",
            sa.Uuid(),
            sa.ForeignKey("finance.investments.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tag_id",
            sa.Uuid(),
            sa.ForeignKey("finance.investment_tags.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        schema="finance",
    )

    op.create_table(
        "investment_transfers",
        sa.Column(
            "investment_id",
            sa.Uuid(),
            sa.ForeignKey("finance.investments.id"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "transfer_id",
            sa.Uuid(),
            sa.ForeignKey("finance.transfers.id"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.CheckConstraint("direction IN ('fund', 'redeem')", name="direction_valid"),
        sa.UniqueConstraint("transfer_id", name="uq_investment_transfers_transfer"),
        schema="finance",
    )

    op.create_table(
        "holdings",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
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
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("cost_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("remark", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("market IN ('SH', 'SZ', 'HK', 'US')", name="market_valid"),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
        sa.CheckConstraint("cost_price >= 0", name="cost_price_non_negative"),
        sa.UniqueConstraint("investment_id", "market", "symbol", name="uq_holdings_position"),
        sa.Index("ix_holdings_household", "household_id"),
        schema="finance",
    )


def downgrade() -> None:
    op.drop_table("holdings", schema="finance")
    op.drop_table("investment_transfers", schema="finance")
    op.drop_table("investment_tag_links", schema="finance")
    op.drop_table("investment_tags", schema="finance")
    op.drop_table("investments", schema="finance")
