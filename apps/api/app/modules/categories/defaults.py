"""Default category tree seeded for every household (spec section 4.4)."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import CategoryType
from app.modules.categories.models import Category

# System category used by transfer fee expense rows. It must never be deleted.
FINANCIAL_FEE_NAME = "金融手续费"


@dataclass(frozen=True)
class DefaultCategory:
    name: str
    category_type: CategoryType
    sort_order: int
    icon: str | None = None


DEFAULT_CATEGORIES: tuple[DefaultCategory, ...] = (
    DefaultCategory("工资", CategoryType.INCOME, 10, "wallet"),
    DefaultCategory("奖金", CategoryType.INCOME, 20, "award"),
    DefaultCategory("利息", CategoryType.INCOME, 30, "percent"),
    DefaultCategory("其他收入", CategoryType.INCOME, 40, "plus-circle"),
    DefaultCategory("餐饮", CategoryType.EXPENSE, 10, "utensils"),
    DefaultCategory("购物", CategoryType.EXPENSE, 20, "shopping-bag"),
    DefaultCategory("交通", CategoryType.EXPENSE, 30, "car"),
    DefaultCategory("住房", CategoryType.EXPENSE, 40, "home"),
    DefaultCategory("娱乐", CategoryType.EXPENSE, 50, "gamepad"),
    DefaultCategory("其他支出", CategoryType.EXPENSE, 60, "minus-circle"),
    DefaultCategory(FINANCIAL_FEE_NAME, CategoryType.EXPENSE, 990, "receipt"),
)


def build_default_categories(household_id: UUID) -> list[Category]:
    """Build (but do not persist) the standard root categories for a household."""
    return [
        Category(
            household_id=household_id,
            name=item.name,
            category_type=item.category_type.value,
            parent_id=None,
            icon=item.icon,
            sort_order=item.sort_order,
            is_active=True,
        )
        for item in DEFAULT_CATEGORIES
    ]


async def seed_default_categories(session: AsyncSession, household_id: UUID) -> None:
    session.add_all(build_default_categories(household_id))
    await session.flush()
