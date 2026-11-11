"""finance.transfers (spec v1.3 section 4.6)."""

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
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Transfer(Base):
    __tablename__ = "transfers"
    __table_args__ = (
        CheckConstraint(
            "from_account_id <> to_account_id OR from_currency <> to_currency",
            name="transfer_source_differs",
        ),
        CheckConstraint("fee >= 0", name="fee_non_negative"),
        CheckConstraint("status IN ('draft', 'confirmed', 'reversed')", name="status_valid"),
        Index("ix_transfers_household_date", "household_id", "transfer_date"),
        Index("ix_transfers_from_account", "from_account_id"),
        Index("ix_transfers_to_account", "to_account_id"),
        Index("ix_transfers_status", "status"),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("core.households.id"), nullable=False
    )
    from_account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("core.accounts.id"), nullable=False
    )
    to_account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("core.accounts.id"), nullable=False
    )
    from_amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    from_currency: Mapped[str] = mapped_column(
        CHAR(3), ForeignKey("core.currencies.code"), nullable=False
    )
    to_amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    to_currency: Mapped[str] = mapped_column(
        CHAR(3), ForeignKey("core.currencies.code"), nullable=False
    )
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    base_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    base_currency: Mapped[str | None] = mapped_column(CHAR(3), ForeignKey("core.currencies.code"))
    fee: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False, default=Decimal("0"))
    fee_currency: Mapped[str] = mapped_column(
        CHAR(3), ForeignKey("core.currencies.code"), nullable=False
    )
    transfer_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reverses_transfer_id: Mapped[UUID | None] = mapped_column(
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
