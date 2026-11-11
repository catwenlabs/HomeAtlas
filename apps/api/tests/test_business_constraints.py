"""Database-level CHECK constraints that back the service rules."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError

from app.modules.categories.models import Category
from app.modules.transactions.models import Transaction
from app.modules.transfers.models import Transfer


async def _household_and_account(
    client: AsyncClient, clean_db: None
) -> tuple[dict, dict, dict[str, str]]:
    household = await client.post("/api/v1/households", json={"name": "约束测试"})
    household_data = household.json()["data"]
    headers = {"X-Household-Id": household_data["id"]}
    account = await client.post(
        "/api/v1/accounts", headers=headers, json={"name": "现金", "currency": "CNY"}
    )
    return household_data, account.json()["data"], headers


async def test_non_opening_transaction_must_be_positive(
    db_client: AsyncClient, db_app, clean_db: None
):
    household, account, _ = await _household_and_account(db_client, clean_db)
    async with db_app.state.db_session_factory() as session:
        session.add(
            Transaction(
                household_id=UUID(household["id"]),
                account_id=UUID(account["id"]),
                transaction_type="income",
                amount=Decimal("-1"),
                currency="CNY",
                base_amount=Decimal("-1"),
                base_currency="CNY",
                exchange_rate=Decimal("1"),
                exchange_rate_date=date(2026, 1, 1),
                transaction_date=datetime(2026, 1, 1, tzinfo=UTC),
                source="manual",
                status="confirmed",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_category_type_check(db_client: AsyncClient, db_app, clean_db: None):
    household, _, _ = await _household_and_account(db_client, clean_db)
    async with db_app.state.db_session_factory() as session:
        session.add(
            Category(
                household_id=UUID(household["id"]),
                name="坏分类",
                category_type="transfer",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_transfer_cannot_move_same_account_same_currency(
    db_client: AsyncClient, db_app, clean_db: None
):
    household, account, _ = await _household_and_account(db_client, clean_db)
    account_id = UUID(account["id"])
    async with db_app.state.db_session_factory() as session:
        session.add(
            Transfer(
                household_id=UUID(household["id"]),
                from_account_id=account_id,
                to_account_id=account_id,
                from_amount=Decimal("10"),
                from_currency="CNY",
                to_amount=Decimal("10"),
                to_currency="CNY",
                exchange_rate=Decimal("1"),
                fee=Decimal("0"),
                fee_currency="CNY",
                transfer_date=datetime(2026, 1, 1, tzinfo=UTC),
                status="confirmed",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_openapi_documents_business_paths(db_client: AsyncClient, clean_db: None):
    payload = (await db_client.get("/openapi.json")).json()
    expected = {
        "/api/v1/households",
        "/api/v1/households/{household_id}",
        "/api/v1/accounts",
        "/api/v1/accounts/{account_id}",
        "/api/v1/accounts/{account_id}/balances",
        "/api/v1/accounts/{account_id}/opening-balance",
        "/api/v1/currencies",
        "/api/v1/categories",
    }
    assert expected <= set(payload["paths"])
