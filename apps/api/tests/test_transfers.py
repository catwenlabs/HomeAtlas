"""Transfer lifecycle: multi-currency moves, fees, reversal, and statistics (Phase 2E)."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select

from app.modules.audit.models import AuditLog


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


async def _create_transfer(client: AsyncClient, headers: dict[str, str], **payload: object) -> dict:
    response = await client.post("/api/v1/transfers", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _confirm_transfer(
    client: AsyncClient, headers: dict[str, str], transfer_id: str, **payload: object
) -> dict:
    response = await client.put(
        f"/api/v1/transfers/{transfer_id}",
        headers=headers,
        json={"status": "confirmed", **payload},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _balances(
    client: AsyncClient, headers: dict[str, str], account_id: str
) -> dict[str, Decimal]:
    response = await client.get(f"/api/v1/accounts/{account_id}/balances", headers=headers)
    assert response.status_code == 200, response.text
    return {
        item["currency"]: Decimal(item["book_balance"])
        for item in response.json()["data"]["balances"]
    }


async def _transactions(
    client: AsyncClient, headers: dict[str, str], account_id: str
) -> list[dict]:
    response = await client.get(
        f"/api/v1/transactions?account_id={account_id}&page_size=100",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["items"]


async def _statistics(
    client: AsyncClient, headers: dict[str, str], path: str, query: str = ""
) -> dict:
    response = await client.get(f"/api/v1/statistics/{path}?{query}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_same_currency_transfer_defers_fee_until_confirmation(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    source = await _create_account(db_client, household_headers, name="转出")
    target = await _create_account(db_client, household_headers, name="转入")
    await _set_opening(db_client, household_headers, source["id"], "1000")
    fee_category = await _find_category(db_client, household_headers, "金融手续费")

    transfer = await _create_transfer(
        db_client,
        household_headers,
        from_account_id=source["id"],
        to_account_id=target["id"],
        from_amount="300",
        to_amount="300",
        fee="5",
        transfer_date="2026-06-10T10:00:00+08:00",
        description="转到储蓄",
    )
    assert transfer["status"] == "draft"
    assert transfer["from_currency"] == "CNY"
    assert transfer["to_currency"] == "CNY"
    assert Decimal(transfer["exchange_rate"]) == Decimal("1")
    assert Decimal(transfer["base_amount"]) == Decimal("300")
    assert transfer["base_currency"] == "CNY"
    assert transfer["fee_currency"] == "CNY"
    assert transfer["reverses_transfer_id"] is None

    # Draft transfers move no money and create no fee row yet.
    assert (await _balances(db_client, household_headers, source["id"]))["CNY"] == Decimal("1000")
    assert await _balances(db_client, household_headers, target["id"]) == {}
    assert not [
        item
        for item in await _transactions(db_client, household_headers, source["id"])
        if item["transfer_id"] is not None
    ]

    confirmed = await _confirm_transfer(db_client, household_headers, transfer["id"])
    assert confirmed["status"] == "confirmed"
    assert (await _balances(db_client, household_headers, source["id"]))["CNY"] == Decimal("695")
    assert (await _balances(db_client, household_headers, target["id"]))["CNY"] == Decimal("300")

    fee_rows = [
        item
        for item in await _transactions(db_client, household_headers, source["id"])
        if item["transfer_id"] == transfer["id"]
    ]
    assert len(fee_rows) == 1
    fee_row = fee_rows[0]
    assert fee_row["transaction_type"] == "expense"
    assert fee_row["source"] == "system"
    assert fee_row["status"] == "confirmed"
    assert fee_row["category_id"] == fee_category["id"]
    assert Decimal(fee_row["amount"]) == Decimal("5")
    assert Decimal(fee_row["base_amount"]) == Decimal("5")

    summary = await _statistics(
        db_client,
        household_headers,
        "income-expense",
        "start_date=2026-06-01&end_date=2026-06-30",
    )
    assert Decimal(summary["income"]) == Decimal("0")
    assert Decimal(summary["expense"]) == Decimal("5")
    assert Decimal(summary["net"]) == Decimal("-5")

    categories = await _statistics(
        db_client,
        household_headers,
        "category",
        "start_date=2026-06-01&end_date=2026-06-30",
    )
    fee_item = next(item for item in categories["items"] if item["category_name"] == "金融手续费")
    assert fee_item["category_type"] == "expense"
    assert Decimal(fee_item["amount"]) == Decimal("5")

    balances = await _statistics(db_client, household_headers, "account-balances")
    by_account = {
        item["account_id"]: {
            line["currency"]: Decimal(line["book_balance"]) for line in item["balances"]
        }
        for item in balances["accounts"]
    }
    assert by_account[source["id"]] == {"CNY": Decimal("695")}
    assert by_account[target["id"]] == {"CNY": Decimal("300")}


async def test_cross_currency_transfer_keeps_recorded_rate(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    cny = await _create_account(db_client, household_headers, name="人民币")
    usd = await _create_account(db_client, household_headers, name="美元", currency="USD")
    await _set_opening(db_client, household_headers, cny["id"], "10000")

    transfer = await _create_transfer(
        db_client,
        household_headers,
        from_account_id=cny["id"],
        to_account_id=usd["id"],
        from_amount="1000",
        from_currency="CNY",
        to_amount="140",
        to_currency="USD",
        exchange_rate="7.14",
        fee="10",
        transfer_date="2026-06-11T10:00:00+08:00",
        status="confirmed",
    )
    assert Decimal(transfer["exchange_rate"]) == Decimal("7.14")
    assert Decimal(transfer["base_amount"]) == Decimal("1000")
    assert transfer["base_currency"] == "CNY"
    assert transfer["fee_currency"] == "CNY"

    assert (await _balances(db_client, household_headers, cny["id"]))["CNY"] == Decimal("8990")
    assert (await _balances(db_client, household_headers, usd["id"]))["USD"] == Decimal("140")
    fee_row = next(
        item
        for item in await _transactions(db_client, household_headers, cny["id"])
        if item["transfer_id"] == transfer["id"]
    )
    assert Decimal(fee_row["amount"]) == Decimal("10")
    assert Decimal(fee_row["base_amount"]) == Decimal("10")

    summary = await _statistics(
        db_client,
        household_headers,
        "income-expense",
        "start_date=2026-06-01&end_date=2026-06-30",
    )
    assert Decimal(summary["expense"]) == Decimal("10")
    overview = await _statistics(
        db_client,
        household_headers,
        "overview",
        "start_date=2026-06-01&end_date=2026-06-30",
    )
    assert {item["currency"]: Decimal(item["book_balance"]) for item in overview["assets"]} == {
        "CNY": Decimal("8990"),
        "USD": Decimal("140"),
    }


async def test_same_account_currency_conversion(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers, name="多币种")
    await _set_opening(db_client, household_headers, account["id"], "7000")
    await _set_opening(
        db_client,
        household_headers,
        account["id"],
        "100",
        currency="USD",
        exchange_rate="7.10",
    )

    transfer = await _create_transfer(
        db_client,
        household_headers,
        from_account_id=account["id"],
        to_account_id=account["id"],
        from_amount="700",
        from_currency="CNY",
        to_amount="100",
        to_currency="USD",
        transfer_date="2026-06-12T10:00:00+08:00",
        status="confirmed",
    )
    assert transfer["status"] == "confirmed"
    assert Decimal(transfer["exchange_rate"]).quantize(Decimal("0.000001")) == Decimal("0.142857")

    balances = await _balances(db_client, household_headers, account["id"])
    assert balances == {"CNY": Decimal("6300"), "USD": Decimal("200")}

    summary = await _statistics(
        db_client,
        household_headers,
        "income-expense",
        "start_date=2026-06-01&end_date=2026-06-30",
    )
    assert Decimal(summary["income"]) == Decimal("0")
    assert Decimal(summary["expense"]) == Decimal("0")


async def test_invalid_same_account_same_currency_transfer_is_rejected(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    response = await db_client.post(
        "/api/v1/transfers",
        headers=household_headers,
        json={
            "from_account_id": account["id"],
            "to_account_id": account["id"],
            "from_amount": "10",
            "to_amount": "10",
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["error_code"] == "TRANSFER_SOURCE_SAME"


async def test_confirmation_rejects_negative_balance_for_principal_plus_fee(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    source = await _create_account(db_client, household_headers, name="转出")
    target = await _create_account(db_client, household_headers, name="转入")
    await _set_opening(db_client, household_headers, source["id"], "100")

    transfer = await _create_transfer(
        db_client,
        household_headers,
        from_account_id=source["id"],
        to_account_id=target["id"],
        from_amount="100",
        to_amount="100",
        fee="5",
    )
    response = await db_client.put(
        f"/api/v1/transfers/{transfer['id']}",
        headers=household_headers,
        json={"status": "confirmed"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error_code"] == "INSUFFICIENT_BALANCE"

    current = await db_client.get(f"/api/v1/transfers/{transfer['id']}", headers=household_headers)
    assert current.json()["data"]["status"] == "draft"
    assert (await _balances(db_client, household_headers, source["id"]))["CNY"] == Decimal("100")
    assert not [
        item
        for item in await _transactions(db_client, household_headers, source["id"])
        if item["transfer_id"] is not None
    ]

    updated = await db_client.put(
        f"/api/v1/transfers/{transfer['id']}",
        headers=household_headers,
        json={"fee": "0"},
    )
    assert updated.status_code == 200, updated.text
    confirmed = await _confirm_transfer(db_client, household_headers, transfer["id"])
    assert confirmed["status"] == "confirmed"
    assert (await _balances(db_client, household_headers, source["id"]))["CNY"] == Decimal("0")


async def test_fee_currency_must_be_available_on_source_account(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    cny = await _create_account(db_client, household_headers, name="人民币")
    usd = await _create_account(db_client, household_headers, name="美元", currency="USD")
    await _set_opening(db_client, household_headers, cny["id"], "1000")

    transfer = await _create_transfer(
        db_client,
        household_headers,
        from_account_id=cny["id"],
        to_account_id=usd["id"],
        from_amount="100",
        to_amount="14",
        fee="1",
        fee_currency="USD",
    )
    rejected = await db_client.put(
        f"/api/v1/transfers/{transfer['id']}",
        headers=household_headers,
        json={"status": "confirmed"},
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["error_code"] == "INSUFFICIENT_BALANCE"

    updated = await db_client.put(
        f"/api/v1/transfers/{transfer['id']}",
        headers=household_headers,
        json={"fee_currency": "CNY"},
    )
    assert updated.status_code == 200, updated.text
    confirmed = await _confirm_transfer(db_client, household_headers, transfer["id"])
    assert confirmed["status"] == "confirmed"
    assert confirmed["fee_currency"] == "CNY"
    assert (await _balances(db_client, household_headers, cny["id"]))["CNY"] == Decimal("899")
    assert (await _balances(db_client, household_headers, usd["id"]))["USD"] == Decimal("14")


async def test_reversal_undoes_principal_and_fee(
    db_client: AsyncClient,
    db_app,
    household,
    household_headers: dict[str, str],
):
    source = await _create_account(db_client, household_headers, name="转出")
    target = await _create_account(db_client, household_headers, name="转入")
    await _set_opening(db_client, household_headers, source["id"], "1000")
    transfer = await _create_transfer(
        db_client,
        household_headers,
        from_account_id=source["id"],
        to_account_id=target["id"],
        from_amount="300",
        to_amount="300",
        fee="5",
        transfer_date="2026-06-10T10:00:00+08:00",
    )
    transfer = await _confirm_transfer(db_client, household_headers, transfer["id"])
    assert transfer["status"] == "confirmed"
    assert (await _balances(db_client, household_headers, source["id"]))["CNY"] == Decimal("695")

    response = await db_client.post(
        f"/api/v1/transfers/{transfer['id']}/reverse",
        headers=household_headers,
        json={"transfer_date": "2026-06-15T10:00:00+08:00"},
    )
    assert response.status_code == 201, response.text
    reversal = response.json()["data"]
    assert reversal["status"] == "confirmed"
    assert reversal["reverses_transfer_id"] == transfer["id"]
    assert reversal["from_account_id"] == target["id"]
    assert reversal["to_account_id"] == source["id"]
    assert Decimal(reversal["from_amount"]) == Decimal("300")
    assert Decimal(reversal["to_amount"]) == Decimal("300")
    assert Decimal(reversal["fee"]) == Decimal("0")

    original = await db_client.get(f"/api/v1/transfers/{transfer['id']}", headers=household_headers)
    assert original.json()["data"]["status"] == "reversed"
    assert (await _balances(db_client, household_headers, source["id"]))["CNY"] == Decimal("1000")
    assert (await _balances(db_client, household_headers, target["id"])).get(
        "CNY", Decimal("0")
    ) == Decimal("0")

    source_rows = await _transactions(db_client, household_headers, source["id"])
    original_fee = next(item for item in source_rows if item["transfer_id"] == transfer["id"])
    fee_reversal = next(item for item in source_rows if item["transfer_id"] == reversal["id"])
    assert original_fee["status"] == "reversed"
    assert original_fee["transaction_type"] == "expense"
    assert fee_reversal["status"] == "confirmed"
    assert fee_reversal["transaction_type"] == "income"
    assert fee_reversal["source"] == "system"
    assert fee_reversal["reverses_transaction_id"] == original_fee["id"]
    assert Decimal(fee_reversal["base_amount"]) == Decimal("5")

    summary = await _statistics(
        db_client,
        household_headers,
        "income-expense",
        "start_date=2026-06-01&end_date=2026-06-30",
    )
    assert Decimal(summary["income"]) == Decimal("0")
    assert Decimal(summary["expense"]) == Decimal("0")

    again = await db_client.post(
        f"/api/v1/transfers/{transfer['id']}/reverse", headers=household_headers
    )
    assert again.status_code == 409
    assert again.json()["error_code"] == "TRANSFER_NOT_REVERSIBLE"

    reverse_reversal = await db_client.post(
        f"/api/v1/transfers/{reversal['id']}/reverse", headers=household_headers
    )
    assert reverse_reversal.status_code == 409
    assert reverse_reversal.json()["error_code"] == "TRANSFER_NOT_REVERSIBLE"

    async with db_app.state.db_session_factory() as session:
        actions = set(
            (
                await session.scalars(
                    select(AuditLog.action).where(
                        AuditLog.entity_type == "transfer",
                        AuditLog.entity_id == UUID(transfer["id"]),
                    )
                )
            ).all()
        )
    assert actions == {"transfer.create", "transfer.confirm", "transfer.reverse"}


async def test_reversal_rejects_destination_without_funds(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    source = await _create_account(db_client, household_headers, name="转出")
    target = await _create_account(db_client, household_headers, name="转入")
    await _set_opening(db_client, household_headers, source["id"], "1000")
    transfer = await _create_transfer(
        db_client,
        household_headers,
        from_account_id=source["id"],
        to_account_id=target["id"],
        from_amount="500",
        to_amount="500",
        status="confirmed",
    )
    dining = await _find_category(db_client, household_headers, "餐饮")
    spent = await db_client.post(
        "/api/v1/transactions",
        headers=household_headers,
        json={
            "account_id": target["id"],
            "category_id": dining["id"],
            "transaction_type": "expense",
            "amount": "400",
            "status": "confirmed",
        },
    )
    assert spent.status_code == 201, spent.text

    response = await db_client.post(
        f"/api/v1/transfers/{transfer['id']}/reverse", headers=household_headers
    )
    assert response.status_code == 409, response.text
    assert response.json()["error_code"] == "INSUFFICIENT_BALANCE"

    current = await db_client.get(f"/api/v1/transfers/{transfer['id']}", headers=household_headers)
    assert current.json()["data"]["status"] == "confirmed"
    listing = await db_client.get(
        f"/api/v1/transfers?account_id={target['id']}", headers=household_headers
    )
    assert listing.json()["data"]["total"] == 1


async def test_transfer_state_machine_and_draft_updates(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    source = await _create_account(db_client, household_headers, name="转出")
    target = await _create_account(db_client, household_headers, name="转入")
    await _set_opening(db_client, household_headers, source["id"], "1000")

    draft = await _create_transfer(
        db_client,
        household_headers,
        from_account_id=source["id"],
        to_account_id=target["id"],
        from_amount="100",
        to_amount="100",
        description="原始",
    )
    updated = await db_client.put(
        f"/api/v1/transfers/{draft['id']}",
        headers=household_headers,
        json={
            "from_amount": "200",
            "to_amount": "200",
            "fee": "2",
            "description": "修改后",
        },
    )
    assert updated.status_code == 200, updated.text
    updated_data = updated.json()["data"]
    assert Decimal(updated_data["from_amount"]) == Decimal("200")
    assert Decimal(updated_data["fee"]) == Decimal("2")
    assert updated_data["description"] == "修改后"

    deleted = await db_client.delete(f"/api/v1/transfers/{draft['id']}", headers=household_headers)
    assert deleted.status_code == 200, deleted.text
    missing = await db_client.get(f"/api/v1/transfers/{draft['id']}", headers=household_headers)
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "TRANSFER_NOT_FOUND"

    confirmed = await _create_transfer(
        db_client,
        household_headers,
        from_account_id=source["id"],
        to_account_id=target["id"],
        from_amount="100",
        to_amount="100",
        status="confirmed",
    )
    edit = await db_client.put(
        f"/api/v1/transfers/{confirmed['id']}",
        headers=household_headers,
        json={"description": "不允许"},
    )
    assert edit.status_code == 409
    assert edit.json()["error_code"] == "TRANSFER_NOT_EDITABLE"
    remove = await db_client.delete(
        f"/api/v1/transfers/{confirmed['id']}", headers=household_headers
    )
    assert remove.status_code == 409
    assert remove.json()["error_code"] == "TRANSFER_NOT_DELETABLE"
    invalid_status = await db_client.put(
        f"/api/v1/transfers/{confirmed['id']}",
        headers=household_headers,
        json={"status": "reversed"},
    )
    assert invalid_status.status_code == 422
    assert invalid_status.json()["error_code"] == "VALIDATION_ERROR"


async def test_cross_household_transfer_access_is_isolated(
    db_client: AsyncClient,
    household_headers: dict[str, str],
    auth_for_household: Any,
    create_household: Any,
):
    source = await _create_account(db_client, household_headers, name="本家账户")
    await _set_opening(db_client, household_headers, source["id"], "1000")
    transfer = await _create_transfer(
        db_client,
        household_headers,
        from_account_id=source["id"],
        to_account_id=source["id"],
        from_amount="100",
        from_currency="CNY",
        to_amount="14",
        to_currency="USD",
        status="draft",
    )

    second_id = await create_household()
    second_headers = await auth_for_household(second_id)
    other = await _create_account(db_client, second_headers, name="别人账户")

    mixed = await db_client.post(
        "/api/v1/transfers",
        headers=household_headers,
        json={
            "from_account_id": source["id"],
            "to_account_id": other["id"],
            "from_amount": "10",
            "to_amount": "10",
        },
    )
    assert mixed.status_code == 404, mixed.text
    assert mixed.json()["error_code"] == "ACCOUNT_NOT_FOUND"

    hidden = await db_client.get(f"/api/v1/transfers/{transfer['id']}", headers=second_headers)
    assert hidden.status_code == 404
    assert hidden.json()["error_code"] == "TRANSFER_NOT_FOUND"
    listing = await db_client.get("/api/v1/transfers", headers=second_headers)
    assert listing.json()["data"]["total"] == 0


async def test_base_exchange_rate_required_when_neither_currency_is_base(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    usd = await _create_account(db_client, household_headers, name="美元", currency="USD")
    eur = await _create_account(db_client, household_headers, name="欧元", currency="EUR")
    await _set_opening(db_client, household_headers, usd["id"], "100", exchange_rate="7.0")

    missing = await db_client.post(
        "/api/v1/transfers",
        headers=household_headers,
        json={
            "from_account_id": usd["id"],
            "to_account_id": eur["id"],
            "from_amount": "10",
            "to_amount": "9",
        },
    )
    assert missing.status_code == 400, missing.text
    assert missing.json()["error_code"] == "BASE_EXCHANGE_RATE_REQUIRED"

    transfer = await _create_transfer(
        db_client,
        household_headers,
        from_account_id=usd["id"],
        to_account_id=eur["id"],
        from_amount="10",
        to_amount="9",
        base_exchange_rate="7.0",
        status="confirmed",
    )
    assert Decimal(transfer["exchange_rate"]) == Decimal("0.9")
    assert Decimal(transfer["base_amount"]) == Decimal("70")
    assert transfer["base_currency"] == "CNY"
    assert (await _balances(db_client, household_headers, usd["id"]))["USD"] == Decimal("90")
    assert (await _balances(db_client, household_headers, eur["id"]))["EUR"] == Decimal("9")


async def test_base_exchange_rate_is_preserved_on_draft_updates(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    usd = await _create_account(db_client, household_headers, name="美元", currency="USD")
    eur = await _create_account(db_client, household_headers, name="欧元", currency="EUR")
    await _set_opening(db_client, household_headers, usd["id"], "100", exchange_rate="7.0")
    draft = await _create_transfer(
        db_client,
        household_headers,
        from_account_id=usd["id"],
        to_account_id=eur["id"],
        from_amount="10",
        to_amount="9",
        base_exchange_rate="7.0",
        description="初始",
    )
    assert Decimal(draft["base_amount"]) == Decimal("70")

    renamed = await db_client.put(
        f"/api/v1/transfers/{draft['id']}",
        headers=household_headers,
        json={"description": "改名"},
    )
    assert renamed.status_code == 200, renamed.text
    assert Decimal(renamed.json()["data"]["base_amount"]) == Decimal("70")

    resized = await db_client.put(
        f"/api/v1/transfers/{draft['id']}",
        headers=household_headers,
        json={"from_amount": "20"},
    )
    assert resized.status_code == 200, resized.text
    assert Decimal(resized.json()["data"]["base_amount"]) == Decimal("140")


async def test_fee_exchange_rate_required_for_third_currency_fee(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    usd = await _create_account(db_client, household_headers, name="美元", currency="USD")
    eur = await _create_account(db_client, household_headers, name="欧元", currency="EUR")
    await _set_opening(db_client, household_headers, usd["id"], "100", exchange_rate="7.0")
    await _set_opening(
        db_client,
        household_headers,
        usd["id"],
        "10",
        currency="JPY",
        exchange_rate="0.048",
    )

    missing = await db_client.post(
        "/api/v1/transfers",
        headers=household_headers,
        json={
            "from_account_id": usd["id"],
            "to_account_id": eur["id"],
            "from_amount": "10",
            "to_amount": "9",
            "base_exchange_rate": "7.0",
            "fee": "1",
            "fee_currency": "JPY",
        },
    )
    assert missing.status_code == 400, missing.text
    assert missing.json()["error_code"] == "FEE_EXCHANGE_RATE_REQUIRED"

    transfer = await _create_transfer(
        db_client,
        household_headers,
        from_account_id=usd["id"],
        to_account_id=eur["id"],
        from_amount="10",
        to_amount="9",
        base_exchange_rate="7.0",
        fee="1",
        fee_currency="JPY",
        fee_exchange_rate="0.048",
        status="confirmed",
    )
    assert transfer["fee_currency"] == "JPY"
    balances = await _balances(db_client, household_headers, usd["id"])
    assert balances["USD"] == Decimal("90")
    assert balances["JPY"] == Decimal("9")

    fee_row = next(
        item
        for item in await _transactions(db_client, household_headers, usd["id"])
        if item["transfer_id"] == transfer["id"]
    )
    assert Decimal(fee_row["amount"]) == Decimal("1")
    assert Decimal(fee_row["base_amount"]) == Decimal("0.048")


async def test_transfer_list_filters_and_pagination(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    source = await _create_account(db_client, household_headers, name="转出")
    target = await _create_account(db_client, household_headers, name="转入")
    await _set_opening(db_client, household_headers, source["id"], "1000")
    first = await _create_transfer(
        db_client,
        household_headers,
        from_account_id=source["id"],
        to_account_id=target["id"],
        from_amount="100",
        to_amount="100",
        transfer_date="2026-06-01T10:00:00+08:00",
    )
    second = await _create_transfer(
        db_client,
        household_headers,
        from_account_id=source["id"],
        to_account_id=target["id"],
        from_amount="50",
        to_amount="50",
        transfer_date="2026-06-02T10:00:00+08:00",
        status="confirmed",
    )
    third = await _create_transfer(
        db_client,
        household_headers,
        from_account_id=source["id"],
        to_account_id=target["id"],
        from_amount="70",
        to_amount="70",
        transfer_date="2026-07-01T10:00:00+08:00",
    )

    june = await db_client.get(
        "/api/v1/transfers?start_date=2026-06-01&end_date=2026-06-30",
        headers=household_headers,
    )
    assert june.json()["data"]["total"] == 2
    drafts = await db_client.get("/api/v1/transfers?status=draft", headers=household_headers)
    assert {item["id"] for item in drafts.json()["data"]["items"]} == {
        first["id"],
        third["id"],
    }
    confirmed = await db_client.get("/api/v1/transfers?status=confirmed", headers=household_headers)
    assert [item["id"] for item in confirmed.json()["data"]["items"]] == [second["id"]]
    newest = await db_client.get(
        "/api/v1/transfers?sort_by=transfer_date&sort_order=desc",
        headers=household_headers,
    )
    assert newest.json()["data"]["items"][0]["id"] == third["id"]
    page = await db_client.get("/api/v1/transfers?page=2&page_size=2", headers=household_headers)
    assert page.json()["data"]["total"] == 3
    assert len(page.json()["data"]["items"]) == 1
    by_source = await db_client.get(
        f"/api/v1/transfers?from_account_id={source['id']}",
        headers=household_headers,
    )
    assert by_source.json()["data"]["total"] == 3
    by_target = await db_client.get(
        f"/api/v1/transfers?to_account_id={target['id']}",
        headers=household_headers,
    )
    assert by_target.json()["data"]["total"] == 3
    bad_sort = await db_client.get("/api/v1/transfers?sort_by=unknown", headers=household_headers)
    assert bad_sort.status_code == 400
    assert bad_sort.json()["error_code"] == "INVALID_SORT_FIELD"


async def test_transfer_validation_rejects_bad_amounts(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    source = await _create_account(db_client, household_headers)
    response = await db_client.post(
        "/api/v1/transfers",
        headers=household_headers,
        json={
            "from_account_id": source["id"],
            "to_account_id": source["id"],
            "from_amount": "0",
            "to_amount": "10",
            "fee": "-1",
        },
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"


async def test_openapi_documents_transfer_paths(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    payload = (await db_client.get("/openapi.json")).json()
    expected = {
        "/api/v1/transfers",
        "/api/v1/transfers/{transfer_id}",
        "/api/v1/transfers/{transfer_id}/reverse",
    }
    assert expected <= set(payload["paths"])


async def test_credit_source_overdraft_allowed(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    credit = await _create_account(
        db_client, household_headers, name="信用卡", account_type="credit"
    )
    target = await _create_account(db_client, household_headers, name="储蓄卡")
    await _set_opening(db_client, household_headers, credit["id"], "-500")

    overdraft = await _create_transfer(
        db_client,
        household_headers,
        from_account_id=credit["id"],
        to_account_id=target["id"],
        from_amount="200",
        to_amount="200",
        status="confirmed",
    )
    assert overdraft["status"] == "confirmed"

    balances = await _balances(db_client, household_headers, credit["id"])
    assert balances["CNY"] == Decimal("-700")


async def test_credit_source_limit_exceeded(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    credit = await _create_account(
        db_client,
        household_headers,
        name="限额信用卡",
        account_type="credit",
        credit_limit=1000,
    )
    target = await _create_account(db_client, household_headers, name="储蓄卡")
    await _set_opening(db_client, household_headers, credit["id"], "-500")

    rejected = await db_client.post(
        "/api/v1/transfers",
        headers=household_headers,
        json={
            "from_account_id": credit["id"],
            "to_account_id": target["id"],
            "from_amount": "600",
            "to_amount": "600",
            "status": "confirmed",
        },
    )
    assert rejected.status_code == 409
    assert rejected.json()["error_code"] == "CREDIT_LIMIT_EXCEEDED"

    draft = await _create_transfer(
        db_client,
        household_headers,
        from_account_id=credit["id"],
        to_account_id=target["id"],
        from_amount="600",
        to_amount="600",
    )
    confirm = await db_client.put(
        f"/api/v1/transfers/{draft['id']}",
        headers=household_headers,
        json={"status": "confirmed"},
    )
    assert confirm.status_code == 409
    assert confirm.json()["error_code"] == "CREDIT_LIMIT_EXCEEDED"


async def test_reverse_into_credit_negative_allowed(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    credit = await _create_account(
        db_client, household_headers, name="信用卡", account_type="credit"
    )
    source = await _create_account(db_client, household_headers, name="储蓄卡")
    await _set_opening(db_client, household_headers, source["id"], "300")

    transfer = await _create_transfer(
        db_client,
        household_headers,
        from_account_id=source["id"],
        to_account_id=credit["id"],
        from_amount="300",
        to_amount="300",
        status="confirmed",
    )
    reversed_response = await db_client.post(
        f"/api/v1/transfers/{transfer['id']}/reverse", headers=household_headers
    )
    assert reversed_response.status_code == 201, reversed_response.text
    balances = await _balances(db_client, household_headers, credit["id"])
    assert balances["CNY"] == Decimal("0")
