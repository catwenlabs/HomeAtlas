"""Shared business enumerations (spec v1.3 section 4)."""

from enum import StrEnum


class AccountType(StrEnum):
    BANK = "bank"
    CASH = "cash"
    WALLET = "wallet"
    OTHER = "other"


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
