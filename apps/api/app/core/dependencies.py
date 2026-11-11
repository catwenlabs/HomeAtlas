"""Shared FastAPI dependencies."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a database session; business modules consume this from Phase 1.1."""
    factory = request.app.state.db_session_factory
    async with factory() as session:
        yield session
