"""Import every ORM model so Base.metadata is complete for Alembic autogenerate."""

from app.modules.accounts.models import Account, AccountBalance
from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
from app.modules.categories.models import Category
from app.modules.currencies.models import Currency
from app.modules.households.models import Household
from app.modules.imports.models import ImportBatch, ImportRow
from app.modules.transactions.models import Transaction
from app.modules.transfers.models import Transfer

__all__ = [
    "Account",
    "AccountBalance",
    "AuditLog",
    "Category",
    "Currency",
    "Household",
    "ImportBatch",
    "ImportRow",
    "Transaction",
    "Transfer",
    "User",
]
