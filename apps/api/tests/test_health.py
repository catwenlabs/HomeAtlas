"""Liveness probe and OpenAPI document."""


async def test_health_returns_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_openapi_document_is_served(client):
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    payload = response.json()
    assert "/health" in payload["paths"]
    assert "/ready" in payload["paths"]
