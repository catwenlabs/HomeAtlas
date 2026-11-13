"""Business API router mounted under settings.api_v1_prefix.

All business endpoints require a Bearer token; ``public_router`` carries the
unauthenticated setup/login endpoints.
"""

from fastapi import APIRouter

from app.modules.accounts.router import router as accounts_router
from app.modules.assets.router import router as assets_router
from app.modules.auth.router import router as auth_router
from app.modules.categories.router import router as categories_router
from app.modules.currencies.router import router as currencies_router
from app.modules.exchange_rates.router import router as exchange_rates_router
from app.modules.households.router import router as households_router
from app.modules.imports.router import router as imports_router
from app.modules.investments.router import router as investments_router
from app.modules.market.router import router as market_router
from app.modules.setup.router import router as setup_router
from app.modules.statistics.router import router as statistics_router
from app.modules.transactions.router import router as transactions_router
from app.modules.transfers.router import router as transfers_router
from app.modules.users.router import router as users_router

public_router = APIRouter()
public_router.include_router(setup_router)
public_router.include_router(auth_router)

api_router = APIRouter()
api_router.include_router(households_router)
api_router.include_router(accounts_router)
api_router.include_router(currencies_router)
api_router.include_router(categories_router)
api_router.include_router(transactions_router)
api_router.include_router(transfers_router)
api_router.include_router(imports_router)
api_router.include_router(statistics_router)
api_router.include_router(exchange_rates_router)
api_router.include_router(assets_router)
api_router.include_router(investments_router)
api_router.include_router(market_router)
api_router.include_router(users_router)
