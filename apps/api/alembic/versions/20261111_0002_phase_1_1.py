"""phase 1.1: business tables and seed data

Revision ID: 0002_phase_1_1
Revises: 0001_initial
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_phase_1_1"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "currencies",
        sa.Column("code", sa.CHAR(3), primary_key=True, nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("decimal_places", sa.SmallInteger(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint(
            "decimal_places >= 0 AND decimal_places <= 8", name="decimal_places_range"
        ),
        schema="core",
    )

    op.create_table(
        "households",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "base_currency",
            sa.CHAR(3),
            sa.ForeignKey("core.currencies.code"),
            nullable=False,
            server_default=sa.text("'CNY'"),
        ),
        sa.Column(
            "timezone",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'Asia/Shanghai'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="core",
    )

    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("core.households.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("institution", sa.String(100), nullable=True),
        sa.Column("account_type", sa.String(30), nullable=False),
        sa.Column("currency", sa.CHAR(3), sa.ForeignKey("core.currencies.code"), nullable=False),
        sa.Column("external_ref", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "account_type IN ('bank', 'cash', 'wallet', 'other')",
            name="account_type_valid",
        ),
        schema="core",
    )
    op.create_index(
        "ix_accounts_household_active", "accounts", ["household_id", "is_active"], schema="core"
    )

    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("core.households.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("category_type", sa.String(20), nullable=False),
        sa.Column(
            "parent_id",
            sa.Uuid(),
            sa.ForeignKey("finance.categories.id"),
            nullable=True,
        ),
        sa.Column("icon", sa.String(50), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name="parent_not_self"),
        sa.CheckConstraint("category_type IN ('income', 'expense')", name="category_type_valid"),
        schema="finance",
    )
    op.create_index(
        "ix_categories_household_type",
        "categories",
        ["household_id", "category_type"],
        schema="finance",
    )
    op.create_index("ix_categories_parent", "categories", ["parent_id"], schema="finance")

    op.create_table(
        "transfers",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("core.households.id"),
            nullable=False,
        ),
        sa.Column(
            "from_account_id",
            sa.Uuid(),
            sa.ForeignKey("core.accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "to_account_id",
            sa.Uuid(),
            sa.ForeignKey("core.accounts.id"),
            nullable=False,
        ),
        sa.Column("from_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column(
            "from_currency", sa.CHAR(3), sa.ForeignKey("core.currencies.code"), nullable=False
        ),
        sa.Column("to_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("to_currency", sa.CHAR(3), sa.ForeignKey("core.currencies.code"), nullable=False),
        sa.Column("exchange_rate", sa.Numeric(24, 12), nullable=False),
        sa.Column("base_amount", sa.Numeric(24, 8), nullable=True),
        sa.Column(
            "base_currency", sa.CHAR(3), sa.ForeignKey("core.currencies.code"), nullable=True
        ),
        sa.Column("fee", sa.Numeric(24, 8), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "fee_currency", sa.CHAR(3), sa.ForeignKey("core.currencies.code"), nullable=False
        ),
        sa.Column("transfer_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "reverses_transfer_id",
            sa.Uuid(),
            sa.ForeignKey("finance.transfers.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "from_account_id <> to_account_id OR from_currency <> to_currency",
            name="transfer_source_differs",
        ),
        sa.CheckConstraint("fee >= 0", name="fee_non_negative"),
        sa.CheckConstraint("status IN ('draft', 'confirmed', 'reversed')", name="status_valid"),
        schema="finance",
    )
    op.create_index(
        "ix_transfers_household_date",
        "transfers",
        ["household_id", "transfer_date"],
        schema="finance",
    )
    op.create_index("ix_transfers_from_account", "transfers", ["from_account_id"], schema="finance")
    op.create_index("ix_transfers_to_account", "transfers", ["to_account_id"], schema="finance")
    op.create_index("ix_transfers_status", "transfers", ["status"], schema="finance")

    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("core.households.id"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("core.accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "category_id",
            sa.Uuid(),
            sa.ForeignKey("finance.categories.id"),
            nullable=True,
        ),
        sa.Column("transaction_type", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("currency", sa.CHAR(3), sa.ForeignKey("core.currencies.code"), nullable=False),
        sa.Column("base_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column(
            "base_currency", sa.CHAR(3), sa.ForeignKey("core.currencies.code"), nullable=False
        ),
        sa.Column("exchange_rate", sa.Numeric(24, 12), nullable=False),
        sa.Column("exchange_rate_date", sa.Date(), nullable=False),
        sa.Column("transaction_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "reverses_transaction_id",
            sa.Uuid(),
            sa.ForeignKey("finance.transactions.id"),
            nullable=True,
        ),
        sa.Column(
            "transfer_id",
            sa.Uuid(),
            sa.ForeignKey("finance.transfers.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "transaction_type IN ('income', 'expense', 'opening_balance')",
            name="transaction_type_valid",
        ),
        sa.CheckConstraint("status IN ('draft', 'confirmed', 'reversed')", name="status_valid"),
        sa.CheckConstraint("source IN ('manual', 'system', 'import')", name="source_valid"),
        sa.CheckConstraint(
            "amount > 0 OR transaction_type = 'opening_balance'",
            name="amount_positive_except_opening",
        ),
        schema="finance",
    )
    op.create_index(
        "ix_transactions_household_date",
        "transactions",
        ["household_id", "transaction_date"],
        schema="finance",
    )
    op.create_index(
        "ix_transactions_account_date",
        "transactions",
        ["account_id", "transaction_date"],
        schema="finance",
    )
    op.create_index("ix_transactions_category", "transactions", ["category_id"], schema="finance")
    op.create_index("ix_transactions_status", "transactions", ["status"], schema="finance")
    op.create_index("ix_transactions_transfer", "transactions", ["transfer_id"], schema="finance")

    op.create_table(
        "account_balances",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("core.accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("currency", sa.CHAR(3), sa.ForeignKey("core.currencies.code"), nullable=False),
        sa.Column("balance", sa.Numeric(24, 8), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("source IN ('manual', 'bank')", name="balance_source_valid"),
        sa.UniqueConstraint(
            "account_id",
            "currency",
            "snapshot_at",
            "source",
            name="account_currency_snapshot_source",
        ),
        schema="core",
    )
    op.create_index(
        "ix_account_balances_account_currency",
        "account_balances",
        ["account_id", "currency"],
        schema="core",
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("core.households.id"),
            nullable=True,
        ),
        sa.Column("actor", sa.String(100), nullable=False, server_default=sa.text("'system'")),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("before_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="system",
    )


def downgrade() -> None:
    op.drop_table("audit_logs", schema="system")
    op.drop_table("account_balances", schema="core")
    op.drop_table("transactions", schema="finance")
    op.drop_table("transfers", schema="finance")
    op.drop_table("categories", schema="finance")
    op.drop_table("accounts", schema="core")
    op.drop_table("households", schema="core")
    op.drop_table("currencies", schema="core")
