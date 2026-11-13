"""Default category catalog shown in the setup wizard (spec section 4.4).

Nothing from this module is written to the database automatically; the setup
wizard prefills these rows and persists only what the user confirms.
"""

from dataclasses import dataclass

from app.core.enums import CategoryType

# System category used by transfer fee expense rows. It must never be deleted.
FINANCIAL_FEE_NAME = "金融手续费"

# System categories used by investment redeem PnL rows (asset-design 7).
INVESTMENT_INCOME_NAME = "投资收益"
INVESTMENT_LOSS_NAME = "投资亏损"

# Suggested category for loan repayment expenses (asset-design 4.3).
LOAN_REPAYMENT_NAME = "贷款还款"


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
    DefaultCategory(INVESTMENT_INCOME_NAME, CategoryType.INCOME, 950, "trending-up"),
    DefaultCategory(INVESTMENT_LOSS_NAME, CategoryType.EXPENSE, 951, "trending-down"),
    DefaultCategory(LOAN_REPAYMENT_NAME, CategoryType.EXPENSE, 952, "landmark"),
    DefaultCategory(FINANCIAL_FEE_NAME, CategoryType.EXPENSE, 990, "receipt"),
)
