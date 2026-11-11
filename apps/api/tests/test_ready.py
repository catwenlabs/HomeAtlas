"""Readiness probe against the real test database and its failure path."""

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app


async def test_ready_returns_ok_when_database_answers(db_client):
    response = await db_client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_ready_returns_503_when_database_unreachable(monkeypatch):
    monkeypatch.setenv("POSTGRES_PORT", "1")  # nothing listens here; refused fast
    get_settings.cache_clear()
    application = create_app()
    async with LifespanManager(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://testserver") as http:
            response = await http.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unreachable"}
