"""Net worth summary, daily snapshots, and monthly aggregation (2C-1)."""

from datetime import date
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.modules.assets.models import NetWorthSnapshot
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
    amount: str,
    **extra: object,
) -> None:
    response = await client.put(
        f"/api/v1/accounts/{account_id}/opening-balance",
        headers=headers,
        json={"amount": amount, **extra},
    )
    assert response.status_code == 200, response.text


async def _add_rate(
    client: AsyncClient,
    headers: dict[str, str],
    base: str,
    quote: str,
    rate: str,
    rate_date: str | None = None,
) -> None:
    response = await client.post(
        "/api/v1/exchange-rates",
        headers=headers,
        json={
            "base_currency": base,
            "quote_currency": quote,
            "rate": rate,
            "rate_date": rate_date or date.today().isoformat(),
        },
    )
    assert response.status_code == 201, response.text


async def _summary(client: AsyncClient, headers: dict[str, str]) -> dict:
    response = await client.get("/api/v1/assets/summary", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_summary_single_currency_without_rates(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    bank = await _create_account(db_client, household_headers, name="储蓄", account_type="bank")
    await _set_opening(db_client, household_headers, bank["id"], "1000")
    credit = await _create_account(
        db_client,
        household_headers,
        name="信用卡",
        account_type="credit",
        credit_limit=5000,
    )
    await _set_opening(db_client, household_headers, credit["id"], "-200")

    summary = await _summary(db_client, household_headers)
    assert summary["base_currency"] == "CNY"
    assert summary["buckets"]["idle"] == "1000.00000000"
    assert summary["buckets"]["invested"] == "0E-8"
    assert summary["buckets"]["matured"] == "0E-8"
    assert summary["total_liabilities"] == "200.00000000"
    assert summary["net_worth"] == "800.00000000"
    assert summary["unmapped_cash"] == "0E-8"
    assert summary["matured_investments"] == []
    assert summary["inactive_count"] == 0
    breakdown = {line["currency"]: line for line in summary["currency_breakdown"]}
    assert breakdown["CNY"]["cash"] == "1000.00000000"
    assert breakdown["CNY"]["liabilities"] == "200.00000000"


async def test_summary_multi_currency_conversion_and_gap(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    bank = await _create_account(db_client, household_headers, name="人民币")
    await _set_opening(db_client, household_headers, bank["id"], "1000")
    dollar = await _create_account(db_client, household_headers, name="美元户", currency="USD")
    await _set_opening(db_client, household_headers, dollar["id"], "100", exchange_rate="7.1")

    missing = await db_client.get("/api/v1/assets/summary", headers=household_headers)
    assert missing.status_code == 400
    assert missing.json()["error_code"] == "EXCHANGE_RATE_NOT_FOUND"
    assert missing.json()["data"]["missing"] == ["USD/CNY"]

    await _add_rate(db_client, household_headers, "USD", "CNY", "7.2")
    summary = await _summary(db_client, household_headers)
    assert summary["net_worth"] == "1720.00000000"
    breakdown = {line["currency"]: line for line in summary["currency_breakdown"]}
    assert breakdown["USD"]["fx_rate"] == "7.200000000000"
    assert summary["fx_rates_used"]["USD"] == "7.200000000000"


async def test_summary_daily_interest_and_credit_overpay(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    savings = await _create_account(
        db_client,
        household_headers,
        name="活期",
        account_type="bank",
        annual_rate=0.03,
    )
    await _set_opening(db_client, household_headers, savings["id"], "3650")
    credit = await _create_account(
        db_client, household_headers, name="溢缴信用卡", account_type="credit"
    )
    await _set_opening(db_client, household_headers, credit["id"], "50")

    summary = await _summary(db_client, household_headers)
    assert summary["daily_interest_income"] == "0.30000000"
    assert summary["daily_interest_expense"] == "0E-8"
    # Overpaid credit counts as cash, not liabilities.
    assert summary["buckets"]["idle"] == "3700.00000000"
    assert summary["total_liabilities"] == "0E-8"


async def test_summary_counts_inactive_accounts(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    dormant = await _create_account(db_client, household_headers, name="旧账户")
    await _set_opening(db_client, household_headers, dormant["id"], "300")
    deactivated = await db_client.put(
        f"/api/v1/accounts/{dormant['id']}",
        headers=household_headers,
        json={"is_active": False},
    )
    assert deactivated.status_code == 200

    summary = await _summary(db_client, household_headers)
    assert summary["inactive_count"] == 1
    assert summary["buckets"]["idle"] == "300.00000000"


async def test_investment_account_balance_counts_as_invested(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    brokerage = await _create_account(
        db_client, household_headers, name="券商", account_type="investment"
    )
    await _set_opening(db_client, household_headers, brokerage["id"], "500")

    summary = await _summary(db_client, household_headers)
    # No investment is registered, so the display bucket stays empty; the
    # money counts in net worth via the account balance and shows up as
    # unmapped cash (design 5.2).
    assert summary["buckets"]["invested"] == "0E-8"
    assert summary["buckets"]["idle"] == "0E-8"
    assert summary["net_worth"] == "500.00000000"
    assert summary["unmapped_cash"] == "500.00000000"


async def test_snapshot_upsert_and_audit(
    db_client: AsyncClient,
    household_headers: dict[str, str],
    db_app: Any,
):
    bank = await _create_account(db_client, household_headers, name="储蓄")
    await _set_opening(db_client, household_headers, bank["id"], "1000")

    created = await db_client.post("/api/v1/assets/snapshots", headers=household_headers)
    assert created.status_code == 201, created.text
    snapshot = created.json()["data"]
    assert snapshot["net_worth"] == "1000.00000000"
    assert snapshot["snapshot_date"] == date.today().isoformat()

    await _set_opening(db_client, household_headers, bank["id"], "1200")
    updated = await db_client.post("/api/v1/assets/snapshots", headers=household_headers)
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["net_worth"] == "1200.00000000"

    listing = await db_client.get("/api/v1/assets/snapshots", headers=household_headers)
    assert listing.status_code == 200
    assert listing.json()["data"]["total"] == 1

    async with db_app.state.db_session_factory() as session:
        actions = (
            await session.scalars(
                select(AuditLog.action).where(AuditLog.entity_type == "net_worth_snapshot")
            )
        ).all()
    assert "net_worth.snapshot.create" in actions
    assert "net_worth.snapshot.update" in actions


async def test_snapshot_missing_rate_not_written(
    db_client: AsyncClient,
    household_headers: dict[str, str],
    db_app: Any,
):
    dollar = await _create_account(db_client, household_headers, name="美元户", currency="USD")
    await _set_opening(db_client, household_headers, dollar["id"], "100", exchange_rate="7.1")

    failed = await db_client.post("/api/v1/assets/snapshots", headers=household_headers)
    assert failed.status_code == 400
    assert failed.json()["error_code"] == "EXCHANGE_RATE_NOT_FOUND"

    async with db_app.state.db_session_factory() as session:
        count = len((await session.scalars(select(NetWorthSnapshot))).all())
    assert count == 0


async def test_snapshot_trend_and_monthly(
    db_client: AsyncClient,
    household_headers: dict[str, str],
    db_app: Any,
):
    bank = await _create_account(db_client, household_headers, name="储蓄")
    await _set_opening(db_client, household_headers, bank["id"], "1000")

    async with db_app.state.db_session_factory() as session:
        for snapshot_date, net in [
            (date(2026, 9, 30), "900"),
            (date(2026, 10, 15), "1000"),
            (date(2026, 10, 31), "1100"),
        ]:
            session.add(
                NetWorthSnapshot(
                    household_id=bank["household_id"],
                    snapshot_date=snapshot_date,
                    base_currency="CNY",
                    total_cash=Decimal(net),
                    total_invested=Decimal("0"),
                    total_liabilities=Decimal("0"),
                    net_worth=Decimal(net),
                    unrealized_pnl=Decimal("0"),
                    unmapped_cash=Decimal("0"),
                    daily_interest_income=Decimal("0.1"),
                    daily_interest_expense=Decimal("0"),
                    currency_breakdown=[],
                    fx_rates_used={},
                )
            )
        await session.commit()

    today = await db_client.post("/api/v1/assets/snapshots", headers=household_headers)
    assert today.status_code == 201, today.text

    trend = await db_client.get(
        "/api/v1/assets/snapshots?date_from=2026-09-01&date_to=2026-12-31",
        headers=household_headers,
    )
    assert trend.status_code == 200
    dates = [item["snapshot_date"] for item in trend.json()["data"]["items"]]
    assert dates == ["2026-09-30", "2026-10-15", "2026-10-31", date.today().isoformat()]

    monthly = await db_client.get(
        "/api/v1/assets/snapshots/monthly?year=2026", headers=household_headers
    )
    assert monthly.status_code == 200, monthly.text
    months = {item["month"]: item for item in monthly.json()["data"]["months"]}
    assert months["2026-09"]["snapshot_count"] == 1
    assert months["2026-09"]["net_change"] == "0E-8"
    assert months["2026-10"]["snapshot_count"] == 2
    assert months["2026-10"]["net_worth_start"] == "1000.00000000"
    assert months["2026-10"]["net_worth_end"] == "1100.00000000"
    assert months["2026-10"]["net_change"] == "100.00000000"
    assert months["2026-10"]["daily_interest_income"] == "0.20000000"

    empty = await db_client.get(
        "/api/v1/assets/snapshots/monthly?year=2024", headers=household_headers
    )
    assert empty.status_code == 200
    assert empty.json()["data"]["months"] == []


async def _investment(client: AsyncClient, headers: dict[str, str], **payload: object) -> dict:
    from datetime import date as date_

    body: dict[str, object] = {
        "name": "投资",
        "investment_type": "fund",
        "currency": "CNY",
        "start_date": date_.today().isoformat(),
    }
    body.update(payload)
    response = await client.post("/api/v1/investments", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_summary_four_quadrant_net_worth(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    """Managed / unmanaged / matured / unmapped-cash quadrants (design 5.2)."""
    from datetime import date, timedelta

    TODAY = date.today()
    bank = await _create_account(db_client, household_headers, name="储蓄")
    await _set_opening(db_client, household_headers, bank["id"], "1000")
    brokerage = await _create_account(
        db_client, household_headers, name="券商", account_type="investment"
    )
    cash_fund = await _create_account(db_client, household_headers, name="划款户")
    await _set_opening(db_client, household_headers, cash_fund["id"], "20000")

    managed = await _investment(
        db_client,
        household_headers,
        name="在投基金",
        account_id=brokerage["id"],
        fund_transfer={"from_account_id": cash_fund["id"], "from_amount": "6000"},
    )
    await db_client.put(
        f"/api/v1/investments/{managed['id']}/value",
        headers=household_headers,
        json={"current_value": "7000"},
    )
    unmanaged = await _investment(
        db_client,
        household_headers,
        name="未托管股票",
        investment_type="stock",
        principal="2000",
    )
    await db_client.put(
        f"/api/v1/investments/{unmanaged['id']}/value",
        headers=household_headers,
        json={"current_value": "2500"},
    )
    matured = await _investment(
        db_client,
        household_headers,
        name="到期定存",
        account_id=brokerage["id"],
        principal="1000",
        end_date=(TODAY - timedelta(days=1)).isoformat(),
    )
    await db_client.put(
        f"/api/v1/investments/{matured['id']}/value",
        headers=household_headers,
        json={"current_value": "1100"},
    )

    summary = await _summary(db_client, household_headers)
    assert summary["buckets"]["idle"] == "15000.00000000"  # bank 1000 + funding leftover 14000
    assert summary["buckets"]["invested"] == "8500.00000000"  # 6000 + 2500
    assert summary["buckets"]["matured"] == "1000.00000000"
    assert summary["unrealized_pnl"] == "1100.00000000"
    assert summary["unmapped_cash"] == "-1000.00000000"
    # net = 1000 cash + 6000 account + 1100 floating + 2500 unmanaged
    assert summary["net_worth"] == "24600.00000000"  # 15000 + 6000 + 1100 + 2500
    assert len(summary["matured_investments"]) == 1
    assert summary["matured_investments"][0]["name"] == "到期定存"

    snapshot = await db_client.post("/api/v1/assets/snapshots", headers=household_headers)
    assert snapshot.status_code == 201, snapshot.text
    assert snapshot.json()["data"]["net_worth"] == "24600.00000000"
