"""Business API router mounted under settings.api_v1_prefix."""

from fastapi import APIRouter

from app.modules.accounts.router import router as accounts_router
from app.modules.categories.router import router as categories_router
from app.modules.currencies.router import router as currencies_router
from app.modules.households.router import router as households_router
from app.modules.imports.router import router as imports_router
from app.modules.statistics.router import router as statistics_router
from app.modules.transactions.router import router as transactions_router
from app.modules.transfers.router import router as transfers_router

api_router = APIRouter()
api_router.include_router(households_router)
api_router.include_router(accounts_router)
api_router.include_router(currencies_router)
api_router.include_router(categories_router)
api_router.include_router(transactions_router)
api_router.include_router(transfers_router)
api_router.include_router(imports_router)
api_router.include_router(statistics_router)
