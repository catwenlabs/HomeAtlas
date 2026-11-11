"""finance.transactions (spec v1.3 section 4.5)."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('income', 'expense', 'opening_balance')",
            name="transaction_type_valid",
        ),
        CheckConstraint(
            "status IN ('draft', 'confirmed', 'reversed')",
            name="status_valid",
        ),
        CheckConstraint(
            "source IN ('manual', 'system', 'import')",
            name="source_valid",
        ),
        CheckConstraint(
            "amount > 0 OR transaction_type = 'opening_balance'",
            name="amount_positive_except_opening",
        ),
        Index("ix_transactions_household_date", "household_id", "transaction_date"),
        Index("ix_transactions_account_date", "account_id", "transaction_date"),
        Index("ix_transactions_category", "category_id"),
        Index("ix_transactions_status", "status"),
        Index("ix_transactions_transfer", "transfer_id"),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("core.households.id"), nullable=False
    )
    account_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("core.accounts.id"), nullable=False)
    category_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("finance.categories.id"), nullable=True
    )
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    currency: Mapped[str] = mapped_column(
        CHAR(3), ForeignKey("core.currencies.code"), nullable=False
    )
    base_amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    base_currency: Mapped[str] = mapped_column(
        CHAR(3), ForeignKey("core.currencies.code"), nullable=False
    )
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    exchange_rate_date: Mapped[date] = mapped_column(Date, nullable=False)
    transaction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reverses_transaction_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("finance.transactions.id"), nullable=True
    )
    transfer_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("finance.transfers.id"), nullable=True
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
