"""Household scoping, base-currency lock, and token-derived tenancy."""

from typing import Any

from httpx import AsyncClient


async def test_current_household_is_the_only_visible_one(
    db_client: AsyncClient, household: dict
) -> None:
    listing = await db_client.get("/api/v1/households")
    assert listing.status_code == 200
    data = listing.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["id"] == household["id"]

    fetched = await db_client.get(f"/api/v1/households/{household['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["name"] == household["name"]

    missing = await db_client.get("/api/v1/households/00000000-0000-0000-0000-000000000099")
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "HOUSEHOLD_NOT_FOUND"


async def test_invalid_timezone_and_currency_are_rejected(
    db_client: AsyncClient, household: dict
) -> None:
    bad_timezone = await db_client.put(
        f"/api/v1/households/{household['id']}", json={"timezone": "Mars/Base"}
    )
    assert bad_timezone.status_code == 422

    bad_currency = await db_client.put(
        f"/api/v1/households/{household['id']}", json={"base_currency": "XXX"}
    )
    assert bad_currency.status_code == 404
    assert bad_currency.json()["error_code"] == "CURRENCY_NOT_FOUND"


async def test_update_household_and_base_currency_lock(
    db_client: AsyncClient, household: dict, household_headers: dict[str, str]
):
    updated = await db_client.put(
        f"/api/v1/households/{household['id']}",
        json={"name": "新名字", "timezone": "Europe/London"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "新名字"

    changed_currency = await db_client.put(
        f"/api/v1/households/{household['id']}", json={"base_currency": "USD"}
    )
    assert changed_currency.status_code == 200
    assert changed_currency.json()["data"]["base_currency"] == "USD"

    account = await db_client.post(
        "/api/v1/accounts",
        headers=household_headers,
        json={"name": "现金", "currency": "USD"},
    )
    account_id = account.json()["data"]["id"]
    opening = await db_client.put(
        f"/api/v1/accounts/{account_id}/opening-balance",
        headers=household_headers,
        json={"amount": "100.00"},
    )
    assert opening.status_code == 200

    locked = await db_client.put(
        f"/api/v1/households/{household['id']}", json={"base_currency": "CNY"}
    )
    assert locked.status_code == 409
    assert locked.json()["error_code"] == "BASE_CURRENCY_LOCKED"

    missing_currency = await db_client.put(
        f"/api/v1/households/{household['id']}", json={"base_currency": "XXX"}
    )
    assert missing_currency.status_code == 404


async def test_household_scope_comes_from_token(
    db_client: AsyncClient,
    household: dict,
    household_headers: dict[str, str],
    auth_for_household: Any,
    create_household: Any,
):
    own = await db_client.get("/api/v1/accounts")
    assert own.status_code == 200
    assert own.json()["data"]["total"] == 0

    second_id = await create_household()
    second_headers = await auth_for_household(second_id)

    await db_client.post("/api/v1/accounts", headers=second_headers, json={"name": "第二家账户"})
    await db_client.post("/api/v1/accounts", headers=household_headers, json={"name": "自家账户"})

    first_scope = await db_client.get("/api/v1/accounts", headers=household_headers)
    second_scope = await db_client.get("/api/v1/accounts", headers=second_headers)
    assert first_scope.json()["data"]["total"] == 1
    assert first_scope.json()["data"]["items"][0]["name"] == "自家账户"
    assert second_scope.json()["data"]["total"] == 1
    assert second_scope.json()["data"]["items"][0]["name"] == "第二家账户"

    # Another household's id is indistinguishable from a missing one.
    cross_read = await db_client.get(f"/api/v1/households/{second_id}", headers=household_headers)
    assert cross_read.status_code == 404
    assert cross_read.json()["error_code"] == "HOUSEHOLD_NOT_FOUND"
    cross_update = await db_client.put(
        f"/api/v1/households/{second_id}",
        headers=household_headers,
        json={"name": "越权改名"},
    )
    assert cross_update.status_code == 404


async def test_business_endpoints_require_valid_token(db_client: AsyncClient, household: dict):
    saved = db_client.headers.pop("Authorization")
    try:
        missing = await db_client.get("/api/v1/accounts")
    finally:
        db_client.headers["Authorization"] = saved
    assert missing.status_code == 401
    assert missing.json()["error_code"] == "AUTH_REQUIRED"

    invalid = await db_client.get(
        "/api/v1/accounts", headers={"Authorization": "Bearer not-a-token"}
    )
    assert invalid.status_code == 401
    assert invalid.json()["error_code"] == "AUTH_INVALID_TOKEN"
