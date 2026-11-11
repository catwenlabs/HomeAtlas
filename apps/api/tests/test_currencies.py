"""Currency endpoints and seed data."""

from httpx import AsyncClient


async def test_list_currencies_returns_seed(db_client: AsyncClient, clean_db: None):
    response = await db_client.get("/api/v1/currencies")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["total"] == 6
    codes = [item["code"] for item in body["data"]["items"]]
    assert codes == ["CNY", "EUR", "GBP", "HKD", "JPY", "USD"]
    jpy = next(item for item in body["data"]["items"] if item["code"] == "JPY")
    assert jpy["decimal_places"] == 0


async def test_get_currency_is_case_insensitive(db_client: AsyncClient, clean_db: None):
    response = await db_client.get("/api/v1/currencies/cny")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["code"] == "CNY"


async def test_get_currency_unknown_returns_404(db_client: AsyncClient, clean_db: None):
    response = await db_client.get("/api/v1/currencies/XXX")
    assert response.status_code == 404
    assert response.json()["error_code"] == "CURRENCY_NOT_FOUND"


async def test_currency_list_rejects_unknown_sort(db_client: AsyncClient, clean_db: None):
    response = await db_client.get("/api/v1/currencies?sort_by=drop_table")
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_SORT_FIELD"


async def test_currency_pagination(db_client: AsyncClient, clean_db: None):
    response = await db_client.get("/api/v1/currencies?page=2&page_size=2")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["page"] == 2
    assert data["page_size"] == 2
    assert data["total"] == 6
    assert len(data["items"]) == 2
