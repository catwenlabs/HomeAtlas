"""Investments: registration, fund/redeem loop, reversal linkage, holdings,
quotes, and tags (phase 2C-2)."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.modules.audit.models import AuditLog

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


async def _create_account(
    client: AsyncClient, headers: dict[str, str], **overrides: object
) -> dict:
    payload: dict[str, object] = {"name": "现金", "account_type": "cash", "currency": "CNY"}
    payload.update(overrides)
    response = await client.post("/api/v1/accounts", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _set_opening(
    client: AsyncClient, headers: dict[str, str], account_id: str, amount: str, **extra: object
) -> None:
    response = await client.put(
        f"/api/v1/accounts/{account_id}/opening-balance",
        headers=headers,
        json={"amount": amount, **extra},
    )
    assert response.status_code == 200, response.text


async def _investment(client: AsyncClient, headers: dict[str, str], **payload: object) -> dict:
    body: dict[str, object] = {
        "name": "测试投资",
        "investment_type": "fixed",
        "currency": "CNY",
        "start_date": TODAY.isoformat(),
    }
    body.update(payload)
    response = await client.post("/api/v1/investments", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _book_balance(client: AsyncClient, headers: dict[str, str], account_id: str) -> Decimal:
    response = await client.get(f"/api/v1/accounts/{account_id}/balances", headers=headers)
    assert response.status_code == 200, response.text
    return Decimal(response.json()["data"]["balances"][0]["book_balance"])


async def _income_expense_total(client: AsyncClient, headers: dict[str, str]) -> dict:
    response = await client.get("/api/v1/statistics/income-expense", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _transfers(client: AsyncClient, headers: dict[str, str]) -> list[dict]:
    response = await client.get("/api/v1/transfers?page_size=50", headers=headers)
    assert response.status_code == 200
    return response.json()["data"]["items"]


async def test_unmanaged_registration_and_defaults(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    created = await _investment(
        db_client,
        household_headers,
        name="茅台持仓",
        investment_type="stock",
        principal="170000",
        annual_rate="0.0",
        liquidity="T0",
    )
    assert created["account_id"] is None
    assert created["principal"] == "170000.00000000"
    assert created["current_value"] == "170000.00000000"
    assert created["status"] == "active"
    assert created["matured"] is False
    assert created["tag_ids"] == []

    # Metadata edits work; principal is editable on unmanaged rows.
    renamed = await db_client.put(
        f"/api/v1/investments/{created['id']}",
        headers=household_headers,
        json={"name": "改名投资", "principal": "180000"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["data"]["principal"] == "180000.00000000"


async def test_managed_funding_flow(db_client: AsyncClient, household_headers: dict[str, str]):
    cash = await _create_account(db_client, household_headers, name="储蓄")
    await _set_opening(db_client, household_headers, cash["id"], "10000")
    brokerage = await _create_account(
        db_client, household_headers, name="券商", account_type="investment"
    )

    created = await _investment(
        db_client,
        household_headers,
        investment_type="fund",
        account_id=brokerage["id"],
        fund_transfer={"from_account_id": cash["id"], "from_amount": "6000"},
    )
    assert created["principal"] == "6000.00000000"
    assert created["current_value"] == "6000.00000000"

    transfers = await _transfers(db_client, household_headers)
    assert len(transfers) == 1
    assert transfers[0]["status"] == "confirmed"
    assert transfers[0]["to_amount"] == "6000.00000000"

    assert await _book_balance(db_client, household_headers, cash["id"]) == Decimal("4000")
    assert await _book_balance(db_client, household_headers, brokerage["id"]) == Decimal("6000")

    # Additional funding accumulates the principal.
    funded = await db_client.post(
        f"/api/v1/investments/{created['id']}/fund",
        headers=household_headers,
        json={"fund_transfer": {"from_account_id": cash["id"], "from_amount": "1000"}},
    )
    assert funded.status_code == 200, funded.text
    assert funded.json()["data"]["principal"] == "7000.00000000"


async def test_funding_guard_rolls_back_creation(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    empty = await _create_account(db_client, household_headers, name="空账户")
    brokerage = await _create_account(
        db_client, household_headers, name="券商", account_type="investment"
    )

    rejected = await db_client.post(
        "/api/v1/investments",
        headers=household_headers,
        json={
            "name": "失败的建仓",
            "investment_type": "fund",
            "currency": "CNY",
            "start_date": TODAY.isoformat(),
            "account_id": brokerage["id"],
            "fund_transfer": {"from_account_id": empty["id"], "from_amount": "500"},
        },
    )
    assert rejected.status_code == 409
    assert rejected.json()["error_code"] == "INSUFFICIENT_BALANCE"

    listing = await db_client.get("/api/v1/investments", headers=household_headers)
    assert listing.json()["data"]["total"] == 0
    assert len(await _transfers(db_client, household_headers)) == 0


async def test_managed_put_narrowing_and_value_endpoint(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    brokerage = await _create_account(
        db_client, household_headers, name="券商", account_type="investment"
    )
    created = await _investment(
        db_client, household_headers, account_id=brokerage["id"], principal="1000"
    )

    locked = await db_client.put(
        f"/api/v1/investments/{created['id']}",
        headers=household_headers,
        json={"principal": "2000"},
    )
    assert locked.status_code == 409
    assert locked.json()["error_code"] == "INVESTMENT_NOT_EDITABLE"

    valued = await db_client.put(
        f"/api/v1/investments/{created['id']}/value",
        headers=household_headers,
        json={"current_value": "1150"},
    )
    assert valued.status_code == 200, valued.text
    assert valued.json()["data"]["current_value"] == "1150.00000000"


async def test_investment_account_validation(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    bank = await _create_account(db_client, household_headers, name="储蓄")
    rejected = await db_client.post(
        "/api/v1/investments",
        headers=household_headers,
        json={
            "name": "坏账户",
            "investment_type": "fund",
            "currency": "CNY",
            "start_date": TODAY.isoformat(),
            "account_id": bank["id"],
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["error_code"] == "INVESTMENT_ACCOUNT_INVALID"

    dollar_brokerage = await _create_account(
        db_client,
        household_headers,
        name="美元券商",
        account_type="investment",
        currency="USD",
    )
    mismatched = await db_client.post(
        "/api/v1/investments",
        headers=household_headers,
        json={
            "name": "币种不符",
            "investment_type": "fund",
            "currency": "CNY",
            "start_date": TODAY.isoformat(),
            "account_id": dollar_brokerage["id"],
        },
    )
    assert mismatched.status_code == 422
    assert mismatched.json()["error_code"] == "INVESTMENT_ACCOUNT_INVALID"


async def test_delete_rules_and_fund_reversal_linkage(
    db_client: AsyncClient, household_headers: dict[str, str], db_app: Any
):
    cash = await _create_account(db_client, household_headers, name="储蓄")
    await _set_opening(db_client, household_headers, cash["id"], "10000")
    brokerage = await _create_account(
        db_client, household_headers, name="券商", account_type="investment"
    )
    created = await _investment(
        db_client,
        household_headers,
        account_id=brokerage["id"],
        fund_transfer={"from_account_id": cash["id"], "from_amount": "5000"},
    )
    await db_client.post(
        f"/api/v1/investments/{created['id']}/fund",
        headers=household_headers,
        json={"fund_transfer": {"from_account_id": cash["id"], "from_amount": "3000"}},
    )
    assert await _book_balance(db_client, household_headers, brokerage["id"]) == Decimal("8000")

    blocked = await db_client.delete(
        f"/api/v1/investments/{created['id']}", headers=household_headers
    )
    assert blocked.status_code == 409
    assert blocked.json()["error_code"] == "INVESTMENT_HAS_TRANSFERS"

    # Reverse the second (3000) funding: principal and balance drop together.
    second = next(
        t
        for t in await _transfers(db_client, household_headers)
        if t["to_amount"] == "3000.00000000"
    )
    reversed_response = await db_client.post(
        f"/api/v1/transfers/{second['id']}/reverse", headers=household_headers
    )
    assert reversed_response.status_code == 201, reversed_response.text

    detail = await db_client.get(f"/api/v1/investments/{created['id']}", headers=household_headers)
    assert detail.json()["data"]["principal"] == "5000.00000000"
    assert await _book_balance(db_client, household_headers, brokerage["id"]) == Decimal("5000")

    async with db_app.state.db_session_factory() as session:
        actions = (
            await session.scalars(
                select(AuditLog.action).where(
                    AuditLog.entity_type == "investment",
                    AuditLog.entity_id == created["id"],
                )
            )
        ).all()
    assert "investment.fund_reverse" in actions

    # The remaining 5000 funding must also be reversed before deletion.
    first = next(
        t
        for t in await _transfers(db_client, household_headers)
        if t["to_amount"] == "5000.00000000"
    )
    first_undo = await db_client.post(
        f"/api/v1/transfers/{first['id']}/reverse", headers=household_headers
    )
    assert first_undo.status_code == 201, first_undo.text

    deleted = await db_client.delete(
        f"/api/v1/investments/{created['id']}", headers=household_headers
    )
    assert deleted.status_code == 200
    listing = await db_client.get("/api/v1/investments", headers=household_headers)
    assert listing.json()["data"]["total"] == 0


async def _funded_investment(
    db_client: AsyncClient, household_headers: dict[str, str], amount: str = "10000"
) -> tuple[dict, dict, dict]:
    cash = await _create_account(db_client, household_headers, name="储蓄")
    await _set_opening(db_client, household_headers, cash["id"], "100000")
    brokerage = await _create_account(
        db_client, household_headers, name="券商", account_type="investment"
    )
    created = await _investment(
        db_client,
        household_headers,
        account_id=brokerage["id"],
        fund_transfer={"from_account_id": cash["id"], "from_amount": amount},
    )
    return created, cash, brokerage


async def test_profit_redeem_books(db_client: AsyncClient, household_headers: dict[str, str]):
    created, cash, brokerage = await _funded_investment(db_client, household_headers)
    valued = await db_client.put(
        f"/api/v1/investments/{created['id']}/value",
        headers=household_headers,
        json={"current_value": "10800"},
    )
    assert valued.status_code == 200

    redeemed = await db_client.post(
        f"/api/v1/investments/{created['id']}/redeem",
        headers=household_headers,
        json={"to_account_id": cash["id"], "to_amount": "11000"},
    )
    assert redeemed.status_code == 200, redeemed.text
    data = redeemed.json()["data"]
    assert data["status"] == "redeemed"
    assert data["realized_pnl"] == "1000.00000000"
    assert data["current_value"] == "0E-8"
    assert data["pre_redeem_value"] == "10800.00000000"

    # Book effects: investment account drained to zero, cash +11000,
    # and the 1000 profit appears exactly once in income statistics.
    assert await _book_balance(db_client, household_headers, brokerage["id"]) == Decimal("0")
    assert await _book_balance(db_client, household_headers, cash["id"]) == Decimal("101000")
    totals = await _income_expense_total(db_client, household_headers)
    assert totals["income"] == "1000.00000000"
    assert Decimal(totals["expense"]) == Decimal("0")


async def test_loss_redeem_books(db_client: AsyncClient, household_headers: dict[str, str]):
    created, cash, brokerage = await _funded_investment(db_client, household_headers)
    redeemed = await db_client.post(
        f"/api/v1/investments/{created['id']}/redeem",
        headers=household_headers,
        json={"to_account_id": cash["id"], "to_amount": "9000"},
    )
    assert redeemed.status_code == 200, redeemed.text
    assert redeemed.json()["data"]["realized_pnl"] == "-1000.00000000"

    totals = await _income_expense_total(db_client, household_headers)
    assert totals["expense"] == "1000.00000000"

    again = await db_client.post(
        f"/api/v1/investments/{created['id']}/redeem",
        headers=household_headers,
        json={"to_account_id": cash["id"], "to_amount": "1"},
    )
    assert again.status_code == 409
    assert again.json()["error_code"] == "INVESTMENT_ALREADY_REDEEMED"


async def test_redeem_validations(db_client: AsyncClient, household_headers: dict[str, str]):
    created, cash, _ = await _funded_investment(db_client, household_headers)
    dollar_account = await _create_account(
        db_client, household_headers, name="美元户", currency="USD"
    )
    mismatched = await db_client.post(
        f"/api/v1/investments/{created['id']}/redeem",
        headers=household_headers,
        json={"to_account_id": dollar_account["id"], "to_amount": "100"},
    )
    assert mismatched.status_code == 422
    assert mismatched.json()["error_code"] == "REDEEM_AMOUNT_INVALID"

    unmanaged = await _investment(db_client, household_headers, name="登记型")
    no_account = await db_client.post(
        f"/api/v1/investments/{unmanaged['id']}/redeem",
        headers=household_headers,
        json={"to_account_id": cash["id"], "to_amount": "10"},
    )
    assert no_account.status_code == 409
    assert no_account.json()["error_code"] == "INVESTMENT_ACCOUNT_REQUIRED"


async def test_full_reversal_chain_restores_state(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    created, cash, brokerage = await _funded_investment(db_client, household_headers)
    await db_client.put(
        f"/api/v1/investments/{created['id']}/value",
        headers=household_headers,
        json={"current_value": "10800"},
    )
    redeemed = await db_client.post(
        f"/api/v1/investments/{created['id']}/redeem",
        headers=household_headers,
        json={"to_account_id": cash["id"], "to_amount": "11000"},
    )
    assert redeemed.status_code == 200

    # Reversing the FUND transfer while redeemed must be refused.
    all_transfers = await _transfers(db_client, household_headers)
    fund = next(t for t in all_transfers if t["description"].startswith("Investment fund"))
    blocked = await db_client.post(
        f"/api/v1/transfers/{fund['id']}/reverse", headers=household_headers
    )
    assert blocked.status_code == 409
    assert blocked.json()["error_code"] == "TRANSFER_LINKED_TO_INVESTMENT"

    # Reverse the redeem: investment and books snap back.
    redeem_id = next(t for t in all_transfers if t["description"].startswith("Investment redeem"))[
        "id"
    ]
    undone = await db_client.post(
        f"/api/v1/transfers/{redeem_id}/reverse", headers=household_headers
    )
    assert undone.status_code == 201, undone.text

    detail = await db_client.get(f"/api/v1/investments/{created['id']}", headers=household_headers)
    data = detail.json()["data"]
    assert data["status"] == "active"
    assert data["realized_pnl"] is None
    assert data["current_value"] == "10800.00000000"

    assert await _book_balance(db_client, household_headers, brokerage["id"]) == Decimal("10000")
    # Cash had 90000 after funding; the redeem reversal takes the 11000
    # proceeds back out.
    assert await _book_balance(db_client, household_headers, cash["id"]) == Decimal("90000")
    totals = await _income_expense_total(db_client, household_headers)
    assert Decimal(totals["income"]) == Decimal("0")

    # Now the fund reversal goes through and empties the investment.
    fund_undo = await db_client.post(
        f"/api/v1/transfers/{fund['id']}/reverse", headers=household_headers
    )
    assert fund_undo.status_code == 201, fund_undo.text
    detail = await db_client.get(f"/api/v1/investments/{created['id']}", headers=household_headers)
    assert detail.json()["data"]["principal"] == "0E-8"
    # The cost basis leaves with the funding; the marked-up residual stays.
    assert detail.json()["data"]["current_value"] == "800.00000000"


async def test_create_rejects_principal_with_fund_transfer(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    """principal + fund_transfer would double-count the cost basis (5.2)."""
    cash = await _create_account(db_client, household_headers, name="储蓄")
    await _set_opening(db_client, household_headers, cash["id"], "100000")
    brokerage = await _create_account(
        db_client, household_headers, name="券商", account_type="investment"
    )
    rejected = await db_client.post(
        "/api/v1/investments",
        headers=household_headers,
        json={
            "name": "双重本金",
            "investment_type": "fixed",
            "start_date": TODAY.isoformat(),
            "account_id": brokerage["id"],
            "principal": "5000",
            "fund_transfer": {"from_account_id": cash["id"], "from_amount": "10000"},
        },
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error_code"] == "INVESTMENT_PRINCIPAL_CONFLICT"
    # No side effects: the funding transfer must not have been created.
    assert await _transfers(db_client, household_headers) == []


async def test_fund_reversal_takes_seeded_value_along(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    created, cash, brokerage = await _funded_investment(db_client, household_headers)
    fund = next(
        t
        for t in await _transfers(db_client, household_headers)
        if t["description"].startswith("Investment fund")
    )
    undone = await db_client.post(
        f"/api/v1/transfers/{fund['id']}/reverse", headers=household_headers
    )
    assert undone.status_code == 201, undone.text
    detail = await db_client.get(f"/api/v1/investments/{created['id']}", headers=household_headers)
    data = detail.json()["data"]
    assert data["principal"] == "0E-8"
    assert data["current_value"] == "0E-8"
    assert await _book_balance(db_client, household_headers, brokerage["id"]) == Decimal("0")
    assert await _book_balance(db_client, household_headers, cash["id"]) == Decimal("100000")


async def test_fund_reversal_keeps_marked_up_residual_value(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    created, _, _ = await _funded_investment(db_client, household_headers)
    await db_client.put(
        f"/api/v1/investments/{created['id']}/value",
        headers=household_headers,
        json={"current_value": "12000"},
    )
    fund = next(
        t
        for t in await _transfers(db_client, household_headers)
        if t["description"].startswith("Investment fund")
    )
    undone = await db_client.post(
        f"/api/v1/transfers/{fund['id']}/reverse", headers=household_headers
    )
    assert undone.status_code == 201, undone.text
    detail = await db_client.get(f"/api/v1/investments/{created['id']}", headers=household_headers)
    data = detail.json()["data"]
    assert data["principal"] == "0E-8"
    # User-asserted markup (12000 - 10000) survives the cost basis leaving.
    assert data["current_value"] == "2000.00000000"


async def test_loss_redeem_guarded_when_cash_drifted_below_principal(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    created, cash, brokerage = await _funded_investment(db_client, household_headers)
    drained = await db_client.post(
        "/api/v1/transfers",
        headers=household_headers,
        json={
            "from_account_id": brokerage["id"],
            "to_account_id": cash["id"],
            "from_amount": "5000",
            "to_amount": "5000",
            "status": "confirmed",
        },
    )
    assert drained.status_code == 201, drained.text

    redeemed = await db_client.post(
        f"/api/v1/investments/{created['id']}/redeem",
        headers=household_headers,
        json={"to_account_id": cash["id"], "to_amount": "4500"},
    )
    assert redeemed.status_code == 409, redeemed.text
    assert redeemed.json()["error_code"] == "INSUFFICIENT_BALANCE"
    # The guard fires on the derived loss row itself: it names the loss
    # 5500 (= principal 10000 - proceeds 4500), not the transfer proceeds.
    assert "5500" in redeemed.json()["message"]
    # Nothing persisted: the drifted balance is untouched.
    assert await _book_balance(db_client, household_headers, brokerage["id"]) == Decimal("5000")


async def test_matured_derived_status(db_client: AsyncClient, household_headers: dict[str, str]):
    matured = await _investment(
        db_client,
        household_headers,
        name="到期理财",
        end_date=YESTERDAY.isoformat(),
    )
    open_ended = await _investment(db_client, household_headers, name="活期")

    detail = await db_client.get(f"/api/v1/investments/{matured['id']}", headers=household_headers)
    assert detail.json()["data"]["matured"] is True

    for status_filter, expected in (("matured", 1), ("active", 1), ("redeemed", 0)):
        listing = await db_client.get(
            f"/api/v1/investments?status={status_filter}", headers=household_headers
        )
        assert listing.json()["data"]["total"] == expected, status_filter

    open_detail = await db_client.get(
        f"/api/v1/investments/{open_ended['id']}", headers=household_headers
    )
    assert open_detail.json()["data"]["matured"] is False


async def test_tags_crud_and_filters(
    db_client: AsyncClient, household_headers: dict[str, str], db_app: Any
):
    created_tag = await db_client.post(
        "/api/v1/investment-tags",
        headers=household_headers,
        json={"name": "稳健", "color": "#22C55E"},
    )
    assert created_tag.status_code == 201, created_tag.text
    tag = created_tag.json()["data"]

    duplicate = await db_client.post(
        "/api/v1/investment-tags", headers=household_headers, json={"name": "稳健"}
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error_code"] == "TAG_DUPLICATE"

    investment = await _investment(
        db_client, household_headers, name="打标投资", tag_ids=[tag["id"]]
    )
    assert investment["tag_ids"] == [tag["id"]]

    filtered = await db_client.get(
        f"/api/v1/investments?tag_id={tag['id']}", headers=household_headers
    )
    assert filtered.json()["data"]["total"] == 1

    in_use = await db_client.delete(
        f"/api/v1/investment-tags/{tag['id']}", headers=household_headers
    )
    assert in_use.status_code == 409
    assert in_use.json()["error_code"] == "TAG_IN_USE"

    untagged = await db_client.put(
        f"/api/v1/investments/{investment['id']}/tags",
        headers=household_headers,
        json={"tag_ids": []},
    )
    assert untagged.status_code == 200
    removed = await db_client.delete(
        f"/api/v1/investment-tags/{tag['id']}", headers=household_headers
    )
    assert removed.status_code == 200


async def test_holdings_crud_and_validations(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    stock = await _investment(db_client, household_headers, name="A股持仓", investment_type="stock")
    created = await db_client.post(
        f"/api/v1/investments/{stock['id']}/holdings",
        headers=household_headers,
        json={"market": "SH", "symbol": "600519", "quantity": 100, "cost_price": "1700"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["cost_subtotal"] == "170000.00000000"

    second = await db_client.post(
        f"/api/v1/investments/{stock['id']}/holdings",
        headers=household_headers,
        json={"market": "SZ", "symbol": "000001", "quantity": 200, "cost_price": "10"},
    )
    assert second.status_code == 201

    listing = await db_client.get(
        f"/api/v1/investments/{stock['id']}/holdings", headers=household_headers
    )
    assert listing.json()["data"]["holdings_cost"] == "172000.00000000"

    duplicate = await db_client.post(
        f"/api/v1/investments/{stock['id']}/holdings",
        headers=household_headers,
        json={"market": "SH", "symbol": "600519", "quantity": 1, "cost_price": "1"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error_code"] == "HOLDING_DUPLICATE"

    currency_mismatch = await db_client.post(
        f"/api/v1/investments/{stock['id']}/holdings",
        headers=household_headers,
        json={"market": "US", "symbol": "AAPL", "quantity": 1, "cost_price": "200"},
    )
    assert currency_mismatch.status_code == 422
    assert currency_mismatch.json()["error_code"] == "HOLDING_CURRENCY_MISMATCH"

    fixed = await _investment(db_client, household_headers, name="定期", investment_type="fixed")
    unsupported = await db_client.post(
        f"/api/v1/investments/{fixed['id']}/holdings",
        headers=household_headers,
        json={"market": "SH", "symbol": "600519", "quantity": 1, "cost_price": "1"},
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["error_code"] == "HOLDING_NOT_SUPPORTED"

    updated = await db_client.put(
        f"/api/v1/investments/{stock['id']}/holdings/{created.json()['data']['id']}",
        headers=household_headers,
        json={"quantity": 120, "cost_price": "1680"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["cost_subtotal"] == "201600.00000000"


async def test_market_quotes_and_refresh_value(
    db_client: AsyncClient, household_headers: dict[str, str], db_app: Any
):
    quotes = await db_client.get(
        "/api/v1/market/quotes?symbols=SH:600519,SZ:000001",
        headers=household_headers,
    )
    assert quotes.status_code == 200, quotes.text
    items = {item["symbol"]: item for item in quotes.json()["data"]["items"]}
    assert items["600519"]["currency"] == "CNY"
    assert items["600519"]["market"] == "SH"

    bad = await db_client.get("/api/v1/market/quotes?symbols=XX:123", headers=household_headers)
    assert bad.status_code == 422

    stock = await _investment(
        db_client,
        household_headers,
        name="快照组合",
        investment_type="stock",
        principal="0",
    )
    for payload in (
        {"market": "SH", "symbol": "600519", "quantity": 100, "cost_price": "1700"},
        {"market": "SZ", "symbol": "000001", "quantity": 200, "cost_price": "10"},
    ):
        response = await db_client.post(
            f"/api/v1/investments/{stock['id']}/holdings",
            headers=household_headers,
            json=payload,
        )
        assert response.status_code == 201, response.text

    refreshed = await db_client.post(
        f"/api/v1/investments/{stock['id']}/refresh-value", headers=household_headers
    )
    assert refreshed.status_code == 200, refreshed.text
    data = refreshed.json()["data"]
    expected = sum(Decimal(item["subtotal"]) for item in data["items"])
    assert Decimal(data["current_value"]) == expected
    assert Decimal(data["previous_value"]) == Decimal("0")

    detail = await db_client.get(f"/api/v1/investments/{stock['id']}", headers=household_headers)
    assert detail.json()["data"]["current_value"] == data["current_value"]
    assert detail.json()["data"]["holdings_cost"] == "172000.00000000"

    async with db_app.state.db_session_factory() as session:
        value_audits = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.entity_type == "investment",
                    AuditLog.entity_id == stock["id"],
                    AuditLog.action == "investment.value",
                )
            )
        ).all()
    assert any((row.after_data or {}).get("source") == "quote" for row in value_audits)

    no_holdings = await _investment(db_client, household_headers, name="空的")
    empty = await db_client.post(
        f"/api/v1/investments/{no_holdings['id']}/refresh-value",
        headers=household_headers,
    )
    assert empty.status_code == 422


async def test_quote_cache_and_provider_failure(monkeypatch: Any) -> None:
    from app.modules.market import service as market_service

    market_service.clear_cache()
    quotes = await market_service.fetch_quotes([("SH", "600000")])
    assert "SH:600000" in quotes

    class EmptyProvider:
        async def fetch(self, refs: list[tuple[str, str]]) -> dict:
            return {}

    monkeypatch.setitem(market_service._PROVIDERS, "fake", EmptyProvider)
    market_service.clear_cache()
    try:
        await market_service.fetch_quotes([("SH", "600001")])
        raise AssertionError("expected QUOTE_PROVIDER_ERROR")
    except Exception as exc:  # noqa: BLE001 - asserting the mapped error
        assert getattr(exc, "error_code", None) == "QUOTE_PROVIDER_ERROR"
        assert exc.status_code == 502  # type: ignore[attr-defined]
    finally:
        market_service.clear_cache()


async def test_cross_currency_redeem_uses_rate_table(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    dollar_cash = await _create_account(
        db_client, household_headers, name="美元储蓄", currency="USD"
    )
    await _set_opening(db_client, household_headers, dollar_cash["id"], "1000", exchange_rate="7.1")
    dollar_brokerage = await _create_account(
        db_client,
        household_headers,
        name="美元券商",
        account_type="investment",
        currency="USD",
    )

    rate = await db_client.post(
        "/api/v1/exchange-rates",
        headers=household_headers,
        json={
            "base_currency": "USD",
            "quote_currency": "CNY",
            "rate": "7.2",
            "rate_date": TODAY.isoformat(),
        },
    )
    assert rate.status_code == 201, rate.text
    rate_id = rate.json()["data"]["id"]

    created = await _investment(
        db_client,
        household_headers,
        name="美元基金",
        currency="USD",
        account_id=dollar_brokerage["id"],
        fund_transfer={"from_account_id": dollar_cash["id"], "from_amount": "100"},
    )
    assert created["principal"] == "100.00000000"

    # Without a rate the redeem cannot fix its base-currency value.
    deleted = await db_client.delete(f"/api/v1/exchange-rates/{rate_id}", headers=household_headers)
    assert deleted.status_code == 200
    blocked = await db_client.post(
        f"/api/v1/investments/{created['id']}/redeem",
        headers=household_headers,
        json={"to_account_id": dollar_cash["id"], "to_amount": "110"},
    )
    assert blocked.status_code == 400
    assert blocked.json()["error_code"] == "EXCHANGE_RATE_NOT_FOUND"

    restored = await db_client.post(
        "/api/v1/exchange-rates",
        headers=household_headers,
        json={
            "base_currency": "USD",
            "quote_currency": "CNY",
            "rate": "7.2",
            "rate_date": TODAY.isoformat(),
        },
    )
    assert restored.status_code == 201

    redeemed = await db_client.post(
        f"/api/v1/investments/{created['id']}/redeem",
        headers=household_headers,
        json={"to_account_id": dollar_cash["id"], "to_amount": "110"},
    )
    assert redeemed.status_code == 200, redeemed.text

    transactions = await db_client.get(
        f"/api/v1/accounts/{dollar_brokerage['id']}/transactions",
        headers=household_headers,
    )
    pnl_rows = [
        row
        for row in transactions.json()["data"]["items"]
        if row["source"] == "system" and row["status"] == "confirmed"
    ]
    assert len(pnl_rows) == 1
    assert pnl_rows[0]["transaction_type"] == "income"
    assert pnl_rows[0]["base_amount"] == "72.00000000"  # 10 USD pnl * 7.2
