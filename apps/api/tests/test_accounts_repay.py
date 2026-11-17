"""Credit-card repayment: one confirmed fee-free transfer per repay action."""

from datetime import date
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.modules.audit.models import AuditLog

TODAY = date.today()


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


async def _balances(
    client: AsyncClient, headers: dict[str, str], account_id: str
) -> dict[str, Decimal]:
    response = await client.get(f"/api/v1/accounts/{account_id}/balances", headers=headers)
    assert response.status_code == 200, response.text
    return {
        item["currency"]: Decimal(item["book_balance"])
        for item in response.json()["data"]["balances"]
    }


async def _repay(
    client: AsyncClient, headers: dict[str, str], account_id: str, **payload: object
) -> Any:
    return await client.post(f"/api/v1/accounts/{account_id}/repay", headers=headers, json=payload)


async def _transfers_total(client: AsyncClient, headers: dict[str, str]) -> int:
    response = await client.get("/api/v1/transfers?page_size=1", headers=headers)
    assert response.status_code == 200, response.text
    return int(response.json()["data"]["total"])


async def _credit_scenario(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    card_opening: str = "-2000",
    cash_opening: str = "3000",
) -> tuple[dict, dict]:
    """A CNY credit card carrying debt plus a funded CNY cash account."""
    card = await _create_account(
        client, headers, name="招行信用卡", account_type="credit", currency="CNY"
    )
    cash = await _create_account(client, headers, name="现金", currency="CNY")
    await _set_opening(client, headers, card["id"], card_opening)
    await _set_opening(client, headers, cash["id"], cash_opening)
    return card, cash


async def test_repay_clears_debt_to_zero(db_client: AsyncClient, household_headers: dict[str, str]):
    card, cash = await _credit_scenario(db_client, household_headers)

    response = await _repay(
        db_client, household_headers, card["id"], from_account_id=cash["id"], amount="2000"
    )

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["status"] == "confirmed"
    assert data["from_account_id"] == cash["id"]
    assert data["to_account_id"] == card["id"]
    assert Decimal(data["from_amount"]) == Decimal("2000")
    assert Decimal(data["to_amount"]) == Decimal("2000")
    assert Decimal(data["fee"]) == Decimal("0")
    assert Decimal(data["exchange_rate"]) == Decimal("1")
    assert data["description"] == "信用卡还款"
    assert data["reverses_transfer_id"] is None
    assert await _balances(db_client, household_headers, cash["id"]) == {"CNY": Decimal("1000")}
    assert await _balances(db_client, household_headers, card["id"]) == {"CNY": Decimal("0")}


async def test_partial_repay(db_client: AsyncClient, household_headers: dict[str, str]):
    card, cash = await _credit_scenario(db_client, household_headers)

    response = await _repay(
        db_client, household_headers, card["id"], from_account_id=cash["id"], amount="500"
    )

    assert response.status_code == 201, response.text
    assert await _balances(db_client, household_headers, card["id"]) == {"CNY": Decimal("-1500")}
    assert await _balances(db_client, household_headers, cash["id"]) == {"CNY": Decimal("2500")}


