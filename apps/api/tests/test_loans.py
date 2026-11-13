"""Loans: CRUD, settle, validation, and net worth integration (2C-3)."""

from datetime import date
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.modules.audit.models import AuditLog

TODAY = date.today()


async def _create_loan(client: AsyncClient, headers: dict[str, str], **overrides: object) -> dict:
    payload: dict[str, object] = {
        "name": "房贷",
        "principal": "1000000",
        "currency": "CNY",
        "annual_rate": "0.039",
        "start_date": "2020-01-01",
        "repayment_type": "monthly_interest",
        "due_day": 20,
    }
    payload.update(overrides)
    response = await client.post("/api/v1/loans", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _summary(client: AsyncClient, headers: dict[str, str]) -> dict:
    response = await client.get("/api/v1/assets/summary", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_loan_crud_and_defaults(db_client: AsyncClient, household_headers: dict[str, str]):
    loan = await _create_loan(db_client, household_headers, institution="工行")
    assert loan["remaining_principal"] == "1000000.00000000"
    assert loan["status"] == "active"
    assert loan["daily_interest"] == str(
        round(Decimal("1000000") * Decimal("0.039") / Decimal("365"), 8)
    )

    listing = await db_client.get("/api/v1/loans?status=active", headers=household_headers)
    assert listing.json()["data"]["total"] == 1

    fetched = await db_client.get(f"/api/v1/loans/{loan['id']}", headers=household_headers)
    assert fetched.json()["data"]["name"] == "房贷"

    updated = await db_client.put(
        f"/api/v1/loans/{loan['id']}",
        headers=household_headers,
        json={"remaining_principal": "900000", "due_day": 1},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["remaining_principal"] == "900000.00000000"


async def test_loan_registration_with_reduced_principal(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    """Registering an existing loan starts from its remaining balance."""
    loan = await _create_loan(
        db_client, household_headers, principal="500000", remaining_principal="400000"
    )
    assert loan["principal"] == "500000.00000000"
    assert loan["remaining_principal"] == "400000.00000000"


async def test_loan_validations(
    db_client: AsyncClient,
    household_headers: dict[str, str],
    create_household: Any,
    auth_for_household: Any,
):
    zero_principal = await db_client.post(
        "/api/v1/loans",
        headers=household_headers,
        json={
            "name": "零本金",
            "principal": 0,
            "currency": "CNY",
            "annual_rate": "0.01",
            "start_date": "2020-01-01",
            "repayment_type": "one_time",
        },
    )
    assert zero_principal.status_code == 422

    over = await db_client.post(
        "/api/v1/loans",
        headers=household_headers,
        json={
            "name": "超额剩余",
            "principal": "1000",
            "remaining_principal": "2000",
            "currency": "CNY",
            "annual_rate": "0.01",
            "start_date": "2020-01-01",
            "repayment_type": "one_time",
        },
    )
    assert over.status_code == 422

    bad_day = await db_client.post(
        "/api/v1/loans",
        headers=household_headers,
        json={
            "name": "坏还款日",
            "principal": "1000",
            "currency": "CNY",
            "annual_rate": "0.01",
            "start_date": "2020-01-01",
            "repayment_type": "one_time",
            "due_day": 32,
        },
    )
    assert bad_day.status_code == 422

    unknown_currency = await db_client.post(
        "/api/v1/loans",
        headers=household_headers,
        json={
            "name": "坏币种",
            "principal": "1000",
            "currency": "XXX",
            "annual_rate": "0.01",
            "start_date": "2020-01-01",
            "repayment_type": "one_time",
        },
    )
    assert unknown_currency.status_code == 404
    assert unknown_currency.json()["error_code"] == "CURRENCY_NOT_FOUND"

    # linked_account_id is validated against the household scope.
    second_id = await create_household()
    second_headers = await auth_for_household(second_id)
    foreign_account = await db_client.post(
        "/api/v1/accounts",
        headers=second_headers,
        json={"name": "他家账户", "account_type": "bank", "currency": "CNY"},
    )
    assert foreign_account.status_code == 201
    wrong_account = await db_client.post(
        "/api/v1/loans",
        headers=household_headers,
        json={
            "name": "坏关联账户",
            "principal": "1000",
            "currency": "CNY",
            "annual_rate": "0.01",
            "start_date": "2020-01-01",
            "repayment_type": "one_time",
            "linked_account_id": foreign_account.json()["data"]["id"],
        },
    )
    assert wrong_account.status_code == 404


async def test_settle_semantics_and_audit(
    db_client: AsyncClient, household_headers: dict[str, str], db_app: Any
):
    loan = await _create_loan(db_client, household_headers)
    settled = await db_client.post(
        f"/api/v1/loans/{loan['id']}/settle",
        headers=household_headers,
        json={"settled_date": TODAY.isoformat()},
    )
    assert settled.status_code == 200, settled.text
    data = settled.json()["data"]
    assert data["status"] == "settled"
    assert data["remaining_principal"] == "0E-8"
    assert data["daily_interest"] == "0E-8"

    again = await db_client.post(
        f"/api/v1/loans/{loan['id']}/settle",
        headers=household_headers,
        json={"settled_date": TODAY.isoformat()},
    )
    assert again.status_code == 409
    assert again.json()["error_code"] == "LOAN_ALREADY_SETTLED"

    edit = await db_client.put(
        f"/api/v1/loans/{loan['id']}",
        headers=household_headers,
        json={"name": "改名"},
    )
    assert edit.status_code == 409

    deleted = await db_client.delete(f"/api/v1/loans/{loan['id']}", headers=household_headers)
    assert deleted.status_code == 409
    assert deleted.json()["error_code"] == "LOAN_NOT_DELETABLE"

    async with db_app.state.db_session_factory() as session:
        actions = (
            await session.scalars(
                select(AuditLog.action).where(
                    AuditLog.entity_type == "loan", AuditLog.entity_id == loan["id"]
                )
            )
        ).all()
    assert "loan.create" in actions
    assert "loan.settle" in actions


async def test_loans_drive_net_worth_and_daily_interest(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    bank = await db_client.post(
        "/api/v1/accounts",
        headers=household_headers,
        json={"name": "储蓄", "account_type": "bank", "currency": "CNY"},
    )
    assert bank.status_code == 201
    opening = await db_client.put(
        f"/api/v1/accounts/{bank.json()['data']['id']}/opening-balance",
        headers=household_headers,
        json={"amount": "365000"},
    )
    assert opening.status_code == 200

    loan = await _create_loan(
        db_client, household_headers, remaining_principal="100000", annual_rate="0.0365"
    )
    summary = await _summary(db_client, household_headers)
    assert summary["total_liabilities"] == "100000.00000000"
    assert summary["net_worth"] == "265000.00000000"
    # 100000 x 0.0365 / 365 = 10 per day.
    assert summary["daily_interest_expense"] == "10.00000000"

    snapshot = await db_client.post("/api/v1/assets/snapshots", headers=household_headers)
    assert snapshot.status_code == 201, snapshot.text
    assert snapshot.json()["data"]["net_worth"] == "265000.00000000"
    assert snapshot.json()["data"]["daily_interest_expense"] == "10.00000000"

    # Settling removes the liability and the interest.
    settled = await db_client.post(
        f"/api/v1/loans/{loan['id']}/settle",
        headers=household_headers,
        json={"settled_date": TODAY.isoformat()},
    )
    assert settled.status_code == 200
    after = await _summary(db_client, household_headers)
    assert after["total_liabilities"] == "0E-8"
    assert after["net_worth"] == "365000.00000000"
    assert after["daily_interest_expense"] == "0E-8"


async def test_foreign_currency_loan_converts(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    dollar = await db_client.post(
        "/api/v1/accounts",
        headers=household_headers,
        json={"name": "美元户", "account_type": "bank", "currency": "USD"},
    )
    assert dollar.status_code == 201
    opening = await db_client.put(
        f"/api/v1/accounts/{dollar.json()['data']['id']}/opening-balance",
        headers=household_headers,
        json={"amount": "10000", "exchange_rate": "7.1"},
    )
    assert opening.status_code == 200

    loan = await _create_loan(
        db_client,
        household_headers,
        name="美元留学贷",
        currency="USD",
        principal="5000",
        remaining_principal="1000",
        annual_rate="0.05",
        repayment_type="one_time",
    )
    assert loan["currency"] == "USD"

    missing = await db_client.get("/api/v1/assets/summary", headers=household_headers)
    assert missing.status_code == 400
    assert missing.json()["error_code"] == "EXCHANGE_RATE_NOT_FOUND"

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
    assert rate.status_code == 201

    summary = await _summary(db_client, household_headers)
    # cash 72000 - liability 7200
    assert summary["net_worth"] == "64800.00000000"
    assert summary["total_liabilities"] == "7200.00000000"
    # 1000 USD x 0.05 / 365 x 7.2 = 0.98630136... -> 0.98630137? quantize 8dp
    expected_interest = Decimal("1000") * Decimal("0.05") / Decimal("365") * Decimal("7.2")
    assert Decimal(summary["daily_interest_expense"]) == round(expected_interest, 8)
