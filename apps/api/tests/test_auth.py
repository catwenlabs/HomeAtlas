"""First-time setup, JWT login, and household member management (Phase 2A)."""

from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import text

from app.core.config import Settings
from app.modules.audit.models import AuditLog


def test_production_requires_a_strong_jwt_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="production", jwt_secret_key="short")

    production = Settings(app_env="production", jwt_secret_key="x" * 32)
    assert production.jwt_secret_key == "x" * 32


async def test_setup_status_and_duplicate_setup(db_client: AsyncClient, clean_db: None) -> None:
    status = await db_client.get("/api/v1/setup/status")
    assert status.status_code == 200, status.text
    data = status.json()["data"]
    assert data["initialized"] is True
    assert data["household_name"] == "测试家庭"

    duplicate = await db_client.post(
        "/api/v1/setup",
        json={
            "username": "another",
            "password": "password123",
            "household_name": "另一个家庭",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error_code"] == "SETUP_ALREADY_COMPLETED"


async def test_setup_status_before_initialization(db_client: AsyncClient, db_app: Any) -> None:
    async with db_app.state.db_session_factory() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE system.audit_logs, core.users, core.account_balances, "
                "finance.transactions, finance.transfers, finance.categories, "
                "core.accounts, core.households RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()
    status = await db_client.get("/api/v1/setup/status")
    assert status.status_code == 200
    assert status.json()["data"] == {"initialized": False, "household_name": None}

    short_password = await db_client.post(
        "/api/v1/setup",
        json={"username": "owner", "password": "short"},
    )
    assert short_password.status_code == 422
    assert short_password.json()["error_code"] == "VALIDATION_ERROR"


async def test_login_me_and_wrong_password(db_client: AsyncClient, clean_db: None) -> None:
    wrong = await db_client.post(
        "/api/v1/auth/login",
        json={"username": "owner", "password": "wrong-password"},
    )
    assert wrong.status_code == 401
    assert wrong.json()["error_code"] == "AUTH_INVALID_CREDENTIALS"

    login = await db_client.post(
        "/api/v1/auth/login",
        json={"username": "OWNER", "password": "password123"},
    )
    assert login.status_code == 200, login.text
    data = login.json()["data"]
    assert data["token_type"] == "bearer"  # noqa: S105
    assert data["user"]["username"] == "owner"
    assert data["user"]["role"] == "owner"
    assert data["household"]["name"] == "测试家庭"
    assert data["expires_in"] > 0

    headers = {"Authorization": f"Bearer {data['access_token']}"}
    me = await db_client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["data"]["username"] == "owner"
    assert me.json()["data"]["household"]["base_currency"] == "CNY"

    logout = await db_client.post("/api/v1/auth/logout")
    assert logout.status_code == 200
    assert logout.json()["data"] is None


async def test_owner_manages_members_and_last_owner_is_protected(
    db_client: AsyncClient, clean_db: None, db_app: Any
) -> None:
    listed = await db_client.get("/api/v1/users")
    assert listed.status_code == 200
    assert len(listed.json()["data"]) == 1

    created = await db_client.post(
        "/api/v1/users",
        json={
            "username": "partner",
            "password": "password123",
            "display_name": "伴侣",
            "role": "member",
        },
    )
    assert created.status_code == 201, created.text
    partner = created.json()["data"]
    assert partner["role"] == "member"

    duplicate = await db_client.post(
        "/api/v1/users",
        json={
            "username": "partner",
            "password": "password123",
            "display_name": "重复",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error_code"] == "USERNAME_TAKEN"

    partner_login = await db_client.post(
        "/api/v1/auth/login",
        json={"username": "partner", "password": "password123"},
    )
    partner_headers = {"Authorization": f"Bearer {partner_login.json()['data']['access_token']}"}
    forbidden = await db_client.post(
        "/api/v1/users",
        headers=partner_headers,
        json={
            "username": "third",
            "password": "password123",
            "display_name": "第三人",
        },
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error_code"] == "OWNER_REQUIRED"

    updated = await db_client.put(
        f"/api/v1/users/{partner['id']}",
        json={"display_name": "新名字", "password": "new-password123"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["display_name"] == "新名字"

    new_login = await db_client.post(
        "/api/v1/auth/login",
        json={"username": "partner", "password": "new-password123"},
    )
    assert new_login.status_code == 200

    me = await db_client.get("/api/v1/auth/me")
    owner_id = me.json()["data"]["id"]
    demote = await db_client.put(f"/api/v1/users/{owner_id}", json={"role": "member"})
    assert demote.status_code == 409
    assert demote.json()["error_code"] == "LAST_OWNER_PROTECTED"

    deactivate = await db_client.put(f"/api/v1/users/{owner_id}", json={"is_active": False})
    assert deactivate.status_code == 409

    missing = await db_client.put(
        "/api/v1/users/00000000-0000-0000-0000-000000000099",
        json={"display_name": "不存在"},
    )
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "USER_NOT_FOUND"


async def test_setup_options_prefill_without_writing(
    db_client: AsyncClient, clean_db: None
) -> None:
    response = await db_client.get("/api/v1/setup/options")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert {item["code"] for item in data["currencies"]} == {
        "CNY",
        "USD",
        "HKD",
        "EUR",
        "GBP",
        "JPY",
    }
    names = {item["name"] for item in data["categories"]}
    assert {"工资", "餐饮", "金融手续费"} <= names
    assert any(item["value"] == "Asia/Shanghai" for item in data["timezones"])

    status = await db_client.get("/api/v1/setup/status")
    assert status.json()["data"]["initialized"] is True


async def test_setup_writes_only_confirmed_categories_and_validates_base_currency(
    db_client: AsyncClient, db_app: Any
) -> None:
    async with db_app.state.db_session_factory() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE system.audit_logs, core.users, core.account_balances, "
                "finance.transactions, finance.transfers, finance.categories, "
                "core.accounts, core.households RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()

    not_base = await db_client.post(
        "/api/v1/setup",
        json={
            "username": "owner",
            "password": "password123",
            "base_currency": "CNY",
            "currency_codes": ["USD"],
        },
    )
    assert not_base.status_code == 400
    assert not_base.json()["error_code"] == "BASE_CURRENCY_NOT_SELECTED"

    created = await db_client.post(
        "/api/v1/setup",
        json={
            "username": "owner",
            "password": "password123",
            "household_name": "精简家庭",
            "base_currency": "CNY",
            "currency_codes": ["CNY", "USD"],
            "categories": [
                {"name": "工资", "category_type": "income", "sort_order": 10},
                {"name": "餐饮", "category_type": "expense", "sort_order": 20},
            ],
        },
    )
    assert created.status_code == 200, created.text
    token = created.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    categories = await db_client.get("/api/v1/categories?page_size=100", headers=headers)
    assert categories.status_code == 200
    assert {item["name"] for item in categories.json()["data"]["items"]} == {"工资", "餐饮"}

    duplicate = await db_client.post(
        "/api/v1/setup",
        json={"username": "other", "password": "password123"},
    )
    assert duplicate.status_code == 409


async def test_setup_writes_audit_actor(db_client: AsyncClient, clean_db: None, db_app: Any):
    from sqlalchemy import select

    async with db_app.state.db_session_factory() as session:
        logs = list(
            (
                await session.scalars(select(AuditLog).where(AuditLog.action == "setup.complete"))
            ).all()
        )
    assert len(logs) == 1
    assert logs[0].actor == "owner"


async def test_disabled_user_cannot_login(db_client: AsyncClient, clean_db: None) -> None:
    created = await db_client.post(
        "/api/v1/users",
        json={
            "username": "disabled",
            "password": "password123",
            "display_name": "停用",
            "role": "member",
        },
    )
    user_id = created.json()["data"]["id"]
    disabled = await db_client.put(f"/api/v1/users/{user_id}", json={"is_active": False})
    assert disabled.status_code == 200

    login = await db_client.post(
        "/api/v1/auth/login",
        json={"username": "disabled", "password": "password123"},
    )
    assert login.status_code == 403
    assert login.json()["error_code"] == "AUTH_ACCOUNT_DISABLED"