async def test_overpay_creates_credit_balance(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    card, cash = await _credit_scenario(
        db_client, household_headers, card_opening="-200", cash_opening="1000"
    )

    response = await _repay(
        db_client, household_headers, card["id"], from_account_id=cash["id"], amount="300"
    )

    assert response.status_code == 201, response.text
    assert await _balances(db_client, household_headers, card["id"]) == {"CNY": Decimal("100")}


async def test_repay_without_debt_allowed(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    card, cash = await _credit_scenario(
        db_client, household_headers, card_opening="0", cash_opening="500"
    )

    response = await _repay(
        db_client, household_headers, card["id"], from_account_id=cash["id"], amount="100"
    )

    assert response.status_code == 201, response.text
    assert await _balances(db_client, household_headers, card["id"]) == {"CNY": Decimal("100")}


async def test_non_credit_target_rejected(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    bank = await _create_account(db_client, household_headers, name="储蓄卡")
    cash = await _create_account(db_client, household_headers, name="现金")
    await _set_opening(db_client, household_headers, cash["id"], "1000")

    response = await _repay(
        db_client, household_headers, bank["id"], from_account_id=cash["id"], amount="100"
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "REPAY_TARGET_NOT_CREDIT"
    assert await _transfers_total(db_client, household_headers) == 0


async def test_self_repay_rejected(db_client: AsyncClient, household_headers: dict[str, str]):
    card, _cash = await _credit_scenario(db_client, household_headers)

    response = await _repay(
        db_client, household_headers, card["id"], from_account_id=card["id"], amount="100"
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "REPAY_SOURCE_SAME"


async def test_cross_currency_from_account_rejected(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    card, _cash = await _credit_scenario(db_client, household_headers)
    dollar_cash = await _create_account(
        db_client, household_headers, name="美元现金", currency="USD"
    )
    await _set_opening(db_client, household_headers, dollar_cash["id"], "1000", exchange_rate="7.1")

    response = await _repay(
        db_client,
        household_headers,
        card["id"],
        from_account_id=dollar_cash["id"],
        amount="100",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "REPAY_CURRENCY_MISMATCH"


async def test_investment_from_account_rejected(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    card, _cash = await _credit_scenario(db_client, household_headers)
    brokerage = await _create_account(
        db_client, household_headers, name="券商账户", account_type="investment", currency="CNY"
    )
    await _set_opening(db_client, household_headers, brokerage["id"], "5000")

    response = await _repay(
        db_client,
        household_headers,
        card["id"],
        from_account_id=brokerage["id"],
        amount="100",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "REPAY_SOURCE_INVESTMENT"


async def test_inactive_accounts_rejected(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    card, cash = await _credit_scenario(db_client, household_headers)
    disabled = await db_client.put(
        f"/api/v1/accounts/{cash['id']}", headers=household_headers, json={"is_active": False}
    )
    assert disabled.status_code == 200, disabled.text

    response = await _repay(
        db_client, household_headers, card["id"], from_account_id=cash["id"], amount="100"
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "ACCOUNT_INACTIVE"

    reenabled = await db_client.put(
        f"/api/v1/accounts/{cash['id']}", headers=household_headers, json={"is_active": True}
    )
    assert reenabled.status_code == 200, reenabled.text
    disabled_card = await db_client.put(
        f"/api/v1/accounts/{card['id']}", headers=household_headers, json={"is_active": False}
    )
    assert disabled_card.status_code == 200, disabled_card.text

    response = await _repay(
        db_client, household_headers, card["id"], from_account_id=cash["id"], amount="100"
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "ACCOUNT_INACTIVE"


async def test_insufficient_funds_rejected(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    card, cash = await _credit_scenario(
        db_client, household_headers, card_opening="-2000", cash_opening="100"
    )

    response = await _repay(
        db_client, household_headers, card["id"], from_account_id=cash["id"], amount="200"
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "INSUFFICIENT_BALANCE"
    assert await _transfers_total(db_client, household_headers) == 0
    assert await _balances(db_client, household_headers, cash["id"]) == {"CNY": Decimal("100")}
    assert await _balances(db_client, household_headers, card["id"]) == {"CNY": Decimal("-2000")}


async def test_amount_must_be_positive(db_client: AsyncClient, household_headers: dict[str, str]):
    card, cash = await _credit_scenario(db_client, household_headers)

    for invalid in ("0", "-5"):
        response = await _repay(
            db_client,
            household_headers,
            card["id"],
            from_account_id=cash["id"],
            amount=invalid,
        )
        assert response.status_code == 422, response.text

    # CNY has 2 decimal places: 0.001 rounds to zero.
    rounded = await _repay(
        db_client, household_headers, card["id"], from_account_id=cash["id"], amount="0.001"
    )
    assert rounded.status_code == 400
    assert rounded.json()["error_code"] == "AMOUNT_INVALID"


async def test_repay_transfer_reversal_restores_state(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    card, cash = await _credit_scenario(db_client, household_headers)
    response = await _repay(
        db_client, household_headers, card["id"], from_account_id=cash["id"], amount="2000"
    )
    assert response.status_code == 201, response.text
    transfer_id = response.json()["data"]["id"]

    reversed_response = await db_client.post(
        f"/api/v1/transfers/{transfer_id}/reverse", headers=household_headers
    )
    assert reversed_response.status_code == 201, reversed_response.text

    assert await _balances(db_client, household_headers, cash["id"]) == {"CNY": Decimal("3000")}
    assert await _balances(db_client, household_headers, card["id"]) == {"CNY": Decimal("-2000")}
    detail = await db_client.get(f"/api/v1/transfers/{transfer_id}", headers=household_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["status"] == "reversed"


async def test_repay_audit_written(
    db_client: AsyncClient, household_headers: dict[str, str], db_app: Any
):
    card, cash = await _credit_scenario(db_client, household_headers)
    response = await _repay(
        db_client, household_headers, card["id"], from_account_id=cash["id"], amount="2000"
    )
    assert response.status_code == 201, response.text
    transfer_id = response.json()["data"]["id"]

    async with db_app.state.db_session_factory() as session:
        account_actions = (
            await session.scalars(
                select(AuditLog.action).where(
                    AuditLog.entity_type == "account",
                    AuditLog.entity_id == card["id"],
                )
            )
        ).all()
        transfer_actions = (
            await session.scalars(
                select(AuditLog.action).where(
                    AuditLog.entity_type == "transfer",
                    AuditLog.entity_id == transfer_id,
                )
            )
        ).all()

    assert "account.repay" in account_actions
    assert "transfer.create" in transfer_actions


async def test_repay_custom_date_and_description(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    card, cash = await _credit_scenario(db_client, household_headers)

    response = await _repay(
        db_client,
        household_headers,
        card["id"],
        from_account_id=cash["id"],
        amount="2000",
        transfer_date="2026-06-15T10:00:00+08:00",
        description="行内还款",
    )

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["description"] == "行内还款"
    assert data["transfer_date"].startswith("2026-06-15")


async def test_repay_foreign_currency_card_uses_rate_table(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    dollar_card = await _create_account(
        db_client, household_headers, name="美元信用卡", account_type="credit", currency="USD"
    )
    dollar_cash = await _create_account(
        db_client, household_headers, name="美元现金", currency="USD"
    )
    rate = await db_client.post(
        "/api/v1/exchange-rates",
        headers=household_headers,
        json={
            "base_currency": "USD",
            "quote_currency": "CNY",
            "rate": "7.1",
            "rate_date": TODAY.isoformat(),
        },
    )
    assert rate.status_code == 201, rate.text
    rate_id = rate.json()["data"]["id"]
    await _set_opening(db_client, household_headers, dollar_card["id"], "-200", exchange_rate="7.1")
    await _set_opening(db_client, household_headers, dollar_cash["id"], "1000", exchange_rate="7.1")

    # Same-currency legs but neither is the household base: no rate -> explicit 400.
    deleted = await db_client.delete(f"/api/v1/exchange-rates/{rate_id}", headers=household_headers)
    assert deleted.status_code == 200, deleted.text
    missing = await _repay(
        db_client,
        household_headers,
        dollar_card["id"],
        from_account_id=dollar_cash["id"],
        amount="100",
    )
    assert missing.status_code == 400
    assert missing.json()["error_code"] == "EXCHANGE_RATE_NOT_FOUND"
    assert missing.json()["data"]["missing"] == ["USD/CNY"]

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
    assert restored.status_code == 201, restored.text

    response = await _repay(
        db_client,
        household_headers,
        dollar_card["id"],
        from_account_id=dollar_cash["id"],
        amount="100",
    )
    assert response.status_code == 201, response.text
    assert Decimal(response.json()["data"]["base_amount"]) == Decimal("720")
    assert await _balances(db_client, household_headers, dollar_card["id"]) == {
        "USD": Decimal("-100")
    }


async def test_repay_cross_household_account_not_found(
    db_client: AsyncClient,
    household_headers: dict[str, str],
    create_household: Any,
    auth_for_household: Any,
):
    card, cash = await _credit_scenario(db_client, household_headers)
    other_id = await create_household()
    other_headers = await auth_for_household(other_id)

    response = await _repay(
        db_client, other_headers, card["id"], from_account_id=cash["id"], amount="100"
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "ACCOUNT_NOT_FOUND"
