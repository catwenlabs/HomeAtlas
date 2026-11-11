"""Unified API response envelope (spec v1.3 section 6.8)."""

from typing import Any


def success_response(data: Any = None, message: str | None = None) -> dict[str, Any]:
    """Build the success envelope: {"success": true, "data": ..., "message": ...}."""
    return {"success": True, "data": data, "message": message}


def error_response(message: str, error_code: str) -> dict[str, Any]:
    """Build the error envelope (success=false, data=null, message, error_code)."""
    return {"success": False, "data": None, "message": message, "error_code": error_code}
