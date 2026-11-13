"""Exchange rate catalog: CRUD, dedup, latest lookup with inverse fallback."""

from datetime import date, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.exchange_rates.models import ExchangeRate

TODAY = date.today()


async def _create_rate(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    base: str = "USD",
    quote: str = "CNY",
    rate: str = "7.2",
    rate_date: str | None = None,
) -> dict[str, Any]:
    payload = {
        "base_currency": base,
        "quote_currency": quote,
        "rate": rate,
        "rate_date": rate_date or TODAY.isoformat(),
    }
    response = await client.post("/api/v1/exchange-rates", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_exchange_rate_crud_list_and_filters(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    first = await _create_rate(
        db_client, household_headers, rate="7.1", rate_date=(TODAY - timedelta(days=2)).isoformat()
    )
    await _create_rate(db_client, household_headers, rate="7.2")
    await _create_rate(db_client, household_headers, base="EUR", quote="CNY", rate="7.8")

    listing = await db_client.get(
        "/api/v1/exchange-rates?base=USD&quote=CNY&sort_by=rate_date&sort_order=desc",
        headers=household_headers,
    )
    assert listing.status_code == 200, listing.text
    items = listing.json()["data"]["items"]
    assert listing.json()["data"]["total"] == 2
    assert items[0]["rate"] == "7.200000000000"
    assert items[1]["rate"] == "7.100000000000"

    removed = await db_client.delete(
        f"/api/v1/exchange-rates/{first['id']}", headers=household_headers
    )
    assert removed.status_code == 200
    after = await db_client.get(
        "/api/v1/exchange-rates?base=USD&quote=CNY", headers=household_headers
    )
    assert after.json()["data"]["total"] == 1


async def test_exchange_rate_validation(db_client: AsyncClient, household_headers: dict[str, str]):
    zero = await db_client.post(
        "/api/v1/exchange-rates",
        headers=household_headers,
        json={
            "base_currency": "USD",
            "quote_currency": "CNY",
            "rate": "0",
            "rate_date": TODAY.isoformat(),
        },
    )
    assert zero.status_code == 422
    assert zero.json()["error_code"] == "EXCHANGE_RATE_VALUE_INVALID"

    same = await db_client.post(
        "/api/v1/exchange-rates",
        headers=household_headers,
        json={
            "base_currency": "USD",
            "quote_currency": "USD",
            "rate": "1",
            "rate_date": TODAY.isoformat(),
        },
    )
    assert same.status_code == 422
    assert same.json()["error_code"] == "EXCHANGE_RATE_VALUE_INVALID"

    unknown = await db_client.post(
        "/api/v1/exchange-rates",
        headers=household_headers,
        json={
            "base_currency": "XXX",
            "quote_currency": "CNY",
            "rate": "1",
            "rate_date": TODAY.isoformat(),
        },
    )
    assert unknown.status_code == 404
    assert unknown.json()["error_code"] == "CURRENCY_NOT_FOUND"


async def test_exchange_rate_duplicate_rejected(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    await _create_rate(db_client, household_headers, rate="7.2")
    duplicate = await db_client.post(
        "/api/v1/exchange-rates",
        headers=household_headers,
        json={
            "base_currency": "USD",
            "quote_currency": "CNY",
            "rate": "7.3",
            "rate_date": TODAY.isoformat(),
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error_code"] == "EXCHANGE_RATE_DUPLICATE"


async def test_latest_direct_and_inverse(db_client: AsyncClient, household_headers: dict[str, str]):
    await _create_rate(
        db_client,
        household_headers,
        rate="7.1",
        rate_date=(TODAY - timedelta(days=2)).isoformat(),
    )
    await _create_rate(db_client, household_headers, rate="7.2")

    direct = await db_client.get(
        "/api/v1/exchange-rates/latest?base=USD&quote=CNY", headers=household_headers
    )
    assert direct.status_code == 200, direct.text
    data = direct.json()["data"]
    assert data["rate"].startswith("7.2")
    assert data["direction"] == "direct"

    inverse = await db_client.get(
        "/api/v1/exchange-rates/latest?base=CNY&quote=USD", headers=household_headers
    )
    assert inverse.status_code == 200, inverse.text
    inverse_data = inverse.json()["data"]
    assert inverse_data["direction"] == "inverse"
    assert inverse_data["base_currency"] == "CNY"
    assert inverse_data["quote_currency"] == "USD"
    # 1 / 7.2 = 0.138888...
    assert inverse_data["rate"].startswith("0.1388")

    yesterday = (TODAY - timedelta(days=1)).isoformat()
    as_of = await db_client.get(
        f"/api/v1/exchange-rates/latest?base=USD&quote=CNY&date={yesterday}",
        headers=household_headers,
    )
    assert as_of.status_code == 200
    assert as_of.json()["data"]["rate"].startswith("7.1")


async def test_latest_not_found(db_client: AsyncClient, household_headers: dict[str, str]):
    missing = await db_client.get(
        "/api/v1/exchange-rates/latest?base=USD&quote=CNY", headers=household_headers
    )
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "EXCHANGE_RATE_NOT_FOUND"


async def test_exchange_rate_audit_and_scoping(
    db_client: AsyncClient,
    household_headers: dict[str, str],
    db_app: Any,
    auth_for_household: Any,
    create_household: Any,
):
    created = await _create_rate(db_client, household_headers)
    await db_client.delete(f"/api/v1/exchange-rates/{created['id']}", headers=household_headers)

    async with db_app.state.db_session_factory() as session:
        actions = (
            await session.scalars(
                select(AuditLog.action).where(
                    AuditLog.entity_type == "exchange_rate",
                    AuditLog.entity_id == created["id"],
                )
            )
        ).all()
    assert "exchange_rate.create" in actions
    assert "exchange_rate.delete" in actions

    second_id = await create_household()
    second_headers = await auth_for_household(second_id)
    second_rate = await _create_rate(db_client, second_headers, rate="7.0")
    cross = await db_client.delete(
        f"/api/v1/exchange-rates/{second_rate['id']}", headers=household_headers
    )
    assert cross.status_code == 404
    scoped_listing = await db_client.get(
        "/api/v1/exchange-rates?base=USD&quote=CNY", headers=second_headers
    )
    assert scoped_listing.json()["data"]["total"] == 1
    first_household = await db_client.get(
        "/api/v1/exchange-rates?base=USD&quote=CNY", headers=household_headers
    )
    assert first_household.json()["data"]["total"] == 0


async def test_rates_model_direct_query_shape(
    db_client: AsyncClient, household_headers: dict[str, str], db_app: Any
):
    """The stored row keeps source=manual and household scoping at DB level."""
    created = await _create_rate(db_client, household_headers)
    async with db_app.state.db_session_factory() as session:
        row = (
            await session.scalars(select(ExchangeRate).where(ExchangeRate.id == created["id"]))
        ).one()
    assert row.source == "manual"
