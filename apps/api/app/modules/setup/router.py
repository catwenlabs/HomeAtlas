"""First-time deployment setup endpoints (Phase 2A)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.responses import success_response
from app.modules.auth import service
from app.modules.auth.schemas import SetupRequest
from app.modules.setup.options import setup_options

router = APIRouter(prefix="/setup", tags=["setup"])

SessionDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("/status")
async def setup_status(session: SessionDep) -> dict[str, Any]:
    status = await service.setup_status(session)
    return success_response(status.model_dump(mode="json"))


@router.get("/options")
async def get_setup_options() -> dict[str, Any]:
    """Static prefill data; nothing is written until POST /setup."""
    return success_response(setup_options())


@router.post("")
async def setup(session: SessionDep, payload: SetupRequest) -> dict[str, Any]:
    result = await service.setup(session, payload)
    return success_response(result.model_dump(mode="json"))
