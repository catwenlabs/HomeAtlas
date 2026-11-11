"""Infrastructure probes. Outside /api/v1 and the response envelope by design."""

from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe: the process is up. Never touches the database."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> Any:
    """Readiness probe: the database answers SELECT 1."""
    factory = request.app.state.db_session_factory
    try:
        async with factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "error", "database": "unreachable"},
        )
    return {"status": "ok", "database": "ok"}
