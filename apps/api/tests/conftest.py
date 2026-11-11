"""Shared fixtures: application factory, HTTP client, disposable test database.

The test database (home_atlas_test) is dropped and recreated once per session,
then migrated with `alembic upgrade head` — the same migrations production uses.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic.config import Config
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.core.config import get_settings
from app.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_DB_NAME = "home_atlas_test"


def _postgres_url(dbname: str) -> str:
    password = os.environ.get("POSTGRES_PASSWORD", "homeatlas")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "homeatlas")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{dbname}"


@pytest.fixture(autouse=True)
def _fresh_settings() -> None:
    """Isolate the cached settings per test so env overrides never leak."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def test_database() -> str:
    """Drop + recreate the disposable test database and apply all migrations."""
    admin_url = _postgres_url("postgres")

    async def _recreate() -> None:
        engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
            await conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
        await engine.dispose()

    asyncio.run(_recreate())

    os.environ["POSTGRES_DB"] = TEST_DB_NAME
    get_settings.cache_clear()
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    return _postgres_url(TEST_DB_NAME)


@pytest.fixture
async def app() -> AsyncIterator[FastAPI]:
    """App without a guaranteed database — for tests that never touch Postgres."""
    application = create_app()
    async with LifespanManager(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


@pytest.fixture
async def db_app(test_database: str) -> AsyncIterator[FastAPI]:
    """App wired to the migrated test database (POSTGRES_DB already overridden)."""
    get_settings.cache_clear()
    application = create_app()
    async with LifespanManager(application):
        yield application


@pytest.fixture
async def db_client(db_app: FastAPI) -> AsyncIterator[AsyncClient]:
    """HTTP client against db_app."""
    transport = ASGITransport(app=db_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


@pytest.fixture
async def clean_db(db_app: FastAPI) -> AsyncIterator[None]:
    """Wipe all business rows between tests; currency seed stays in place."""
    async with db_app.state.db_session_factory() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE system.import_rows, system.import_batches, "
                "system.audit_logs, core.account_balances, "
                "finance.transactions, finance.transfers, finance.categories, "
                "core.accounts, core.households RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()
    yield


@pytest.fixture
async def household(db_client: AsyncClient, clean_db: None) -> dict:
    response = await db_client.post(
        "/api/v1/households", json={"name": "测试家庭", "base_currency": "CNY"}
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


@pytest.fixture
def household_headers(household: dict) -> dict[str, str]:
    return {"X-Household-Id": household["id"]}
