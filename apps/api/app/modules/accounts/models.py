"""core.accounts and core.account_balances (spec v1.3 sections 4.2, 4.7)."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            "account_type IN ('bank', 'cash', 'wallet', 'other', 'credit', 'investment')",
            name="account_type_valid",
        ),
        CheckConstraint(
            "annual_rate IS NULL OR annual_rate >= 0",
            name="annual_rate_non_negative",
        ),
        CheckConstraint(
            "liquidity IS NULL OR liquidity IN ('none', 'T0', 'T1', 'T2', 'T3')",
            name="liquidity_valid",
        ),
        CheckConstraint(
            "credit_limit IS NULL OR credit_limit >= 0",
            name="credit_limit_non_negative",
        ),
        Index("ix_accounts_household_active", "household_id", "is_active"),
        {"schema": "core"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("core.households.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    institution: Mapped[str | None] = mapped_column(String(100))
    account_type: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(
        CHAR(3), ForeignKey("core.currencies.code"), nullable=False
    )
    external_ref: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    annual_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    liquidity: Mapped[str | None] = mapped_column(String(10))
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AccountBalance(Base):
    """Reconciliation snapshot, never the opening balance (section 4.7)."""

    __tablename__ = "account_balances"
    __table_args__ = (
        CheckConstraint("source IN ('manual', 'bank')", name="balance_source_valid"),
        UniqueConstraint(
            "account_id",
            "currency",
            "snapshot_at",
            "source",
            name="account_currency_snapshot_source",
        ),
        Index("ix_account_balances_account_currency", "account_id", "currency"),
        {"schema": "core"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("core.accounts.id", ondelete="CASCADE"), nullable=False
    )
    currency: Mapped[str] = mapped_column(
        CHAR(3), ForeignKey("core.currencies.code"), nullable=False
    )
    balance: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
