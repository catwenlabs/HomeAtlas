"""Accounts, opening balances, live balances, snapshots, and deletion rules."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select

from app.modules.accounts.models import AccountBalance
from app.modules.audit.models import AuditLog
from app.modules.transactions.models import Transaction
from app.modules.transfers.models import Transfer


async def _create_account(
    client: AsyncClient, headers: dict[str, str], **overrides: object
) -> dict:
    payload: dict[str, object] = {"name": "中国银行", "account_type": "bank", "currency": "CNY"}
    payload.update(overrides)
    response = await client.post("/api/v1/accounts", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_account_crud_and_filters(db_client: AsyncClient, household_headers: dict[str, str]):
    account = await _create_account(
        db_client, household_headers, institution="中行", external_ref="6222"
    )
    assert account["currency"] == "CNY"
    assert account["is_active"] is True

    listing = await db_client.get(
        "/api/v1/accounts?is_active=true&sort_by=name", headers=household_headers
    )
    assert listing.status_code == 200
    assert listing.json()["data"]["total"] == 1

    fetched = await db_client.get(f"/api/v1/accounts/{account['id']}", headers=household_headers)
    assert fetched.status_code == 200
    assert fetched.json()["data"]["institution"] == "中行"

    updated = await db_client.put(
        f"/api/v1/accounts/{account['id']}",
        headers=household_headers,
        json={
            "name": "招商银行",
            "is_active": False,
            "currency": "USD",
            "institution": None,
        },
    )
    assert updated.status_code == 200
    data = updated.json()["data"]
    assert data["name"] == "招商银行"
    assert data["is_active"] is False
    assert data["currency"] == "USD"
    assert data["institution"] is None

    deleted = await db_client.delete(f"/api/v1/accounts/{account['id']}", headers=household_headers)
    assert deleted.status_code == 200
    assert deleted.json()["success"] is True

    missing = await db_client.get(f"/api/v1/accounts/{account['id']}", headers=household_headers)
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "ACCOUNT_NOT_FOUND"


async def test_create_account_rejects_unknown_currency(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    response = await db_client.post(
        "/api/v1/accounts", headers=household_headers, json={"name": "X", "currency": "XXX"}
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "CURRENCY_NOT_FOUND"


async def test_account_is_scoped_to_household(
    db_client: AsyncClient, household: dict, household_headers: dict[str, str]
):
    second = await db_client.post("/api/v1/households", json={"name": "第二家"})
    second_id = second.json()["data"]["id"]
    second_headers = {"X-Household-Id": second_id}
    second_account = await _create_account(db_client, second_headers, name="第二账户")

    response = await db_client.get(
        f"/api/v1/accounts/{second_account['id']}", headers=household_headers
    )
    assert response.status_code == 404

    wrong_delete = await db_client.delete(
        f"/api/v1/accounts/{second_account['id']}", headers=household_headers
    )
    assert wrong_delete.status_code == 404


async def test_opening_balance_create_update_and_audit(
    db_client: AsyncClient,
    db_app,
    household_headers: dict[str, str],
):
    account = await _create_account(db_client, household_headers)

    created = await db_client.put(
        f"/api/v1/accounts/{account['id']}/opening-balance",
        headers=household_headers,
        json={"amount": "1000.005", "description": "开账"},
    )
    assert created.status_code == 200, created.text
    transaction = created.json()["data"]
    assert transaction["transaction_type"] == "opening_balance"
    assert transaction["status"] == "confirmed"
    assert Decimal(transaction["amount"]) == Decimal("1000.00")
    assert Decimal(transaction["base_amount"]) == Decimal("1000.00")

    updated = await db_client.put(
        f"/api/v1/accounts/{account['id']}/opening-balance",
        headers=household_headers,
        json={"amount": "-250.50", "description": "调整"},
    )
    assert updated.status_code == 200
    updated_transaction = updated.json()["data"]
    assert updated_transaction["id"] == transaction["id"]
    assert Decimal(updated_transaction["amount"]) == Decimal("-250.50")

    async with db_app.state.db_session_factory() as session:
        audits = list(
            (
                await session.scalars(
                    select(AuditLog)
                    .where(AuditLog.entity_type == "transaction")
                    .order_by(AuditLog.created_at)
                )
            ).all()
        )
    assert [audit.action for audit in audits] == [
        "opening_balance.set",
        "opening_balance.update",
    ]
    assert audits[1].before_data is not None
    assert audits[1].after_data is not None

    balances = await db_client.get(
        f"/api/v1/accounts/{account['id']}/balances", headers=household_headers
    )
    assert balances.status_code == 200
    line = balances.json()["data"]["balances"][0]
    assert line["currency"] == "CNY"
    assert Decimal(line["book_balance"]) == Decimal("-250.50")
    assert line["latest_snapshot"] is None


async def test_foreign_currency_opening_balance_requires_rate(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers, currency="USD")

    missing_rate = await db_client.put(
        f"/api/v1/accounts/{account['id']}/opening-balance",
        headers=household_headers,
        json={"amount": "100.00"},
    )
    assert missing_rate.status_code == 400
    assert missing_rate.json()["error_code"] == "EXCHANGE_RATE_REQUIRED"

    created = await db_client.put(
        f"/api/v1/accounts/{account['id']}/opening-balance",
        headers=household_headers,
        json={"amount": "100.00", "exchange_rate": "7.100000"},
    )
    assert created.status_code == 200
    assert Decimal(created.json()["data"]["base_amount"]) == Decimal("710.00")

    bad_rate = await db_client.put(
        f"/api/v1/accounts/{account['id']}/opening-balance",
        headers=household_headers,
        json={"amount": "100.00", "currency": "CNY", "exchange_rate": "2"},
    )
    assert bad_rate.status_code == 400
    assert bad_rate.json()["error_code"] == "EXCHANGE_RATE_INVALID"


async def test_opening_balance_rounds_per_currency_decimals(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers, currency="JPY")
    response = await db_client.put(
        f"/api/v1/accounts/{account['id']}/opening-balance",
        headers=household_headers,
        json={"amount": "1000.5", "exchange_rate": "0.05"},
    )
    assert response.status_code == 200
    assert Decimal(response.json()["data"]["amount"]) == Decimal("1000")
    assert Decimal(response.json()["data"]["base_amount"]) == Decimal("50.00")


async def test_unknown_opening_currency_returns_404(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    response = await db_client.put(
        f"/api/v1/accounts/{account['id']}/opening-balance",
        headers=household_headers,
        json={"amount": "10", "currency": "XXX"},
    )
    assert response.status_code == 404


async def test_delete_account_blocked_by_opening_balance(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    await db_client.put(
        f"/api/v1/accounts/{account['id']}/opening-balance",
        headers=household_headers,
        json={"amount": "10"},
    )
    response = await db_client.delete(
        f"/api/v1/accounts/{account['id']}", headers=household_headers
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "ACCOUNT_HAS_TRANSACTIONS"


async def test_balances_include_transfers_snapshots_and_exclude_drafts(
    db_client: AsyncClient, db_app, household: dict, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    account_id = UUID(account["id"])
    household_id = UUID(household["id"])

    async with db_app.state.db_session_factory() as session:
        session.add(
            Transaction(
                household_id=household_id,
                account_id=account_id,
                transaction_type="opening_balance",
                amount=Decimal("100"),
                currency="CNY",
                base_amount=Decimal("100"),
                base_currency="CNY",
                exchange_rate=Decimal("1"),
                exchange_rate_date=date(2026, 1, 1),
                transaction_date=datetime(2026, 1, 1, tzinfo=UTC),
                source="manual",
                status="confirmed",
            )
        )
        session.add(
            Transaction(
                household_id=household_id,
                account_id=account_id,
                transaction_type="expense",
                amount=Decimal("999"),
                currency="CNY",
                base_amount=Decimal("999"),
                base_currency="CNY",
                exchange_rate=Decimal("1"),
                exchange_rate_date=date(2026, 1, 1),
                transaction_date=datetime(2026, 1, 1, tzinfo=UTC),
                source="manual",
                status="draft",
            )
        )
        transfer = Transfer(
            household_id=household_id,
            from_account_id=account_id,
            to_account_id=account_id,
            from_amount=Decimal("40"),
            from_currency="CNY",
            to_amount=Decimal("5"),
            to_currency="USD",
            exchange_rate=Decimal("0.125"),
            base_amount=Decimal("40"),
            base_currency="CNY",
            fee=Decimal("2"),
            fee_currency="CNY",
            transfer_date=datetime(2026, 1, 2, tzinfo=UTC),
            status="confirmed",
        )
        session.add(transfer)
        await session.flush()
        session.add(
            Transaction(
                household_id=household_id,
                account_id=account_id,
                transaction_type="expense",
                amount=Decimal("2"),
                currency="CNY",
                base_amount=Decimal("2"),
                base_currency="CNY",
                exchange_rate=Decimal("1"),
                exchange_rate_date=date(2026, 1, 2),
                transaction_date=datetime(2026, 1, 2, tzinfo=UTC),
                source="system",
                status="confirmed",
                transfer_id=transfer.id,
            )
        )
        session.add(
            AccountBalance(
                account_id=account_id,
                currency="CNY",
                balance=Decimal("60"),
                snapshot_at=datetime(2026, 1, 3, tzinfo=UTC),
                source="manual",
            )
        )
        await session.commit()

    response = await db_client.get(
        f"/api/v1/accounts/{account['id']}/balances", headers=household_headers
    )
    assert response.status_code == 200
    lines = {line["currency"]: line for line in response.json()["data"]["balances"]}
    assert Decimal(lines["CNY"]["book_balance"]) == Decimal("58")
    assert Decimal(lines["CNY"]["latest_snapshot"]["balance"]) == Decimal("60")
    assert Decimal(lines["CNY"]["difference"]) == Decimal("2")
    assert Decimal(lines["USD"]["book_balance"]) == Decimal("5")
    assert lines["USD"]["latest_snapshot"] is None


async def test_delete_account_blocked_by_transfer(
    db_client: AsyncClient, db_app, household: dict, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    other = await _create_account(db_client, household_headers, name="另一个")
    async with db_app.state.db_session_factory() as session:
        session.add(
            Transfer(
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
        )
        await session.commit()

    response = await db_client.delete(
        f"/api/v1/accounts/{account['id']}", headers=household_headers
    )
    assert response.status_code == 409


async def test_account_transactions_and_balance_history(
    db_client: AsyncClient, db_app, household: dict, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    await db_client.put(
        f"/api/v1/accounts/{account['id']}/opening-balance",
        headers=household_headers,
        json={"amount": "12.30"},
    )
    async with db_app.state.db_session_factory() as session:
        session.add(
            AccountBalance(
                account_id=UUID(account["id"]),
                currency="CNY",
                balance=Decimal("12.30"),
                snapshot_at=datetime(2026, 2, 1, tzinfo=UTC),
                source="bank",
            )
        )
        await session.commit()

    transactions = await db_client.get(
        f"/api/v1/accounts/{account['id']}/transactions?transaction_type=opening_balance",
        headers=household_headers,
    )
    assert transactions.status_code == 200
    assert transactions.json()["data"]["total"] == 1

    filtered_out = await db_client.get(
        f"/api/v1/accounts/{account['id']}/transactions?transaction_type=income",
        headers=household_headers,
    )
    assert filtered_out.json()["data"]["total"] == 0

    history = await db_client.get(
        f"/api/v1/accounts/{account['id']}/balance-history?currency=CNY",
        headers=household_headers,
    )
    assert history.status_code == 200
    assert history.json()["data"]["total"] == 1

    future = await db_client.get(
        f"/api/v1/accounts/{account['id']}/balance-history?start_date=2030-01-01",
        headers=household_headers,
    )
    assert future.json()["data"]["total"] == 0


async def test_account_list_sort_validation(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    bad = await db_client.get("/api/v1/accounts?sort_by=password", headers=household_headers)
    assert bad.status_code == 400
