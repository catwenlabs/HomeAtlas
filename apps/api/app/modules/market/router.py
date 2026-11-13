"""Market quote endpoints (2C-2). Quotes are informational, never ledgered."""

from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.core.responses import success_response
from app.modules.households.dependencies import CurrentHousehold
from app.modules.market import service

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/quotes")
async def get_quotes(
    household: CurrentHousehold,
    symbols: Annotated[str, Query(min_length=1)],
) -> dict[str, Any]:
    refs = service.parse_symbols(symbols)
    quotes = await service.fetch_quotes(refs)
    return success_response({"items": [service.quote_response(quote) for quote in quotes.values()]})
