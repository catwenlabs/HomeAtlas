"""phase 2c-1: exchange rates, credit accounts, net worth snapshots

Revision ID: 0005_phase_2c_1
Revises: 0004_phase_2a_users
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_phase_2c_1"
down_revision: str | None = "0004_phase_2a_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exchange_rates",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("core.households.id"),
            nullable=False,
        ),
        sa.Column(
            "base_currency",
            sa.CHAR(3),
            sa.ForeignKey("core.currencies.code"),
            nullable=False,
        ),
        sa.Column(
            "quote_currency",
            sa.CHAR(3),
            sa.ForeignKey("core.currencies.code"),
            nullable=False,
        ),
        sa.Column("rate", sa.Numeric(24, 12), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
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
        sa.CheckConstraint("rate > 0", name="rate_positive"),
        sa.CheckConstraint("base_currency <> quote_currency", name="pair_distinct"),
        sa.CheckConstraint("source IN ('manual', 'import', 'system')", name="source_valid"),
        sa.UniqueConstraint(
            "household_id",
            "base_currency",
            "quote_currency",
            "rate_date",
            name="uq_exchange_rates_pair_date",
        ),
        schema="finance",
    )
    op.create_index(
        "ix_exchange_rates_household_date",
        "exchange_rates",
        ["household_id", "rate_date"],
        schema="finance",
    )

    # credit / investment account types (asset-design section 4.2)
    op.drop_constraint("account_type_valid", "accounts", schema="core", type_="check")
    op.create_check_constraint(
        "account_type_valid",
        "accounts",
        "account_type IN ('bank', 'cash', 'wallet', 'other', 'credit', 'investment')",
        schema="core",
    )
    op.add_column(
        "accounts",
        sa.Column("annual_rate", sa.Numeric(12, 8), nullable=True),
        schema="core",
    )
    op.create_check_constraint(
        "annual_rate_non_negative",
        "accounts",
        "annual_rate IS NULL OR annual_rate >= 0",
        schema="core",
    )
    op.add_column(
        "accounts",
        sa.Column("liquidity", sa.String(10), nullable=True),
        schema="core",
    )
    op.create_check_constraint(
        "liquidity_valid",
        "accounts",
        "liquidity IS NULL OR liquidity IN ('none', 'T0', 'T1', 'T2', 'T3')",
        schema="core",
    )
    op.add_column(
        "accounts",
        sa.Column("credit_limit", sa.Numeric(24, 8), nullable=True),
        schema="core",
    )
    op.create_check_constraint(
        "credit_limit_non_negative",
        "accounts",
        "credit_limit IS NULL OR credit_limit >= 0",
        schema="core",
    )

    op.create_table(
        "net_worth_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("core.households.id"),
            nullable=False,
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("base_currency", sa.CHAR(3), nullable=False),
        sa.Column("total_cash", sa.Numeric(24, 8), nullable=False),
        sa.Column("total_invested", sa.Numeric(24, 8), nullable=False),
        sa.Column("total_liabilities", sa.Numeric(24, 8), nullable=False),
        sa.Column("net_worth", sa.Numeric(24, 8), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(24, 8), nullable=False),
        sa.Column("unmapped_cash", sa.Numeric(24, 8), nullable=False),
        sa.Column("daily_interest_income", sa.Numeric(24, 8), nullable=False),
        sa.Column("daily_interest_expense", sa.Numeric(24, 8), nullable=False),
        sa.Column(
            "currency_breakdown",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "fx_rates_used",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
        sa.UniqueConstraint(
            "household_id",
            "snapshot_date",
            name="uq_net_worth_snapshots_household_date",
        ),
        schema="finance",
    )
    op.create_index(
        "ix_net_worth_snapshots_household_date",
        "net_worth_snapshots",
        ["household_id", "snapshot_date"],
        schema="finance",
    )


def downgrade() -> None:
    op.drop_table("net_worth_snapshots", schema="finance")
    op.drop_constraint("credit_limit_non_negative", "accounts", schema="core", type_="check")
    op.drop_column("accounts", "credit_limit", schema="core")
    op.drop_constraint("liquidity_valid", "accounts", schema="core", type_="check")
    op.drop_column("accounts", "liquidity", schema="core")
    op.drop_constraint("annual_rate_non_negative", "accounts", schema="core", type_="check")
    op.drop_column("accounts", "annual_rate", schema="core")
    op.drop_constraint("account_type_valid", "accounts", schema="core", type_="check")
    op.create_check_constraint(
        "account_type_valid",
        "accounts",
        "account_type IN ('bank', 'cash', 'wallet', 'other')",
        schema="core",
    )
    op.drop_table("exchange_rates", schema="finance")
