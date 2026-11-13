"""Shared business enumerations (spec v1.3 section 4)."""

from enum import StrEnum


class AccountType(StrEnum):
    BANK = "bank"
    CASH = "cash"
    WALLET = "wallet"
    OTHER = "other"
    CREDIT = "credit"
    INVESTMENT = "investment"


class Liquidity(StrEnum):
    """Withdrawal speed for accounts and investments (asset-design 4.2)."""

    NONE = "none"
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


class ExchangeRateSource(StrEnum):
    MANUAL = "manual"
    IMPORT = "import"
    SYSTEM = "system"


class InvestmentType(StrEnum):
    FIXED = "fixed"
    DAILY = "daily"
    FUND = "fund"
    CASH = "cash"
    STOCK = "stock"
    BOND = "bond"
    OTHER = "other"


class InvestmentStatus(StrEnum):
    ACTIVE = "active"
    REDEEMED = "redeemed"


class InvestmentLinkDirection(StrEnum):
    FUND = "fund"
    REDEEM = "redeem"


class Market(StrEnum):
    """Quote markets mapped to their settlement currency."""

    SH = "SH"
    SZ = "SZ"
    HK = "HK"
    US = "US"


class CategoryType(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"


class TransactionType(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    OPENING_BALANCE = "opening_balance"


class TransactionStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    REVERSED = "reversed"


class TransactionSource(StrEnum):
    MANUAL = "manual"
    SYSTEM = "system"
    IMPORT = "import"


class BalanceSource(StrEnum):
    MANUAL = "manual"
    BANK = "bank"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"
