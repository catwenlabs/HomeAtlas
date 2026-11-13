"""Asset summary and net worth snapshot endpoints (asset-design 6.5)."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.pagination import PaginationDep, page_payload
from app.core.responses import success_response
from app.modules.assets import service
from app.modules.assets.models import NetWorthSnapshot
from app.modules.assets.schemas import AssetsSummary, NetWorthSnapshotRead
from app.modules.households.dependencies import CurrentHousehold

router = APIRouter(prefix="/assets", tags=["assets"])

SessionDep = Annotated[AsyncSession, Depends(get_db)]


def _snapshot(snapshot: NetWorthSnapshot) -> dict[str, Any]:
    return NetWorthSnapshotRead.model_validate(snapshot).model_dump(mode="json")


@router.get("/summary")
async def asset_summary(
    session: SessionDep,
    household: CurrentHousehold,
) -> dict[str, Any]:
    summary = await service.build_summary(session, household)
    return success_response(AssetsSummary.model_validate(summary).model_dump(mode="json"))


@router.post("/snapshots")
async def create_snapshot(
    session: SessionDep,
    household: CurrentHousehold,
    response: Response,
) -> dict[str, Any]:
    snapshot, created = await service.create_snapshot(session, household)
    response.status_code = 201 if created else 200
    return success_response(_snapshot(snapshot))


@router.get("/snapshots")
async def list_snapshots(
    session: SessionDep,
    household: CurrentHousehold,
    pagination: PaginationDep,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    snapshots, total = await service.list_snapshots(
        session, household.id, pagination, date_from=date_from, date_to=date_to
    )
    return success_response(
        page_payload([_snapshot(item) for item in snapshots], total, pagination)
    )


@router.get("/snapshots/monthly")
async def monthly_summary(
    session: SessionDep,
    household: CurrentHousehold,
    year: Annotated[int, Query(ge=1900, le=9999)],
) -> dict[str, Any]:
    summary = await service.monthly_summary(session, household.id, year)
    return success_response(summary)
