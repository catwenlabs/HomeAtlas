"""Investment, tag, holding, and quote-valuation endpoints (asset-design 6.3)."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.pagination import PaginationDep, page_payload
from app.core.responses import success_response
from app.modules.households.dependencies import CurrentHousehold
from app.modules.households.service import household_today
from app.modules.investments import holdings, service, tags
from app.modules.investments.models import Investment
from app.modules.investments.schemas import (
    HoldingCreate,
    HoldingRead,
    HoldingUpdate,
    InvestmentCreate,
    InvestmentFund,
    InvestmentRead,
    InvestmentRedeem,
    InvestmentTagsUpdate,
    InvestmentUpdate,
    InvestmentValueUpdate,
    TagCreate,
    TagRead,
    TagUpdate,
)

router = APIRouter(tags=["investments"])

SessionDep = Annotated[AsyncSession, Depends(get_db)]


def _holding(holding: Any) -> dict[str, Any]:
    data = HoldingRead.model_validate(holding).model_dump(mode="json")
    data["cost_subtotal"] = str(holdings.holding_cost(holding))
    return data


def _investment(
    investment: Investment,
    *,
    today: Any,
    tag_ids: list[uuid.UUID] | None = None,
    holdings_cost: Any = None,
) -> dict[str, Any]:
    data = InvestmentRead.model_validate(investment).model_dump(mode="json")
    data["matured"] = service.is_matured(investment, today)
    if tag_ids is not None:
        data["tag_ids"] = tag_ids
    if holdings_cost is not None:
        data["holdings_cost"] = str(holdings_cost)
    return data


# ---------------------------------------------------------------- tags


@router.get("/investment-tags")
async def list_tags(
    session: SessionDep,
    household: CurrentHousehold,
) -> dict[str, Any]:
    return success_response(
        {
            "items": [
                TagRead.model_validate(t).model_dump(mode="json")
                for t in await tags.list_tags(session, household.id)
            ]
        }
    )


@router.post("/investment-tags", status_code=status.HTTP_201_CREATED)
async def create_tag(
    session: SessionDep,
    household: CurrentHousehold,
    payload: TagCreate,
) -> dict[str, Any]:
    tag = await tags.create_tag(session, household.id, payload)
    return success_response(TagRead.model_validate(tag).model_dump(mode="json"))


@router.put("/investment-tags/{tag_id}")
async def update_tag(
    session: SessionDep,
    household: CurrentHousehold,
    tag_id: uuid.UUID,
    payload: TagUpdate,
) -> dict[str, Any]:
    tag = await tags.update_tag(session, household.id, tag_id, payload)
    return success_response(TagRead.model_validate(tag).model_dump(mode="json"))


@router.delete("/investment-tags/{tag_id}")
async def delete_tag(
    session: SessionDep,
    household: CurrentHousehold,
    tag_id: uuid.UUID,
) -> dict[str, Any]:
    await tags.delete_tag(session, household.id, tag_id)
    return success_response(message="Investment tag deleted")


# --------------------------------------------------------- investments


@router.get("/investments")
async def list_investments(
    session: SessionDep,
    household: CurrentHousehold,
    pagination: PaginationDep,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    investment_type: Annotated[str | None, Query()] = None,
    tag_id: Annotated[uuid.UUID | None, Query()] = None,
    account_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict[str, Any]:
    investments, total = await service.list_investments(
        session,
        household,
        pagination,
        status=status_filter,
        investment_type=investment_type,
        tag_id=tag_id,
        account_id=account_id,
    )
    today = household_today(household)
    tag_map = await service.tag_ids_for(session, [i.id for i in investments])
    return success_response(
        page_payload(
            [_investment(i, today=today, tag_ids=tag_map.get(i.id, [])) for i in investments],
            total,
            pagination,
        )
    )


@router.post("/investments", status_code=status.HTTP_201_CREATED)
async def create_investment(
    session: SessionDep,
    household: CurrentHousehold,
    payload: InvestmentCreate,
) -> dict[str, Any]:
    investment = await service.create_investment(session, household, payload)
    today = household_today(household)
    return success_response(_investment(investment, today=today, tag_ids=list(payload.tag_ids)))


@router.get("/investments/{investment_id}")
async def get_investment(
    session: SessionDep,
    household: CurrentHousehold,
    investment_id: uuid.UUID,
) -> dict[str, Any]:
    investment = await service.get_investment(session, household.id, investment_id)
    today = household_today(household)
    tag_map = await service.tag_ids_for(session, [investment.id])
    cost = await service.holdings_cost(session, investment.id)
    return success_response(
        _investment(
            investment,
            today=today,
            tag_ids=tag_map.get(investment.id, []),
            holdings_cost=cost,
        )
    )


@router.put("/investments/{investment_id}")
async def update_investment(
    session: SessionDep,
    household: CurrentHousehold,
    investment_id: uuid.UUID,
    payload: InvestmentUpdate,
) -> dict[str, Any]:
    investment = await service.update_investment(session, household, investment_id, payload)
    today = household_today(household)
    return success_response(_investment(investment, today=today))


@router.delete("/investments/{investment_id}")
async def delete_investment(
    session: SessionDep,
    household: CurrentHousehold,
    investment_id: uuid.UUID,
) -> dict[str, Any]:
    await service.delete_investment(session, household, investment_id)
    return success_response(message="Investment deleted")


@router.put("/investments/{investment_id}/value")
async def set_investment_value(
    session: SessionDep,
    household: CurrentHousehold,
    investment_id: uuid.UUID,
    payload: InvestmentValueUpdate,
) -> dict[str, Any]:
    investment = await service.set_value(session, household, investment_id, payload)
    today = household_today(household)
    return success_response(_investment(investment, today=today))


@router.put("/investments/{investment_id}/tags")
async def set_investment_tags(
    session: SessionDep,
    household: CurrentHousehold,
    investment_id: uuid.UUID,
    payload: InvestmentTagsUpdate,
) -> dict[str, Any]:
    investment = await service.set_tags(session, household, investment_id, payload.tag_ids)
    today = household_today(household)
    return success_response(_investment(investment, today=today, tag_ids=list(payload.tag_ids)))


@router.post("/investments/{investment_id}/fund")
async def fund_investment(
    session: SessionDep,
    household: CurrentHousehold,
    investment_id: uuid.UUID,
    payload: InvestmentFund,
) -> dict[str, Any]:
    investment = await service.fund_investment(session, household, investment_id, payload)
    today = household_today(household)
    return success_response(_investment(investment, today=today))


@router.post("/investments/{investment_id}/redeem")
async def redeem_investment(
    session: SessionDep,
    household: CurrentHousehold,
    investment_id: uuid.UUID,
    payload: InvestmentRedeem,
) -> dict[str, Any]:
    result = await service.redeem_investment(session, household, investment_id, payload)
    today = household_today(household)
    data = _investment(result["investment"], today=today)
    data["redeem_transfer_id"] = str(result["transfer_id"])
    data["realized_pnl"] = str(result["realized_pnl"])
    return success_response(data)


# ------------------------------------------------------------- holdings


@router.get("/investments/{investment_id}/holdings")
async def list_holdings(
    session: SessionDep,
    household: CurrentHousehold,
    investment_id: uuid.UUID,
) -> dict[str, Any]:
    rows = await holdings.list_holdings(session, household, investment_id)
    return success_response(
        {
            "items": [_holding(row) for row in rows],
            "holdings_cost": str(holdings.total_cost(rows)),
        }
    )


@router.post("/investments/{investment_id}/holdings", status_code=status.HTTP_201_CREATED)
async def create_holding(
    session: SessionDep,
    household: CurrentHousehold,
    investment_id: uuid.UUID,
    payload: HoldingCreate,
) -> dict[str, Any]:
    holding = await holdings.create_holding(session, household, investment_id, payload)
    return success_response(_holding(holding))


@router.put("/investments/{investment_id}/holdings/{holding_id}")
async def update_holding(
    session: SessionDep,
    household: CurrentHousehold,
    investment_id: uuid.UUID,
    holding_id: uuid.UUID,
    payload: HoldingUpdate,
) -> dict[str, Any]:
    holding = await holdings.update_holding(session, household, investment_id, holding_id, payload)
    return success_response(_holding(holding))


@router.delete("/investments/{investment_id}/holdings/{holding_id}")
async def delete_holding(
    session: SessionDep,
    household: CurrentHousehold,
    investment_id: uuid.UUID,
    holding_id: uuid.UUID,
) -> dict[str, Any]:
    await holdings.delete_holding(session, household, investment_id, holding_id)
    return success_response(message="Holding deleted")


@router.post("/investments/{investment_id}/refresh-value")
async def refresh_investment_value(
    session: SessionDep,
    household: CurrentHousehold,
    investment_id: uuid.UUID,
) -> dict[str, Any]:
    result = await holdings.refresh_value(session, household, investment_id)
    return success_response(result)
