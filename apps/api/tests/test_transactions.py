"""Income/expense lifecycle, reversing, filtering, and audit trail (Phase 1.2)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.transactions.models import Transaction
from app.modules.transfers.models import Transfer


async def _create_account(
    client: AsyncClient, headers: dict[str, str], **overrides: object
) -> dict:
    payload: dict[str, object] = {"name": "现金", "account_type": "cash", "currency": "CNY"}
    payload.update(overrides)
    response = await client.post("/api/v1/accounts", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _set_opening(
    client: AsyncClient,
    headers: dict[str, str],
    account_id: str,
    amount: str = "1000",
    **extra: object,
) -> dict:
    response = await client.put(
        f"/api/v1/accounts/{account_id}/opening-balance",
        headers=headers,
        json={"amount": amount, **extra},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _find_category(client: AsyncClient, headers: dict[str, str], name: str) -> dict:
    response = await client.get("/api/v1/categories?page_size=100", headers=headers)
    return next(item for item in response.json()["data"]["items"] if item["name"] == name)


async def _create_transaction(
    client: AsyncClient, headers: dict[str, str], **payload: object
) -> dict:
    response = await client.post("/api/v1/transactions", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _book_balance(response: dict, currency: str = "CNY") -> Decimal:
    line = next(item for item in response["data"]["balances"] if item["currency"] == currency)
    return Decimal(line["book_balance"])


async def test_draft_and_confirm_income_expense(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    await _set_opening(db_client, household_headers, account["id"], "1000")
    dining = await _find_category(db_client, household_headers, "餐饮")
    salary = await _find_category(db_client, household_headers, "工资")

    draft = await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        category_id=dining["id"],
        transaction_type="expense",
        amount="100.00",
        description="午餐",
        external_id="ext-1",
    )
    assert draft["status"] == "draft"
    assert draft["source"] == "manual"
    assert draft["currency"] == "CNY"
    assert Decimal(draft["amount"]) == Decimal("100.00")
    assert Decimal(draft["base_amount"]) == Decimal("100.00")
    assert Decimal(draft["exchange_rate"]) == Decimal("1")

    balances = await db_client.get(
        f"/api/v1/accounts/{account['id']}/balances", headers=household_headers
    )
    assert _book_balance(balances.json()) == Decimal("1000")

    income = await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        category_id=salary["id"],
        transaction_type="income",
        amount="50",
        status="confirmed",
    )
    assert income["status"] == "confirmed"

    balances = await db_client.get(
        f"/api/v1/accounts/{account['id']}/balances", headers=household_headers
    )
    assert _book_balance(balances.json()) == Decimal("1050")

    confirmed = await db_client.put(
        f"/api/v1/transactions/{draft['id']}",
        headers=household_headers,
        json={"status": "confirmed"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["status"] == "confirmed"

    balances = await db_client.get(
        f"/api/v1/accounts/{account['id']}/balances", headers=household_headers
    )
    assert _book_balance(balances.json()) == Decimal("950")


async def test_confirmed_expense_rejects_negative_balance(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    await _set_opening(db_client, household_headers, account["id"], "10")
    dining = await _find_category(db_client, household_headers, "餐饮")

    rejected = await db_client.post(
        "/api/v1/transactions",
        headers=household_headers,
        json={
            "account_id": account["id"],
            "category_id": dining["id"],
            "transaction_type": "expense",
            "amount": "20",
            "status": "confirmed",
        },
    )
    assert rejected.status_code == 409
    assert rejected.json()["error_code"] == "INSUFFICIENT_BALANCE"

    draft = await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        category_id=dining["id"],
        transaction_type="expense",
        amount="20",
    )
    confirm = await db_client.put(
        f"/api/v1/transactions/{draft['id']}",
        headers=household_headers,
        json={"status": "confirmed"},
    )
    assert confirm.status_code == 409
    assert confirm.json()["error_code"] == "INSUFFICIENT_BALANCE"

    fetched = await db_client.get(f"/api/v1/transactions/{draft['id']}", headers=household_headers)
    assert fetched.json()["data"]["status"] == "draft"


async def test_amount_must_be_positive_and_status_restricted(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    for amount in ("0", "-5"):
        response = await db_client.post(
            "/api/v1/transactions",
            headers=household_headers,
            json={
                "account_id": account["id"],
                "transaction_type": "income",
                "amount": amount,
            },
        )
        assert response.status_code == 422
        assert response.json()["error_code"] == "VALIDATION_ERROR"

    bad_status = await db_client.post(
        "/api/v1/transactions",
        headers=household_headers,
        json={
            "account_id": account["id"],
            "transaction_type": "income",
            "amount": "1",
            "status": "reversed",
        },
    )
    assert bad_status.status_code == 422


async def test_opening_balance_type_rejected_by_transaction_api(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    response = await db_client.post(
        "/api/v1/transactions",
        headers=household_headers,
        json={
            "account_id": account["id"],
            "transaction_type": "opening_balance",
            "amount": "10",
            "status": "confirmed",
        },
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "TRANSACTION_TYPE_INVALID"


async def test_category_and_account_validation(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    dining = await _find_category(db_client, household_headers, "餐饮")

    mismatch = await db_client.post(
        "/api/v1/transactions",
        headers=household_headers,
        json={
            "account_id": account["id"],
            "category_id": dining["id"],
            "transaction_type": "income",
            "amount": "10",
        },
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["error_code"] == "CATEGORY_TYPE_MISMATCH"

    inactive = await db_client.post(
        "/api/v1/categories",
        headers=household_headers,
        json={"name": "临时支出", "category_type": "expense", "is_active": False},
    )
    inactive_id = inactive.json()["data"]["id"]
    inactive_category = await db_client.post(
        "/api/v1/transactions",
        headers=household_headers,
        json={
            "account_id": account["id"],
            "category_id": inactive_id,
            "transaction_type": "expense",
            "amount": "10",
        },
    )
    assert inactive_category.status_code == 409
    assert inactive_category.json()["error_code"] == "CATEGORY_INACTIVE"

    await db_client.put(
        f"/api/v1/accounts/{account['id']}",
        headers=household_headers,
        json={"is_active": False},
    )
    inactive_account = await db_client.post(
        "/api/v1/transactions",
        headers=household_headers,
        json={
            "account_id": account["id"],
            "transaction_type": "income",
            "amount": "10",
        },
    )
    assert inactive_account.status_code == 409
    assert inactive_account.json()["error_code"] == "ACCOUNT_INACTIVE"

    missing_account = await db_client.post(
        "/api/v1/transactions",
        headers=household_headers,
        json={
            "account_id": "00000000-0000-0000-0000-000000000099",
            "transaction_type": "income",
            "amount": "10",
        },
    )
    assert missing_account.status_code == 404
    assert missing_account.json()["error_code"] == "ACCOUNT_NOT_FOUND"

    active_account = await _create_account(db_client, household_headers, name="仍可用的账户")
    missing_category = await db_client.post(
        "/api/v1/transactions",
        headers=household_headers,
        json={
            "account_id": active_account["id"],
            "category_id": "00000000-0000-0000-0000-000000000099",
            "transaction_type": "income",
            "amount": "10",
        },
    )
    assert missing_category.status_code == 404
    assert missing_category.json()["error_code"] == "CATEGORY_NOT_FOUND"


async def test_foreign_currency_rate_and_rounding(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    usd_account = await _create_account(
        db_client, household_headers, name="美元账户", currency="USD"
    )
    await _set_opening(db_client, household_headers, usd_account["id"], "100", exchange_rate="7.10")
    salary = await _find_category(db_client, household_headers, "工资")

    missing_rate = await db_client.post(
        "/api/v1/transactions",
        headers=household_headers,
        json={
            "account_id": usd_account["id"],
            "category_id": salary["id"],
            "transaction_type": "income",
            "amount": "10",
            "status": "confirmed",
        },
    )
    assert missing_rate.status_code == 400
    assert missing_rate.json()["error_code"] == "EXCHANGE_RATE_REQUIRED"

    created = await _create_transaction(
        db_client,
        household_headers,
        account_id=usd_account["id"],
        category_id=salary["id"],
        transaction_type="income",
        amount="10",
        currency="USD",
        exchange_rate="7.10",
        status="confirmed",
    )
    assert Decimal(created["base_amount"]) == Decimal("71.00")

    invalid_rate = await db_client.post(
        "/api/v1/transactions",
        headers=household_headers,
        json={
            "account_id": usd_account["id"],
            "transaction_type": "income",
            "amount": "10",
            "currency": "CNY",
            "exchange_rate": "2",
        },
    )
    assert invalid_rate.status_code == 400
    assert invalid_rate.json()["error_code"] == "EXCHANGE_RATE_INVALID"

    jpy_account = await _create_account(
        db_client, household_headers, name="日元账户", currency="JPY"
    )
    await _set_opening(
        db_client, household_headers, jpy_account["id"], "1000", exchange_rate="0.05"
    )
    rounded = await _create_transaction(
        db_client,
        household_headers,
        account_id=jpy_account["id"],
        transaction_type="expense",
        amount="10.5",
        currency="JPY",
        exchange_rate="0.05",
        status="confirmed",
    )
    assert Decimal(rounded["amount"]) == Decimal("10")
    assert Decimal(rounded["base_amount"]) == Decimal("0.50")
    assert rounded["exchange_rate_date"] == datetime.now(UTC).date().isoformat()


async def test_list_filters_pagination_and_sorting(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account_a = await _create_account(db_client, household_headers, name="账户A")
    account_b = await _create_account(db_client, household_headers, name="账户B")
    await _set_opening(db_client, household_headers, account_a["id"], "1000")
    await _set_opening(db_client, household_headers, account_b["id"], "1000")
    salary = await _find_category(db_client, household_headers, "工资")
    dining = await _find_category(db_client, household_headers, "餐饮")
    transport = await _find_category(db_client, household_headers, "交通")

    income = await _create_transaction(
        db_client,
        household_headers,
        account_id=account_a["id"],
        category_id=salary["id"],
        transaction_type="income",
        amount="100",
        description="工资发放",
        transaction_date="2026-01-15T09:00:00+08:00",
        status="confirmed",
    )
    lunch = await _create_transaction(
        db_client,
        household_headers,
        account_id=account_a["id"],
        category_id=dining["id"],
        transaction_type="expense",
        amount="30",
        description="午餐",
        transaction_date="2026-02-10T12:00:00+08:00",
        status="confirmed",
    )
    taxi = await _create_transaction(
        db_client,
        household_headers,
        account_id=account_b["id"],
        category_id=transport["id"],
        transaction_type="expense",
        amount="50",
        description="打车",
        transaction_date="2026-02-20T19:00:00+08:00",
    )

    async def total(query: str) -> int:
        response = await db_client.get(f"/api/v1/transactions?{query}", headers=household_headers)
        assert response.status_code == 200, response.text
        return response.json()["data"]["total"]

    # Two opening_balance rows are created by the fixtures, so the full list has 5.
    assert await total("") == 5
    assert await total(f"account_id={account_a['id']}") == 3
    assert await total(f"category_id={dining['id']}") == 1
    assert await total("transaction_type=expense") == 2
    assert await total("transaction_type=opening_balance") == 2
    assert await total("status=draft") == 1
    assert await total("currency=cny") == 5
    assert await total("min_amount=40&max_amount=60") == 1
    assert await total("keyword=%E5%8D%88") == 1
    assert await total("start_date=2026-02-01&end_date=2026-02-28") == 2
    assert await total("start_date=2030-01-01") == 0

    sorted_response = await db_client.get(
        "/api/v1/transactions?sort_by=amount&sort_order=desc", headers=household_headers
    )
    amounts = [Decimal(item["amount"]) for item in sorted_response.json()["data"]["items"]]
    assert amounts == sorted(amounts, reverse=True)

    paged = await db_client.get(
        "/api/v1/transactions?page=2&page_size=2", headers=household_headers
    )
    page_data = paged.json()["data"]
    assert page_data["page"] == 2
    assert page_data["page_size"] == 2
    assert page_data["total"] == 5
    assert len(page_data["items"]) == 2

    bad_sort = await db_client.get(
        "/api/v1/transactions?sort_by=password", headers=household_headers
    )
    assert bad_sort.status_code == 400
    assert bad_sort.json()["error_code"] == "INVALID_SORT_FIELD"

    ids = {
        item["id"]
        for item in (
            await db_client.get("/api/v1/transactions?page_size=100", headers=household_headers)
        ).json()["data"]["items"]
    }
    assert {income["id"], lunch["id"], taxi["id"]} <= ids


async def test_get_is_household_scoped(
    db_client: AsyncClient,
    household_headers: dict[str, str],
    auth_for_household: Any,
    create_household: Any,
):
    account = await _create_account(db_client, household_headers)
    transaction = await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        transaction_type="income",
        amount="1",
    )

    fetched = await db_client.get(
        f"/api/v1/transactions/{transaction['id']}", headers=household_headers
    )
    assert fetched.status_code == 200

    missing = await db_client.get(
        "/api/v1/transactions/00000000-0000-0000-0000-000000000099",
        headers=household_headers,
    )
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "TRANSACTION_NOT_FOUND"

    second_id = await create_household()
    second_headers = await auth_for_household(second_id)
    other_account = await _create_account(db_client, second_headers, name="别人的账户")
    other_transaction = await _create_transaction(
        db_client,
        second_headers,
        account_id=other_account["id"],
        transaction_type="income",
        amount="1",
    )

    hidden = await db_client.get(
        f"/api/v1/transactions/{other_transaction['id']}", headers=household_headers
    )
    assert hidden.status_code == 404

    hidden_delete = await db_client.delete(
        f"/api/v1/transactions/{other_transaction['id']}", headers=household_headers
    )
    assert hidden_delete.status_code == 404


async def test_update_draft_then_immutable(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    await _set_opening(db_client, household_headers, account["id"], "1000")
    dining = await _find_category(db_client, household_headers, "餐饮")
    salary = await _find_category(db_client, household_headers, "工资")

    transaction = await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        transaction_type="expense",
        amount="10",
        description="旧描述",
    )

    updated = await db_client.put(
        f"/api/v1/transactions/{transaction['id']}",
        headers=household_headers,
        json={
            "category_id": dining["id"],
            "amount": "20",
            "description": "新描述",
            "transaction_date": "2026-05-01T00:00:00+08:00",
            "exchange_rate_date": "2026-05-01",
            "external_id": "ext-updated",
        },
    )
    assert updated.status_code == 200, updated.text
    data = updated.json()["data"]
    assert Decimal(data["amount"]) == Decimal("20.00")
    assert data["description"] == "新描述"
    assert data["external_id"] == "ext-updated"
    assert data["category_id"] == dining["id"]

    change_currency = await db_client.put(
        f"/api/v1/transactions/{transaction['id']}",
        headers=household_headers,
        json={"currency": "USD"},
    )
    assert change_currency.status_code == 400
    assert change_currency.json()["error_code"] == "EXCHANGE_RATE_REQUIRED"

    change_type_mismatch = await db_client.put(
        f"/api/v1/transactions/{transaction['id']}",
        headers=household_headers,
        json={"transaction_type": "income", "category_id": salary["id"]},
    )
    assert change_type_mismatch.status_code == 200

    confirmed = await db_client.put(
        f"/api/v1/transactions/{transaction['id']}",
        headers=household_headers,
        json={"status": "confirmed"},
    )
    assert confirmed.status_code == 200

    immutable = await db_client.put(
        f"/api/v1/transactions/{transaction['id']}",
        headers=household_headers,
        json={"amount": "99"},
    )
    assert immutable.status_code == 409
    assert immutable.json()["error_code"] == "TRANSACTION_FIELD_IMMUTABLE"


async def _confirmed_expense(
    db_client: AsyncClient, household_headers: dict[str, str], **payload: object
) -> dict:
    account = await _create_account(db_client, household_headers)
    await _set_opening(db_client, household_headers, account["id"], "1000")
    transaction = await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        transaction_type="expense",
        amount="10",
        description="原始描述",
        status="confirmed",
        **payload,
    )
    return transaction


async def test_confirmed_metadata_edit(
    db_client: AsyncClient, db_app, household_headers: dict[str, str]
):
    dining = await _find_category(db_client, household_headers, "餐饮")
    transaction = await _confirmed_expense(db_client, household_headers)

    response = await db_client.put(
        f"/api/v1/transactions/{transaction['id']}",
        headers=household_headers,
        json={"category_id": dining["id"], "description": "更正后的描述"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["category_id"] == dining["id"]
    assert data["description"] == "更正后的描述"
    assert Decimal(data["amount"]) == Decimal("10.00")
    assert data["status"] == "confirmed"

    async with db_app.state.db_session_factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(AuditLog).where(
                        AuditLog.entity_type == "transaction",
                        AuditLog.entity_id == UUID(transaction["id"]),
                        AuditLog.action == "transaction.update_metadata",
                    )
                )
            ).all()
        )
    assert len(rows) == 1
    audit = rows[0]
    assert audit.before_data is not None
    assert audit.after_data is not None
    assert audit.before_data["description"] == "原始描述"
    assert audit.after_data["description"] == "更正后的描述"
    assert audit.after_data["category_id"] == dining["id"]

    # No-op edit (same values) must not write an audit record.
    no_op = await db_client.put(
        f"/api/v1/transactions/{transaction['id']}",
        headers=household_headers,
        json={"category_id": dining["id"], "description": "更正后的描述"},
    )
    assert no_op.status_code == 200
    async with db_app.state.db_session_factory() as session:
        count = len(
            list(
                (
                    await session.scalars(
                        select(AuditLog).where(
                            AuditLog.entity_type == "transaction",
                            AuditLog.entity_id == UUID(transaction["id"]),
                            AuditLog.action == "transaction.update_metadata",
                        )
                    )
                ).all()
            )
        )
    assert count == 1


async def test_confirmed_metadata_edit_allows_clearing_fields(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    dining = await _find_category(db_client, household_headers, "餐饮")
    transaction = await _confirmed_expense(db_client, household_headers, category_id=dining["id"])

    response = await db_client.put(
        f"/api/v1/transactions/{transaction['id']}",
        headers=household_headers,
        json={"category_id": None, "description": None},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["category_id"] is None
    assert data["description"] is None


async def test_confirmed_metadata_edit_rejects_financial_fields(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    other = await _create_account(db_client, household_headers, name="转入账户")
    transaction = await _confirmed_expense(db_client, household_headers)

    attempts = [
        {"amount": "20"},
        {"status": "draft"},
        {"transaction_type": "income"},
        {"currency": "USD"},
        {"exchange_rate": "2"},
        {"exchange_rate_date": "2026-05-01"},
        {"transaction_date": "2026-05-01T00:00:00+08:00"},
        {"account_id": other["id"]},
        {"external_id": "ext-1"},
    ]
    for payload in attempts:
        response = await db_client.put(
            f"/api/v1/transactions/{transaction['id']}",
            headers=household_headers,
            json=payload,
        )
        assert response.status_code == 409, payload
        assert response.json()["error_code"] == "TRANSACTION_FIELD_IMMUTABLE", payload

    # Financial fields must be rejected even when sent alongside metadata.
    combined = await db_client.put(
        f"/api/v1/transactions/{transaction['id']}",
        headers=household_headers,
        json={"description": "混合请求", "amount": "20"},
    )
    assert combined.status_code == 409
    assert combined.json()["error_code"] == "TRANSACTION_FIELD_IMMUTABLE"

    # Category type must still match the transaction type.
    salary = await _find_category(db_client, household_headers, "工资")
    mismatch = await db_client.put(
        f"/api/v1/transactions/{transaction['id']}",
        headers=household_headers,
        json={"category_id": salary["id"]},
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["error_code"] == "CATEGORY_TYPE_MISMATCH"

    # The account was only created to be referenced; opening not needed.
    assert account["id"]


async def test_reversed_transaction_rejects_metadata_edit(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    transaction = await _confirmed_expense(db_client, household_headers)
    await db_client.post(
        f"/api/v1/transactions/{transaction['id']}/reverse", headers=household_headers
    )

    response = await db_client.put(
        f"/api/v1/transactions/{transaction['id']}",
        headers=household_headers,
        json={"description": "冲销后"},
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "TRANSACTION_NOT_EDITABLE"


async def test_confirmed_metadata_edit_rejects_transfer_linked(
    db_client: AsyncClient, db_app, household: dict, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    other = await _create_account(db_client, household_headers, name="转入账户")

    async with db_app.state.db_session_factory() as session:
        transfer = Transfer(
            household_id=UUID(household["id"]),
            from_account_id=UUID(account["id"]),
            to_account_id=UUID(other["id"]),
            from_amount=Decimal("10"),
            from_currency="CNY",
            to_amount=Decimal("10"),
            to_currency="CNY",
            exchange_rate=Decimal("1"),
            fee=Decimal("1"),
            fee_currency="CNY",
            transfer_date=datetime(2026, 1, 1, tzinfo=UTC),
            status="confirmed",
        )
        session.add(transfer)
        await session.flush()
        fee_transaction = Transaction(
            household_id=UUID(household["id"]),
            account_id=UUID(account["id"]),
            transaction_type="expense",
            amount=Decimal("1"),
            currency="CNY",
            base_amount=Decimal("1"),
            base_currency="CNY",
            exchange_rate=Decimal("1"),
            exchange_rate_date=date(2026, 1, 1),
            transaction_date=datetime(2026, 1, 1, tzinfo=UTC),
            source="system",
            status="confirmed",
            transfer_id=transfer.id,
        )
        session.add(fee_transaction)
        await session.commit()
        fee_id = fee_transaction.id

    response = await db_client.put(
        f"/api/v1/transactions/{fee_id}",
        headers=household_headers,
        json={"description": "改手续费"},
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "TRANSACTION_LINKED_TO_TRANSFER"


async def test_update_with_expected_updated_at(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    dining = await _find_category(db_client, household_headers, "餐饮")
    transaction = await _confirmed_expense(db_client, household_headers)

    stale = await db_client.put(
        f"/api/v1/transactions/{transaction['id']}",
        headers=household_headers,
        json={
            "description": "过期版本",
            "expected_updated_at": "2020-01-01T00:00:00Z",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error_code"] == "TRANSACTION_CONFLICT"

    current = await db_client.get(
        f"/api/v1/transactions/{transaction['id']}", headers=household_headers
    )
    fresh_updated_at = current.json()["data"]["updated_at"]

    ok = await db_client.put(
        f"/api/v1/transactions/{transaction['id']}",
        headers=household_headers,
        json={
            "category_id": dining["id"],
            "description": "并发安全更新",
            "expected_updated_at": fresh_updated_at,
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["description"] == "并发安全更新"

    # The edit bumped updated_at: replaying with the old token now conflicts.
    replay = await db_client.put(
        f"/api/v1/transactions/{transaction['id']}",
        headers=household_headers,
        json={
            "description": "重放",
            "expected_updated_at": fresh_updated_at,
        },
    )
    assert replay.status_code == 409
    assert replay.json()["error_code"] == "TRANSACTION_CONFLICT"


async def test_concurrent_edits_with_same_token_one_wins(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    """Two writers holding the same token race: the row lock must let exactly
    one commit; the loser reloads under lock and gets TRANSACTION_CONFLICT."""
    import asyncio

    transaction = await _confirmed_expense(db_client, household_headers)
    current = await db_client.get(
        f"/api/v1/transactions/{transaction['id']}", headers=household_headers
    )
    token = current.json()["data"]["updated_at"]

    first, second = await asyncio.gather(
        db_client.put(
            f"/api/v1/transactions/{transaction['id']}",
            headers=household_headers,
            json={"description": "成员A", "expected_updated_at": token},
        ),
        db_client.put(
            f"/api/v1/transactions/{transaction['id']}",
            headers=household_headers,
            json={"description": "成员B", "expected_updated_at": token},
        ),
    )
    outcomes = sorted([first.status_code, second.status_code])
    assert outcomes == [200, 409], (first.text, second.text)
    loser = second if second.status_code == 409 else first
    assert loser.json()["error_code"] == "TRANSACTION_CONFLICT"

    final = await db_client.get(
        f"/api/v1/transactions/{transaction['id']}", headers=household_headers
    )
    winner_description = final.json()["data"]["description"]
    assert winner_description in {"成员A", "成员B"}
    assert final.json()["data"]["description"] == winner_description


async def test_reversed_row_reports_immutable_even_with_stale_token(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    transaction = await _confirmed_expense(db_client, household_headers)
    await db_client.post(
        f"/api/v1/transactions/{transaction['id']}/reverse", headers=household_headers
    )

    response = await db_client.put(
        f"/api/v1/transactions/{transaction['id']}",
        headers=household_headers,
        json={"description": "过期令牌", "expected_updated_at": "2020-01-01T00:00:00Z"},
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "TRANSACTION_NOT_EDITABLE"


async def test_confirmed_metadata_edit_rejects_opening_balance(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    opening = await _set_opening(db_client, household_headers, account["id"], "100")

    response = await db_client.put(
        f"/api/v1/transactions/{opening['id']}",
        headers=household_headers,
        json={"description": "改期初描述"},
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "TRANSACTION_NOT_EDITABLE"


async def test_delete_only_draft(db_client: AsyncClient, household_headers: dict[str, str]):
    account = await _create_account(db_client, household_headers)
    await _set_opening(db_client, household_headers, account["id"], "100")

    draft = await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        transaction_type="income",
        amount="5",
    )
    deleted = await db_client.delete(
        f"/api/v1/transactions/{draft['id']}", headers=household_headers
    )
    assert deleted.status_code == 200
    assert deleted.json()["success"] is True

    gone = await db_client.get(f"/api/v1/transactions/{draft['id']}", headers=household_headers)
    assert gone.status_code == 404

    confirmed = await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        transaction_type="income",
        amount="5",
        status="confirmed",
    )
    blocked = await db_client.delete(
        f"/api/v1/transactions/{confirmed['id']}", headers=household_headers
    )
    assert blocked.status_code == 409
    assert blocked.json()["error_code"] == "TRANSACTION_NOT_DELETABLE"


async def test_reverse_expense_restores_balance(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    await _set_opening(db_client, household_headers, account["id"], "100")
    dining = await _find_category(db_client, household_headers, "餐饮")

    expense = await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        category_id=dining["id"],
        transaction_type="expense",
        amount="40",
        status="confirmed",
    )

    reversed_response = await db_client.post(
        f"/api/v1/transactions/{expense['id']}/reverse",
        headers=household_headers,
        json={"description": "记错了"},
    )
    assert reversed_response.status_code == 201, reversed_response.text
    reversal = reversed_response.json()["data"]
    assert reversal["transaction_type"] == "income"
    assert Decimal(reversal["amount"]) == Decimal("40.00")
    assert reversal["reverses_transaction_id"] == expense["id"]
    assert reversal["source"] == "system"
    assert reversal["status"] == "confirmed"
    assert reversal["description"] == "记错了"
    assert reversal["category_id"] == dining["id"]

    original = await db_client.get(
        f"/api/v1/transactions/{expense['id']}", headers=household_headers
    )
    assert original.json()["data"]["status"] == "reversed"

    balances = await db_client.get(
        f"/api/v1/accounts/{account['id']}/balances", headers=household_headers
    )
    assert _book_balance(balances.json()) == Decimal("100")

    again = await db_client.post(
        f"/api/v1/transactions/{expense['id']}/reverse", headers=household_headers
    )
    assert again.status_code == 409
    assert again.json()["error_code"] == "TRANSACTION_NOT_REVERSIBLE"

    immutable = await db_client.put(
        f"/api/v1/transactions/{expense['id']}",
        headers=household_headers,
        json={"description": "不允许"},
    )
    assert immutable.status_code == 409

    undeletable = await db_client.delete(
        f"/api/v1/transactions/{expense['id']}", headers=household_headers
    )
    assert undeletable.status_code == 409


async def test_reverse_income_requires_balance(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    income = await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        transaction_type="income",
        amount="100",
        status="confirmed",
    )
    await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        transaction_type="expense",
        amount="100",
        status="confirmed",
    )

    rejected = await db_client.post(
        f"/api/v1/transactions/{income['id']}/reverse", headers=household_headers
    )
    assert rejected.status_code == 409
    assert rejected.json()["error_code"] == "INSUFFICIENT_BALANCE"

    still_confirmed = await db_client.get(
        f"/api/v1/transactions/{income['id']}", headers=household_headers
    )
    assert still_confirmed.json()["data"]["status"] == "confirmed"


async def test_reverse_rejects_draft_and_opening_balance(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    opening = await _set_opening(db_client, household_headers, account["id"], "10")
    draft = await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        transaction_type="income",
        amount="1",
    )

    draft_reverse = await db_client.post(
        f"/api/v1/transactions/{draft['id']}/reverse", headers=household_headers
    )
    assert draft_reverse.status_code == 409
    assert draft_reverse.json()["error_code"] == "TRANSACTION_NOT_REVERSIBLE"

    opening_reverse = await db_client.post(
        f"/api/v1/transactions/{opening['id']}/reverse", headers=household_headers
    )
    assert opening_reverse.status_code == 409
    assert opening_reverse.json()["error_code"] == "TRANSACTION_NOT_REVERSIBLE"


async def test_reverse_rejects_transfer_linked_transaction(
    db_client: AsyncClient, db_app, household: dict, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    other = await _create_account(db_client, household_headers, name="转入账户")

    async with db_app.state.db_session_factory() as session:
        transfer = Transfer(
            household_id=UUID(household["id"]),
            from_account_id=UUID(account["id"]),
            to_account_id=UUID(other["id"]),
            from_amount=Decimal("10"),
            from_currency="CNY",
            to_amount=Decimal("10"),
            to_currency="CNY",
            exchange_rate=Decimal("1"),
            fee=Decimal("0"),
            fee_currency="CNY",
            transfer_date=datetime(2026, 1, 1, tzinfo=UTC),
            status="confirmed",
        )
        session.add(transfer)
        await session.flush()
        linked = Transaction(
            household_id=UUID(household["id"]),
            account_id=UUID(account["id"]),
            transaction_type="expense",
            amount=Decimal("1"),
            currency="CNY",
            base_amount=Decimal("1"),
            base_currency="CNY",
            exchange_rate=Decimal("1"),
            exchange_rate_date=date(2026, 1, 1),
            transaction_date=datetime(2026, 1, 1, tzinfo=UTC),
            source="system",
            status="confirmed",
            transfer_id=transfer.id,
        )
        session.add(linked)
        await session.commit()
        linked_id = linked.id

    response = await db_client.post(
        f"/api/v1/transactions/{linked_id}/reverse", headers=household_headers
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "TRANSACTION_LINKED_TO_TRANSFER"


async def test_audit_trail_for_lifecycle(
    db_client: AsyncClient, db_app, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    await _set_opening(db_client, household_headers, account["id"], "100")

    draft = await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        transaction_type="expense",
        amount="10",
    )
    await db_client.put(
        f"/api/v1/transactions/{draft['id']}",
        headers=household_headers,
        json={"status": "confirmed"},
    )
    await db_client.post(f"/api/v1/transactions/{draft['id']}/reverse", headers=household_headers)

    removable = await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        transaction_type="income",
        amount="1",
    )
    await db_client.delete(f"/api/v1/transactions/{removable['id']}", headers=household_headers)

    async with db_app.state.db_session_factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(AuditLog)
                    .where(AuditLog.entity_type == "transaction")
                    .order_by(AuditLog.created_at)
                )
            ).all()
        )
    actions = [row.action for row in rows]
    assert actions[0] == "opening_balance.set"
    assert "transaction.create" in actions
    assert "transaction.confirm" in actions
    assert "transaction.reverse" in actions
    assert "transaction.delete" in actions

    reverse_audit = next(row for row in rows if row.action == "transaction.reverse")
    assert reverse_audit.before_data is not None
    assert reverse_audit.after_data is not None
    assert reverse_audit.after_data["reversal_id"]
    assert reverse_audit.after_data["status"] == "reversed"


async def test_openapi_documents_transaction_paths(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    payload = (await db_client.get("/openapi.json")).json()
    expected = {
        "/api/v1/transactions",
        "/api/v1/transactions/{transaction_id}",
        "/api/v1/transactions/{transaction_id}/reverse",
    }
    assert expected <= set(payload["paths"])
