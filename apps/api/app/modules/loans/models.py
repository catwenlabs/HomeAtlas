"""finance.loans (asset-design section 4.3).

Lightweight liability model: principal + rate + due day. Repayments are
ordinary expense transactions (suggested category 贷款还款); the balance
side reads remaining_principal, maintained by hand and zeroed on settle.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Loan(Base):
    __tablename__ = "loans"
    __table_args__ = (
        CheckConstraint("principal > 0", name="principal_positive"),
        CheckConstraint("annual_rate >= 0", name="rate_non_negative"),
        CheckConstraint("due_day IS NULL OR due_day BETWEEN 1 AND 31", name="due_day_range"),
        CheckConstraint(
            "repayment_type IN ('monthly_interest', 'one_time')",
            name="repayment_type_valid",
        ),
        CheckConstraint("remaining_principal >= 0", name="remaining_non_negative"),
        CheckConstraint("status IN ('active', 'settled')", name="status_valid"),
        CheckConstraint("remaining_principal <= principal", name="remaining_within_principal"),
        Index("ix_loans_household_status", "household_id", "status"),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("core.households.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    institution: Mapped[str | None] = mapped_column(String(100))
    principal: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    currency: Mapped[str] = mapped_column(
        CHAR(3), ForeignKey("core.currencies.code"), nullable=False
    )
    annual_rate: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    due_day: Mapped[int | None] = mapped_column(SmallInteger)
    repayment_type: Mapped[str] = mapped_column(String(30), nullable=False)
    linked_account_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("core.accounts.id"), nullable=True
    )
    remaining_principal: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    settled_date: Mapped[date | None] = mapped_column(Date)
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


def loan_audit_data(loan: Loan) -> dict[str, Any]:
    return {
        "name": loan.name,
        "principal": str(loan.principal),
        "currency": str(loan.currency).strip(),
        "annual_rate": str(loan.annual_rate),
        "remaining_principal": str(loan.remaining_principal),
        "status": loan.status,
        "repayment_type": loan.repayment_type,
    }
