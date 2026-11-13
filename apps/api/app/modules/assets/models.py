"""finance.net_worth_snapshots (asset-design section 4.7).

One row per household per natural day (household timezone), upserted on
demand. All amounts are converted to the household base currency with the
rates recorded in fx_rates_used.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class NetWorthSnapshot(Base):
    __tablename__ = "net_worth_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "household_id",
            "snapshot_date",
            name="uq_net_worth_snapshots_household_date",
        ),
        Index("ix_net_worth_snapshots_household_date", "household_id", "snapshot_date"),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("core.households.id"), nullable=False
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    base_currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    total_cash: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    total_invested: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    total_liabilities: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    net_worth: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    unmapped_cash: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    daily_interest_income: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    daily_interest_expense: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    currency_breakdown: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    fx_rates_used: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
