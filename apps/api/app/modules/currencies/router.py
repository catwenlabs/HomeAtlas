"""Currency endpoints (spec section 6.3)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.pagination import PaginationDep, page_payload
from app.core.responses import success_response
from app.modules.currencies import service
from app.modules.currencies.schemas import CurrencyRead

router = APIRouter(prefix="/currencies", tags=["currencies"])

SessionDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("")
async def list_currencies(
    session: SessionDep,
    pagination: PaginationDep,
    is_active: Annotated[bool | None, Query()] = None,
) -> dict[str, Any]:
    currencies, total = await service.list_currencies(session, pagination, is_active=is_active)
    items = [
        CurrencyRead.model_validate(currency).model_dump(mode="json") for currency in currencies
    ]
    return success_response(page_payload(items, total, pagination))


@router.get("/{code}")
async def get_currency(session: SessionDep, code: str) -> dict[str, Any]:
    currency = await service.get_currency(session, code, require_active=False)
    return success_response(CurrencyRead.model_validate(currency).model_dump(mode="json"))
