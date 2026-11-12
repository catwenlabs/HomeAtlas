"""Shared fixtures: application factory, HTTP client, disposable test database.

The test database (home_atlas_test) is dropped and recreated once per session,
then migrated with `alembic upgrade head` — the same migrations production uses.
Currencies are seeded once because setup (not migrations) writes the catalog.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.core.config import get_settings
from app.main import create_app
from app.modules.currencies.defaults import seed_currencies

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_DB_NAME = "home_atlas_test"

TEST_OWNER = {
    "username": "owner",
    "password": "password123",
    "display_name": "测试用户",
    "household_name": "测试家庭",
    "base_currency": "CNY",
    "timezone": "Asia/Shanghai",
}


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

    async def _seed() -> None:
        engine = create_async_engine(_postgres_url(TEST_DB_NAME))
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await seed_currencies(session)
            await session.commit()
        await engine.dispose()

    asyncio.run(_seed())
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
async def clean_db(db_app: FastAPI, db_client: AsyncClient) -> AsyncIterator[None]:
    """Wipe business rows, then run first-time setup and authenticate the client."""
    async with db_app.state.db_session_factory() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE system.import_rows, system.import_batches, "
                "system.audit_logs, core.users, core.account_balances, "
                "finance.transactions, finance.transfers, finance.categories, "
                "core.accounts, core.households RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()
    response = await db_client.post("/api/v1/setup", json=TEST_OWNER)
    assert response.status_code == 200, response.text
    db_app.state.test_auth = response.json()["data"]
    db_client.headers["Authorization"] = f"Bearer {db_app.state.test_auth['access_token']}"
    yield


@pytest.fixture
def household(clean_db: None, db_app: FastAPI) -> dict[str, Any]:
    return db_app.state.test_auth["household"]


@pytest.fixture
def household_headers(household: dict[str, Any], db_app: FastAPI) -> dict[str, str]:
    return {"Authorization": f"Bearer {db_app.state.test_auth['access_token']}"}


@pytest.fixture
def create_household(db_app: FastAPI) -> Any:
    """Insert another household directly; the public API no longer creates them."""

    async def _make(
        name: str = "第二家",
        *,
        base_currency: str = "CNY",
        timezone: str = "Asia/Shanghai",
    ) -> str:
        from app.modules.households.models import Household

        async with db_app.state.db_session_factory() as session:
            household = Household(
                name=name,
                base_currency=base_currency,
                timezone=timezone,
            )
            session.add(household)
            await session.commit()
            await session.refresh(household)
            return str(household.id)

    return _make


@pytest.fixture
def auth_for_household(db_client: AsyncClient, db_app: FastAPI) -> Any:
    """Create a member user in another household and return their bearer headers."""

    async def _make(household_id: str, *, username: str | None = None) -> dict[str, str]:
        from uuid import UUID, uuid4

        from app.modules.auth import service as auth_service
        from app.modules.auth.schemas import UserCreate

        name = username or f"member-{uuid4().hex[:8]}"
        async with db_app.state.db_session_factory() as session:
            await auth_service.create_user(
                session,
                UUID(household_id),
                UserCreate(
                    username=name,
                    password="password123",
                    display_name=name,
                    role="owner",
                ),
                actor="owner",
            )
        login = await db_client.post(
            "/api/v1/auth/login",
            json={"username": name, "password": "password123"},
        )
        assert login.status_code == 200, login.text
        return {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    return _make
