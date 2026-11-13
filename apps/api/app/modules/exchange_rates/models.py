"""finance.exchange_rates (asset-design section 4.1).

Household-scoped bank quotes, not a global market feed. Lookup rule:
latest direct pair with rate_date <= as-of, else the inverse 1/rate.
"""

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
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    __table_args__ = (
        CheckConstraint("rate > 0", name="rate_positive"),
        CheckConstraint("base_currency <> quote_currency", name="pair_distinct"),
        CheckConstraint("source IN ('manual', 'import', 'system')", name="source_valid"),
        UniqueConstraint(
            "household_id",
            "base_currency",
            "quote_currency",
            "rate_date",
            name="uq_exchange_rates_pair_date",
        ),
        Index("ix_exchange_rates_household_date", "household_id", "rate_date"),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("core.households.id"), nullable=False
    )
    base_currency: Mapped[str] = mapped_column(
        CHAR(3), ForeignKey("core.currencies.code"), nullable=False
    )
    quote_currency: Mapped[str] = mapped_column(
        CHAR(3), ForeignKey("core.currencies.code"), nullable=False
    )
    rate: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
