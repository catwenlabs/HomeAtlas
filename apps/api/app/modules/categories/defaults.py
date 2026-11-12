"""Default category catalog shown in the setup wizard (spec section 4.4).

Nothing from this module is written to the database automatically; the setup
wizard prefills these rows and persists only what the user confirms.
"""

from dataclasses import dataclass

from app.core.enums import CategoryType

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
