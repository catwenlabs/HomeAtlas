"""phase 2c-3: loans

Revision ID: 0007_phase_2c_3
Revises: 0006_phase_2c_2
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_phase_2c_3"
down_revision: str | None = "0006_phase_2c_2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "loans",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("core.households.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("institution", sa.String(100), nullable=True),
        sa.Column("principal", sa.Numeric(24, 8), nullable=False),
        sa.Column(
            "currency",
            sa.CHAR(3),
            sa.ForeignKey("core.currencies.code"),
            nullable=False,
        ),
        sa.Column("annual_rate", sa.Numeric(12, 8), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("due_day", sa.SmallInteger(), nullable=True),
        sa.Column("repayment_type", sa.String(30), nullable=False),
        sa.Column(
            "linked_account_id",
            sa.Uuid(),
            sa.ForeignKey("core.accounts.id"),
            nullable=True,
        ),
        sa.Column("remaining_principal", sa.Numeric(24, 8), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("settled_date", sa.Date(), nullable=True),
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
        sa.CheckConstraint("principal > 0", name="principal_positive"),
        sa.CheckConstraint("annual_rate >= 0", name="rate_non_negative"),
        sa.CheckConstraint("due_day IS NULL OR due_day BETWEEN 1 AND 31", name="due_day_range"),
        sa.CheckConstraint(
            "repayment_type IN ('monthly_interest', 'one_time')",
            name="repayment_type_valid",
        ),
        sa.CheckConstraint("remaining_principal >= 0", name="remaining_non_negative"),
        sa.CheckConstraint("status IN ('active', 'settled')", name="status_valid"),
        sa.CheckConstraint("remaining_principal <= principal", name="remaining_within_principal"),
        sa.Index("ix_loans_household_status", "household_id", "status"),
        schema="finance",
    )


def downgrade() -> None:
    op.drop_table("loans", schema="finance")
