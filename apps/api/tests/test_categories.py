"""Category hierarchy validation, protection, and scoping."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from httpx import AsyncClient

from app.modules.accounts.models import Account
from app.modules.transactions.models import Transaction


async def _find_category(client: AsyncClient, headers: dict[str, str], name: str) -> dict:
    response = await client.get("/api/v1/categories?page_size=100", headers=headers)
    return next(item for item in response.json()["data"]["items"] if item["name"] == name)


async def test_default_categories_and_filters(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    response = await db_client.get("/api/v1/categories?page_size=100", headers=household_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 13

    income = await db_client.get(
        "/api/v1/categories?category_type=income&page_size=100", headers=household_headers
    )
    assert income.json()["data"]["total"] == 5

    inactive = await db_client.get(
        "/api/v1/categories?is_active=false&page_size=100", headers=household_headers
    )
    assert inactive.json()["data"]["total"] == 0

    sorted_desc = await db_client.get(
        "/api/v1/categories?sort_by=sort_order&sort_order=desc", headers=household_headers
    )
    assert sorted_desc.status_code == 200
    assert int(sorted_desc.json()["data"]["items"][0]["sort_order"]) >= 0

    bad_sort = await db_client.get(
        "/api/v1/categories?sort_by=parent_id", headers=household_headers
    )
    assert bad_sort.status_code == 400


async def test_create_child_and_list_by_parent(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    parent = await _find_category(db_client, household_headers, "餐饮")
    child = await db_client.post(
        "/api/v1/categories",
        headers=household_headers,
        json={
            "name": "外卖",
            "category_type": "expense",
            "parent_id": parent["id"],
            "sort_order": 1,
        },
    )
    assert child.status_code == 201, child.text
    assert child.json()["data"]["parent_id"] == parent["id"]

    children = await db_client.get(
        f"/api/v1/categories?parent_id={parent['id']}", headers=household_headers
    )
    assert children.json()["data"]["total"] == 1

    fetched = await db_client.get(
        f"/api/v1/categories/{child.json()['data']['id']}", headers=household_headers
    )
    assert fetched.status_code == 200

    updated = await db_client.put(
        f"/api/v1/categories/{child.json()['data']['id']}",
        headers=household_headers,
        json={"name": "堂食", "is_active": False, "icon": "utensils"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "堂食"
    assert updated.json()["data"]["is_active"] is False

    moved_to_root = await db_client.put(
        f"/api/v1/categories/{child.json()['data']['id']}",
        headers=household_headers,
        json={"parent_id": None},
    )
    assert moved_to_root.status_code == 200
    assert moved_to_root.json()["data"]["parent_id"] is None


async def test_category_hierarchy_rules(
    db_client: AsyncClient,
    household: dict,
    household_headers: dict[str, str],
    auth_for_household: Any,
    create_household: Any,
):
    dining = await _find_category(db_client, household_headers, "餐饮")
    salary = await _find_category(db_client, household_headers, "工资")

    type_mismatch = await db_client.post(
        "/api/v1/categories",
        headers=household_headers,
        json={"name": "错误", "category_type": "income", "parent_id": dining["id"]},
    )
    assert type_mismatch.status_code == 400
    assert type_mismatch.json()["error_code"] == "CATEGORY_TYPE_MISMATCH"

    child = await db_client.post(
        "/api/v1/categories",
        headers=household_headers,
        json={"name": "外卖", "category_type": "expense", "parent_id": dining["id"]},
    )
    grandchild = await db_client.post(
        "/api/v1/categories",
        headers=household_headers,
        json={
            "name": "三级",
            "category_type": "expense",
            "parent_id": child.json()["data"]["id"],
        },
    )
    assert grandchild.status_code == 400
    assert grandchild.json()["error_code"] == "CATEGORY_LEVEL_EXCEEDED"

    self_parent = await db_client.put(
        f"/api/v1/categories/{dining['id']}",
        headers=household_headers,
        json={"parent_id": dining["id"]},
    )
    assert self_parent.status_code == 400
    assert self_parent.json()["error_code"] == "CATEGORY_PARENT_INVALID"

    move_with_children = await db_client.put(
        f"/api/v1/categories/{dining['id']}",
        headers=household_headers,
        json={"parent_id": salary["id"]},
    )
    assert move_with_children.status_code == 400

    type_change_with_children = await db_client.put(
        f"/api/v1/categories/{dining['id']}",
        headers=household_headers,
        json={"category_type": "income"},
    )
    assert type_change_with_children.status_code == 400
    assert type_change_with_children.json()["error_code"] == "CATEGORY_HAS_CHILDREN"

    second_id = await create_household()
    second_headers = await auth_for_household(second_id)
    other_parent_response = await db_client.post(
        "/api/v1/categories",
        headers=second_headers,
        json={"name": "餐饮", "category_type": "expense"},
    )
    assert other_parent_response.status_code == 201, other_parent_response.text
    other_parent = other_parent_response.json()["data"]
    cross_household = await db_client.post(
        "/api/v1/categories",
        headers=second_headers,
        json={
            "name": "跨家庭",
            "category_type": "expense",
            "parent_id": dining["id"],
        },
    )
    assert cross_household.status_code == 400
    assert cross_household.json()["error_code"] == "CATEGORY_PARENT_MISMATCH"

    missing = await db_client.post(
        "/api/v1/categories",
        headers=household_headers,
        json={
            "name": "无父",
            "category_type": "expense",
            "parent_id": "00000000-0000-0000-0000-000000000099",
        },
    )
    assert missing.status_code == 404

    fetched_other = await db_client.get(
        f"/api/v1/categories/{other_parent['id']}", headers=household_headers
    )
    assert fetched_other.status_code == 404


async def test_delete_category_rules(
    db_client: AsyncClient, db_app, household: dict, household_headers: dict[str, str]
):
    fee = await _find_category(db_client, household_headers, "金融手续费")
    protected = await db_client.delete(f"/api/v1/categories/{fee['id']}", headers=household_headers)
    assert protected.status_code == 409
    assert protected.json()["error_code"] == "CATEGORY_SYSTEM_PROTECTED"

    rename_protected = await db_client.put(
        f"/api/v1/categories/{fee['id']}",
        headers=household_headers,
        json={"name": "改名手续费"},
    )
    assert rename_protected.status_code == 409
    assert rename_protected.json()["error_code"] == "CATEGORY_SYSTEM_PROTECTED"

    dining = await _find_category(db_client, household_headers, "餐饮")
    child = await db_client.post(
        "/api/v1/categories",
        headers=household_headers,
        json={"name": "外卖", "category_type": "expense", "parent_id": dining["id"]},
    )
    has_children = await db_client.delete(
        f"/api/v1/categories/{dining['id']}", headers=household_headers
    )
    assert has_children.status_code == 409
    assert has_children.json()["error_code"] == "CATEGORY_HAS_CHILDREN"

    deleted = await db_client.delete(
        f"/api/v1/categories/{child.json()['data']['id']}", headers=household_headers
    )
    assert deleted.status_code == 200

    account = await db_client.post(
        "/api/v1/accounts", headers=household_headers, json={"name": "现金"}
    )
    account_id = UUID(account.json()["data"]["id"])
    async with db_app.state.db_session_factory() as session:
        assert await session.get(Account, account_id) is not None
        session.add(
            Transaction(
                household_id=UUID(household["id"]),
                account_id=account_id,
                category_id=UUID(dining["id"]),
                transaction_type="expense",
                amount=Decimal("10"),
                currency="CNY",
                base_amount=Decimal("10"),
                base_currency="CNY",
                exchange_rate=Decimal("1"),
                exchange_rate_date=date(2026, 1, 1),
                transaction_date=datetime(2026, 1, 1, tzinfo=UTC),
                source="manual",
                status="confirmed",
            )
        )
        await session.commit()

    in_use = await db_client.delete(f"/api/v1/categories/{dining['id']}", headers=household_headers)
    assert in_use.status_code == 409
    assert in_use.json()["error_code"] == "CATEGORY_IN_USE"

    missing = await db_client.delete(
        "/api/v1/categories/00000000-0000-0000-0000-000000000099",
        headers=household_headers,
    )
    assert missing.status_code == 404


async def test_create_root_category_and_update_type_without_children(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    created = await db_client.post(
        "/api/v1/categories",
        headers=household_headers,
        json={"name": "投资收入", "category_type": "income", "icon": "trending-up"},
    )
    assert created.status_code == 201
    category_id = created.json()["data"]["id"]

    updated = await db_client.put(
        f"/api/v1/categories/{category_id}",
        headers=household_headers,
        json={"category_type": "expense", "sort_order": 5},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["category_type"] == "expense"

    fetched = await db_client.get(f"/api/v1/categories/{category_id}", headers=household_headers)
    assert fetched.json()["data"]["sort_order"] == 5
