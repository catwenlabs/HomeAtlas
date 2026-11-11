"""Database wiring: session dependency yields a usable async session."""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db


class _RequestStub:
    """Minimal request stand-in exposing the app and its state."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.state = app.state


@pytest.fixture
async def session(db_app: FastAPI) -> AsyncIterator[AsyncSession]:
    generator = get_db(_RequestStub(db_app))
    yield await generator.__anext__()
    with pytest.raises(StopAsyncIteration):
        await generator.__anext__()


async def test_get_db_yields_working_session(session: AsyncSession):
    result = await session.execute(text("SELECT 1 AS one"))
    assert result.scalar_one() == 1
