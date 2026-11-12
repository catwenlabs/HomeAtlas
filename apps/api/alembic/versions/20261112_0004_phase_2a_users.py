"""phase 2a: household users and JWT authentication

Revision ID: 0004_phase_2a_users
Revises: 0003_phase_2b_1
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_phase_2a_users"
down_revision: str | None = "0003_phase_2b_1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("core.households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("username", sa.String(50), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default=sa.text("'member'")),
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
        sa.CheckConstraint("role IN ('owner', 'member')", name="ck_users_role_valid"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        schema="core",
    )
    op.create_index("ix_users_household_id", "users", ["household_id"], schema="core")

    # Remove the legacy default household only if it never received business
    # data. Its audit/import rows reference the household without ON DELETE
    # CASCADE, so they must be removed first or the delete would fail.
    legacy_guard = """
        household_id = '00000000-0000-0000-0000-000000000001'
        AND NOT EXISTS (
            SELECT 1 FROM core.accounts
            WHERE household_id = '00000000-0000-0000-0000-000000000001'
        )
        AND NOT EXISTS (
            SELECT 1 FROM finance.transactions
            WHERE household_id = '00000000-0000-0000-0000-000000000001'
        )
        AND NOT EXISTS (
            SELECT 1 FROM finance.transfers
            WHERE household_id = '00000000-0000-0000-0000-000000000001'
        )
    """
    op.execute(sa.text(f"DELETE FROM system.import_batches WHERE {legacy_guard}"))  # noqa: S608
    op.execute(sa.text(f"DELETE FROM system.audit_logs WHERE {legacy_guard}"))  # noqa: S608
    op.execute(sa.text(f"DELETE FROM finance.categories WHERE {legacy_guard}"))  # noqa: S608
    op.execute(
        sa.text(
            """
            DELETE FROM core.households
            WHERE id = '00000000-0000-0000-0000-000000000001'
              AND NOT EXISTS (
                  SELECT 1 FROM core.accounts
                  WHERE household_id = '00000000-0000-0000-0000-000000000001'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM finance.transactions
                  WHERE household_id = '00000000-0000-0000-0000-000000000001'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM finance.transfers
                  WHERE household_id = '00000000-0000-0000-0000-000000000001'
              )
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_users_household_id", table_name="users", schema="core")
    op.drop_table("users", schema="core")
