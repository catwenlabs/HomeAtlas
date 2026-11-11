"""Error envelope shape for HTTP-level failures."""

import json

from fastapi import Request

from app.core.exceptions import (
    AppError,
    app_error_handler,
    unexpected_error_handler,
)


def _request() -> Request:
    return Request(scope={"type": "http", "method": "GET", "path": "/", "headers": []})


async def test_unknown_route_returns_error_envelope(client):
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error_code"] == "NOT_FOUND"
    assert body["message"]


async def test_app_error_handler_uses_status_and_code():
    exc = AppError("invalid transaction", status_code=422, error_code="TRANSACTION_INVALID")
    response = await app_error_handler(_request(), exc)
    assert response.status_code == 422
    body = json.loads(response.body)
    assert body == {
        "success": False,
        "data": None,
        "message": "invalid transaction",
        "error_code": "TRANSACTION_INVALID",
    }


async def test_unexpected_error_is_masked():
    response = await unexpected_error_handler(_request(), RuntimeError("secret detail"))
    assert response.status_code == 500
    body = json.loads(response.body)
    assert body["error_code"] == "INTERNAL_ERROR"
    assert "secret" not in body["message"]
