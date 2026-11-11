"""Household CRUD, default categories, base-currency lock, and scoping rules."""

from httpx import AsyncClient


async def test_create_household_seeds_default_categories(db_client: AsyncClient, clean_db: None):
    response = await db_client.post(
        "/api/v1/households",
        json={"name": "我的家", "base_currency": "usd", "timezone": "America/New_York"},
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["base_currency"] == "USD"
    assert data["timezone"] == "America/New_York"

    headers = {"X-Household-Id": data["id"]}
    categories = await db_client.get("/api/v1/categories?page_size=100", headers=headers)
    assert categories.status_code == 200
    items = categories.json()["data"]["items"]
    assert len(items) == 11
    assert {item["name"] for item in items} >= {"工资", "餐饮", "金融手续费"}


async def test_list_and_get_households(db_client: AsyncClient, clean_db: None):
    created = await db_client.post("/api/v1/households", json={"name": "甲"})
    household_id = created.json()["data"]["id"]

    listing = await db_client.get("/api/v1/households")
    assert listing.status_code == 200
    assert listing.json()["data"]["total"] == 1

    fetched = await db_client.get(f"/api/v1/households/{household_id}")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["name"] == "甲"

    missing = await db_client.get("/api/v1/households/00000000-0000-0000-0000-000000000099")
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "HOUSEHOLD_NOT_FOUND"


async def test_invalid_timezone_and_currency_are_rejected(db_client: AsyncClient, clean_db: None):
    bad_timezone = await db_client.post(
        "/api/v1/households", json={"name": "甲", "timezone": "Mars/Base"}
    )
    assert bad_timezone.status_code == 422

    bad_currency = await db_client.post(
        "/api/v1/households", json={"name": "甲", "base_currency": "XXX"}
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


async def test_household_scope_falls_back_to_single_household(
    db_client: AsyncClient, household: dict
):
    response = await db_client.get("/api/v1/accounts")
    assert response.status_code == 200
    assert response.json()["data"]["total"] == 0


async def test_household_scope_requires_header_when_multiple(
    db_client: AsyncClient, household: dict, household_headers: dict[str, str]
):
    second = await db_client.post("/api/v1/households", json={"name": "第二家"})
    second_id = second.json()["data"]["id"]

    ambiguous = await db_client.get("/api/v1/accounts")
    assert ambiguous.status_code == 400
    assert ambiguous.json()["error_code"] == "HOUSEHOLD_REQUIRED"

    scoped = await db_client.get("/api/v1/accounts", headers=household_headers)
    assert scoped.status_code == 200

    missing = await db_client.get(
        "/api/v1/accounts",
        headers={"X-Household-Id": "00000000-0000-0000-0000-000000000099"},
    )
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "HOUSEHOLD_NOT_FOUND"

    second_scoped = await db_client.get("/api/v1/accounts", headers={"X-Household-Id": second_id})
    assert second_scoped.status_code == 200


async def test_household_scope_without_any_household(db_client: AsyncClient, clean_db: None):
    response = await db_client.get("/api/v1/accounts")
    assert response.status_code == 400
    assert response.json()["error_code"] == "HOUSEHOLD_REQUIRED"


async def test_invalid_household_header_is_validation_error(
    db_client: AsyncClient, household: dict
):
    response = await db_client.get("/api/v1/accounts", headers={"X-Household-Id": "nope"})
    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"


async def test_household_list_sort_validation(db_client: AsyncClient, household: dict):
    response = await db_client.get("/api/v1/households?sort_by=name&sort_order=desc")
    assert response.status_code == 200
    bad = await db_client.get("/api/v1/households?sort_by=evil")
    assert bad.status_code == 400
