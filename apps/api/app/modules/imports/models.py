"""system.import_batches / system.import_rows (Phase 2B-1 sync skeleton)."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_IMPORT_STATUSES = (
    "'uploaded', 'mapped', 'previewed', 'confirmed', 'processing', "
    "'completed', 'partial', 'failed', 'cancelled', 'expired'"
)
_ROW_STATUSES = "'pending', 'valid', 'invalid', 'duplicate', 'imported', 'skipped'"


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint(f"status IN ({_IMPORT_STATUSES})", name="status_valid"),
        CheckConstraint("source_format IN ('csv', 'xlsx')", name="source_format_valid"),
        Index("ix_import_batches_household_created", "household_id", "created_at"),
        Index("ix_import_batches_status", "status"),
        Index("ix_import_batches_file_sha", "household_id", "file_sha256"),
        {"schema": "system"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("core.households.id"), nullable=False
    )
    account_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("core.accounts.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    source_format: Mapped[str] = mapped_column(String(10), nullable=False, default="csv")
    original_filename: Mapped[str | None] = mapped_column(String(255))
    stored_path: Mapped[str | None] = mapped_column(Text)
    file_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    columns: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    mapping: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    mapping_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportRow(Base):
    __tablename__ = "import_rows"
    __table_args__ = (
        CheckConstraint(f"status IN ({_ROW_STATUSES})", name="status_valid"),
        UniqueConstraint("batch_id", "row_number", name="uq_import_rows_batch_row"),
        Index("ix_import_rows_batch_status", "batch_id", "status"),
        Index("ix_import_rows_batch_hash", "batch_id", "row_hash"),
        Index("ix_import_rows_transaction", "transaction_id"),
        {"schema": "system"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("system.import_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_data: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    normalized_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    row_hash: Mapped[str | None] = mapped_column(CHAR(64))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    transaction_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("finance.transactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    duplicate_of_transaction_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("finance.transactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
