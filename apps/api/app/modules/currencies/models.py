"""core.currencies (spec v1.3 section 4.3)."""

from sqlalchemy import CHAR, CheckConstraint, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Currency(Base):
    __tablename__ = "currencies"
    __table_args__ = (
        CheckConstraint("decimal_places >= 0 AND decimal_places <= 8", name="decimal_places_range"),
        {"schema": "core"},
    )

    code: Mapped[str] = mapped_column(CHAR(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    decimal_places: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
