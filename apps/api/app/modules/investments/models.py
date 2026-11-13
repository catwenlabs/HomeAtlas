"""finance.investments and satellite tables (asset-design sections 4.4-4.6).

An investment with account_id is "managed" (principal arrived via internal
transfers recorded in investment_transfers); without one it is "unmanaged"
— a pure registration snapshot that never touches the account system.
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


class Investment(Base):
    __tablename__ = "investments"
    __table_args__ = (
        CheckConstraint(
            "investment_type IN ('fixed', 'daily', 'fund', 'cash', 'stock', 'bond', 'other')",
            name="investment_type_valid",
        ),
        CheckConstraint("principal >= 0", name="principal_non_negative"),
        CheckConstraint("current_value >= 0", name="current_value_non_negative"),
        CheckConstraint("status IN ('active', 'redeemed')", name="status_valid"),
        CheckConstraint("annual_rate IS NULL OR annual_rate >= 0", name="rate_ok"),
        CheckConstraint(
            "liquidity IS NULL OR liquidity IN ('none', 'T0', 'T1', 'T2', 'T3')",
            name="liquidity_valid",
        ),
        Index("ix_investments_household_status", "household_id", "status"),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("core.households.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    investment_type: Mapped[str] = mapped_column(String(20), nullable=False)
    account_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("core.accounts.id"), nullable=True
    )
    principal: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    current_value: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    currency: Mapped[str] = mapped_column(
        CHAR(3), ForeignKey("core.currencies.code"), nullable=False
    )
    annual_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    liquidity: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    pre_redeem_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    remark: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class InvestmentTag(Base):
    __tablename__ = "investment_tags"
    __table_args__ = (
        UniqueConstraint("household_id", "name", name="uq_investment_tags_name"),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("core.households.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    color: Mapped[str | None] = mapped_column(CHAR(7))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class InvestmentTagLink(Base):
    __tablename__ = "investment_tag_links"
    __table_args__ = {"schema": "finance"}

    investment_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("finance.investments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("finance.investment_tags.id", ondelete="CASCADE"),
        primary_key=True,
    )


class InvestmentTransfer(Base):
    """Mandatory link between an investment action and its transfer (4.6)."""

    __tablename__ = "investment_transfers"
    __table_args__ = (
        CheckConstraint("direction IN ('fund', 'redeem')", name="direction_valid"),
        UniqueConstraint("transfer_id", name="uq_investment_transfers_transfer"),
        {"schema": "finance"},
    )

    investment_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("finance.investments.id"), primary_key=True
    )
    transfer_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("finance.transfers.id"), primary_key=True
    )
    direction: Mapped[str] = mapped_column(String(10), nullable=False)


class Holding(Base):
    """Stock/fund position snapshot: market + symbol + quantity + cost."""

    __tablename__ = "holdings"
    __table_args__ = (
        CheckConstraint("market IN ('SH', 'SZ', 'HK', 'US')", name="market_valid"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("cost_price >= 0", name="cost_price_non_negative"),
        UniqueConstraint("investment_id", "market", "symbol", name="uq_holdings_position"),
        Index("ix_holdings_household", "household_id"),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("core.households.id"), nullable=False
    )
    investment_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("finance.investments.id", ondelete="CASCADE"), nullable=False
    )
    market: Mapped[str] = mapped_column(String(10), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    cost_price: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    remark: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
