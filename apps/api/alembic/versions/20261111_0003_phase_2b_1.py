"""phase 2b-1: import batches and rows (sync skeleton)

Revision ID: 0003_phase_2b_1
Revises: 0002_phase_1_1
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_phase_2b_1"
down_revision: str | None = "0002_phase_1_1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_batches",
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
            nullable=True,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="uploaded"),
        sa.Column("source_format", sa.String(10), nullable=False, server_default="csv"),
        sa.Column("original_filename", sa.String(255), nullable=True),
        sa.Column("stored_path", sa.Text(), nullable=True),
        sa.Column("file_sha256", sa.CHAR(64), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "columns",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("mapping", postgresql.JSONB(), nullable=True),
        sa.Column("mapping_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('uploaded', 'mapped', 'previewed', 'confirmed', "
            "'processing', 'completed', 'partial', 'failed', 'cancelled', 'expired')",
            name="status_valid",
        ),
        sa.CheckConstraint("source_format IN ('csv', 'xlsx')", name="source_format_valid"),
        schema="system",
    )
    op.create_index(
        "ix_import_batches_household_created",
        "import_batches",
        ["household_id", "created_at"],
        schema="system",
    )
    op.create_index(
        "ix_import_batches_status",
        "import_batches",
        ["status"],
        schema="system",
    )
    op.create_index(
        "ix_import_batches_file_sha",
        "import_batches",
        ["household_id", "file_sha256"],
        schema="system",
    )

    op.create_table(
        "import_rows",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "batch_id",
            sa.Uuid(),
            sa.ForeignKey("system.import_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column(
            "raw_data",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("normalized_data", postgresql.JSONB(), nullable=True),
        sa.Column("row_hash", sa.CHAR(64), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "errors",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "transaction_id",
            sa.Uuid(),
            sa.ForeignKey("finance.transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "duplicate_of_transaction_id",
            sa.Uuid(),
            sa.ForeignKey("finance.transactions.id", ondelete="SET NULL"),
            nullable=True,
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
        sa.CheckConstraint(
            "status IN ('pending', 'valid', 'invalid', 'duplicate', 'imported', 'skipped')",
            name="status_valid",
        ),
        sa.UniqueConstraint("batch_id", "row_number", name="uq_import_rows_batch_row"),
        schema="system",
    )
    op.create_index(
        "ix_import_rows_batch_status",
        "import_rows",
        ["batch_id", "status"],
        schema="system",
    )
    op.create_index(
        "ix_import_rows_batch_hash",
        "import_rows",
        ["batch_id", "row_hash"],
        schema="system",
    )
    op.create_index(
        "ix_import_rows_transaction",
        "import_rows",
        ["transaction_id"],
        schema="system",
    )


def downgrade() -> None:
    op.drop_table("import_rows", schema="system")
    op.drop_table("import_batches", schema="system")
