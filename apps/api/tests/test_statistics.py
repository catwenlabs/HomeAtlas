"""Income/expense statistics: totals, categories, periods, and time zones (Phase 1.4)."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from httpx import AsyncClient

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


async def _statistics(
    client: AsyncClient, headers: dict[str, str], path: str, query: str = ""
) -> dict:
    response = await client.get(f"/api/v1/statistics/{path}?{query}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _amount(value: str) -> Decimal:
    return Decimal(value)


async def test_income_expense_excludes_opening_drafts_and_reversals(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    await _set_opening(db_client, household_headers, account["id"], "1000")
    salary = await _find_category(db_client, household_headers, "工资")
    dining = await _find_category(db_client, household_headers, "餐饮")

    await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        category_id=salary["id"],
        transaction_type="income",
        amount="100",
        transaction_date="2026-06-05T09:00:00+08:00",
        status="confirmed",
    )
    await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        category_id=dining["id"],
        transaction_type="expense",
        amount="30",
        transaction_date="2026-06-06T12:00:00+08:00",
        status="confirmed",
    )
    await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        category_id=dining["id"],
        transaction_type="expense",
        amount="20",
        transaction_date="2026-06-07T12:00:00+08:00",
    )
    reversed_expense = await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        category_id=dining["id"],
        transaction_type="expense",
        amount="40",
        transaction_date="2026-06-08T12:00:00+08:00",
        status="confirmed",
    )
    reversed_response = await db_client.post(
        f"/api/v1/transactions/{reversed_expense['id']}/reverse", headers=household_headers
    )
    assert reversed_response.status_code == 201, reversed_response.text

    data = await _statistics(
        db_client,
        household_headers,
        "income-expense",
        "start_date=2026-06-01&end_date=2026-06-30",
    )
    assert data["base_currency"] == "CNY"
    assert data["start_date"] == "2026-06-01"
    assert data["end_date"] == "2026-06-30"
    assert _amount(data["income"]) == Decimal("100")
    assert _amount(data["expense"]) == Decimal("30")
    assert _amount(data["net"]) == Decimal("70")
    assert data["income_count"] == 1
    assert data["expense_count"] == 1
    assert data["transaction_count"] == 2


async def test_income_expense_defaults_to_current_household_month(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        transaction_type="income",
        amount="25",
        status="confirmed",
    )

    data = await _statistics(db_client, household_headers, "income-expense")
    assert _amount(data["income"]) == Decimal("25")
    assert _amount(data["expense"]) == Decimal("0")
    assert _amount(data["net"]) == Decimal("25")


async def test_category_breakdown_percentages_and_uncategorized(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    await _set_opening(db_client, household_headers, account["id"], "1000")
    salary = await _find_category(db_client, household_headers, "工资")
    dining = await _find_category(db_client, household_headers, "餐饮")
    transport = await _find_category(db_client, household_headers, "交通")

    for category_id, amount in (
        (dining["id"], "30"),
        (transport["id"], "20"),
        (None, "50"),
    ):
        await _create_transaction(
            db_client,
            household_headers,
            account_id=account["id"],
            category_id=category_id,
            transaction_type="expense",
            amount=amount,
            transaction_date="2026-06-10T12:00:00+08:00",
            status="confirmed",
        )
    await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        category_id=salary["id"],
        transaction_type="income",
        amount="100",
        transaction_date="2026-06-10T12:00:00+08:00",
        status="confirmed",
    )

    data = await _statistics(
        db_client,
        household_headers,
        "category",
        "start_date=2026-06-01&end_date=2026-06-30",
    )
    assert _amount(data["income_total"]) == Decimal("100")
    assert _amount(data["expense_total"]) == Decimal("100")
    by_name = {item["category_name"]: item for item in data["items"]}
    assert _amount(by_name["餐饮"]["amount"]) == Decimal("30")
    assert _amount(by_name["餐饮"]["percentage"]) == Decimal("30")
    assert _amount(by_name["交通"]["percentage"]) == Decimal("20")
    assert by_name["未分类"]["category_id"] is None
    assert _amount(by_name["未分类"]["percentage"]) == Decimal("50")
    assert by_name["工资"]["category_type"] == "income"
    assert _amount(by_name["工资"]["percentage"]) == Decimal("100")

    expense_only = await _statistics(
        db_client,
        household_headers,
        "category",
        "start_date=2026-06-01&end_date=2026-06-30&transaction_type=expense",
    )
    assert {item["category_type"] for item in expense_only["items"]} == {"expense"}
    assert _amount(expense_only["income_total"]) == Decimal("0")
    assert _amount(expense_only["expense_total"]) == Decimal("100")

    invalid = await db_client.get(
        "/api/v1/statistics/category?transaction_type=opening_balance",
        headers=household_headers,
    )
    assert invalid.status_code == 422


async def test_monthly_grouping_uses_household_timezone(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    await _set_opening(db_client, household_headers, account["id"], "1000")

    await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        transaction_type="income",
        amount="5",
        transaction_date="2026-02-28T23:00:00+08:00",
        status="confirmed",
    )
    await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        transaction_type="expense",
        amount="7",
        transaction_date="2026-02-28T23:30:00+08:00",
        status="confirmed",
    )
    # 02:00 on March 1 in Shanghai is still February 28 in UTC.
    await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        transaction_type="expense",
        amount="10",
        transaction_date="2026-03-01T02:00:00+08:00",
        status="confirmed",
    )

    data = await _statistics(
        db_client,
        household_headers,
        "monthly",
        "start_date=2026-02-01&end_date=2026-03-31&granularity=month",
    )
    assert data["granularity"] == "month"
    assert [item["period"] for item in data["items"]] == ["2026-02", "2026-03"]
    february, march = data["items"]
    assert _amount(february["income"]) == Decimal("5")
    assert _amount(february["expense"]) == Decimal("7")
    assert _amount(february["net"]) == Decimal("-2")
    assert _amount(march["income"]) == Decimal("0")
    assert _amount(march["expense"]) == Decimal("10")
    assert _amount(march["net"]) == Decimal("-10")
    assert _amount(data["income_total"]) == Decimal("5")
    assert _amount(data["expense_total"]) == Decimal("17")
    assert _amount(data["net_total"]) == Decimal("-12")


async def test_monthly_year_granularity_and_empty_buckets(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    await _set_opening(db_client, household_headers, account["id"], "1000")

    # 02:00 on January 1 in Shanghai is still December 31 in UTC.
    await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        transaction_type="income",
        amount="50",
        transaction_date="2026-01-01T02:00:00+08:00",
        status="confirmed",
    )
    await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        transaction_type="expense",
        amount="5",
        transaction_date="2026-06-01T12:00:00+08:00",
        status="confirmed",
    )

    data = await _statistics(
        db_client,
        household_headers,
        "monthly",
        "start_date=2025-01-01&end_date=2026-12-31&granularity=year",
    )
    assert [item["period"] for item in data["items"]] == ["2025", "2026"]
    assert _amount(data["items"][0]["income"]) == Decimal("0")
    assert _amount(data["items"][1]["income"]) == Decimal("50")
    assert _amount(data["items"][1]["expense"]) == Decimal("5")
    assert _amount(data["items"][1]["net"]) == Decimal("45")

    months = await _statistics(
        db_client,
        household_headers,
        "monthly",
        "start_date=2025-11-01&end_date=2026-01-31&granularity=month",
    )
    assert [item["period"] for item in months["items"]] == [
        "2025-11",
        "2025-12",
        "2026-01",
    ]
    assert _amount(months["items"][2]["income"]) == Decimal("50")


async def test_multi_currency_aggregates_base_amount(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    usd_account = await _create_account(
        db_client, household_headers, name="美元账户", currency="USD"
    )
    cny_account = await _create_account(db_client, household_headers, name="人民币账户")
    await _set_opening(
        db_client, household_headers, usd_account["id"], "1000", exchange_rate="7.10"
    )
    await _set_opening(db_client, household_headers, cny_account["id"], "1000")

    await _create_transaction(
        db_client,
        household_headers,
        account_id=usd_account["id"],
        transaction_type="income",
        amount="10",
        currency="USD",
        exchange_rate="7.10",
        transaction_date="2026-06-10T09:00:00+08:00",
        status="confirmed",
    )
    await _create_transaction(
        db_client,
        household_headers,
        account_id=cny_account["id"],
        transaction_type="expense",
        amount="30",
        transaction_date="2026-06-11T09:00:00+08:00",
        status="confirmed",
    )

    data = await _statistics(
        db_client,
        household_headers,
        "income-expense",
        "start_date=2026-06-01&end_date=2026-06-30",
    )
    assert data["base_currency"] == "CNY"
    assert _amount(data["income"]) == Decimal("71")
    assert _amount(data["expense"]) == Decimal("30")
    assert _amount(data["net"]) == Decimal("41")


async def test_transfer_principal_excluded_and_fee_counted_once(
    db_client: AsyncClient,
    db_app,
    household: dict,
    household_headers: dict[str, str],
):
    account = await _create_account(db_client, household_headers, name="转出账户")
    target = await _create_account(db_client, household_headers, name="转入账户")
    await _set_opening(db_client, household_headers, account["id"], "1000")
    fee_category = await _find_category(db_client, household_headers, "金融手续费")

    async with db_app.state.db_session_factory() as session:
        transfer = Transfer(
            household_id=UUID(household["id"]),
            from_account_id=UUID(account["id"]),
            to_account_id=UUID(target["id"]),
            from_amount=Decimal("500"),
            from_currency="CNY",
            to_amount=Decimal("500"),
            to_currency="CNY",
            exchange_rate=Decimal("1"),
            fee=Decimal("5"),
            fee_currency="CNY",
            transfer_date=datetime.fromisoformat("2026-06-10T10:00:00+08:00"),
            status="confirmed",
        )
        session.add(transfer)
        await session.flush()
        session.add(
            Transaction(
                household_id=UUID(household["id"]),
                account_id=UUID(account["id"]),
                category_id=UUID(fee_category["id"]),
                transaction_type="expense",
                amount=Decimal("5"),
                currency="CNY",
                base_amount=Decimal("5"),
                base_currency="CNY",
                exchange_rate=Decimal("1"),
                exchange_rate_date=transfer.transfer_date.date(),
                transaction_date=transfer.transfer_date,
                description="Transfer fee",
                source="system",
                status="confirmed",
                transfer_id=transfer.id,
            )
        )
        await session.commit()

    data = await _statistics(
        db_client,
        household_headers,
        "income-expense",
        "start_date=2026-06-01&end_date=2026-06-30",
    )
    assert _amount(data["income"]) == Decimal("0")
    assert _amount(data["expense"]) == Decimal("5")
    assert data["transaction_count"] == 1

    by_category = await _statistics(
        db_client,
        household_headers,
        "category",
        "start_date=2026-06-01&end_date=2026-06-30&transaction_type=expense",
    )
    assert len(by_category["items"]) == 1
    assert by_category["items"][0]["category_name"] == "金融手续费"
    assert _amount(by_category["items"][0]["amount"]) == Decimal("5")
    assert _amount(by_category["items"][0]["percentage"]) == Decimal("100")


async def test_cashflow_series_fills_empty_periods_and_cumulates(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    account = await _create_account(db_client, household_headers)
    await _set_opening(db_client, household_headers, account["id"], "1000")

    await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        transaction_type="income",
        amount="100",
        transaction_date="2026-07-01T09:00:00+08:00",
        status="confirmed",
    )
    await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        transaction_type="expense",
        amount="40",
        transaction_date="2026-07-02T12:00:00+08:00",
        status="confirmed",
    )
    await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        transaction_type="income",
        amount="10",
        transaction_date="2026-07-02T18:00:00+08:00",
        status="confirmed",
    )

    data = await _statistics(
        db_client,
        household_headers,
        "cashflow",
        "start_date=2026-07-01&end_date=2026-07-04&granularity=day",
    )
    assert [item["period"] for item in data["items"]] == [
        "2026-07-01",
        "2026-07-02",
        "2026-07-03",
        "2026-07-04",
    ]
    assert [_amount(item["net"]) for item in data["items"]] == [
        Decimal("100"),
        Decimal("-30"),
        Decimal("0"),
        Decimal("0"),
    ]
    assert [_amount(item["cumulative_net"]) for item in data["items"]] == [
        Decimal("100"),
        Decimal("70"),
        Decimal("70"),
        Decimal("70"),
    ]
    assert _amount(data["income_total"]) == Decimal("110")
    assert _amount(data["expense_total"]) == Decimal("40")
    assert _amount(data["net_total"]) == Decimal("70")

    monthly = await _statistics(
        db_client,
        household_headers,
        "cashflow",
        "start_date=2026-07-01&end_date=2026-08-31&granularity=month",
    )
    assert [item["period"] for item in monthly["items"]] == ["2026-07", "2026-08"]
    assert _amount(monthly["items"][1]["cumulative_net"]) == Decimal("70")


async def test_statistics_are_household_scoped(
    db_client: AsyncClient,
    household_headers: dict[str, str],
    auth_for_household: Any,
    create_household: Any,
):
    account = await _create_account(db_client, household_headers)
    await _create_transaction(
        db_client,
        household_headers,
        account_id=account["id"],
        transaction_type="income",
        amount="10",
        transaction_date="2026-06-10T09:00:00+08:00",
        status="confirmed",
    )

    second_id = await create_household()
    second_headers = await auth_for_household(second_id)
    other_account = await _create_account(db_client, second_headers, name="别人的账户")
    await _create_transaction(
        db_client,
        second_headers,
        account_id=other_account["id"],
        transaction_type="income",
        amount="99",
        transaction_date="2026-06-10T09:00:00+08:00",
        status="confirmed",
    )

    first = await _statistics(
        db_client,
        household_headers,
        "income-expense",
        "start_date=2026-06-01&end_date=2026-06-30",
    )
    assert _amount(first["income"]) == Decimal("10")

    second_data = await _statistics(
        db_client,
        second_headers,
        "income-expense",
        "start_date=2026-06-01&end_date=2026-06-30",
    )
    assert _amount(second_data["income"]) == Decimal("99")


async def test_overview_combines_income_expense_and_per_currency_assets(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    cny_account = await _create_account(db_client, household_headers, name="人民币账户")
    usd_account = await _create_account(
        db_client, household_headers, name="美元账户", currency="USD"
    )
    await _set_opening(db_client, household_headers, cny_account["id"], "1000")
    await _set_opening(db_client, household_headers, usd_account["id"], "100", exchange_rate="7.10")

    await _create_transaction(
        db_client,
        household_headers,
        account_id=cny_account["id"],
        transaction_type="income",
        amount="100",
        transaction_date="2026-06-10T09:00:00+08:00",
        status="confirmed",
    )
    await _create_transaction(
        db_client,
        household_headers,
        account_id=cny_account["id"],
        transaction_type="expense",
        amount="30",
        transaction_date="2026-06-11T09:00:00+08:00",
        status="confirmed",
    )

    data = await _statistics(
        db_client,
        household_headers,
        "overview",
        "start_date=2026-06-01&end_date=2026-06-30",
    )
    assert data["base_currency"] == "CNY"
    assert _amount(data["income"]) == Decimal("100")
    assert _amount(data["expense"]) == Decimal("30")
    assert _amount(data["net"]) == Decimal("70")
    assert data["account_count"] == 2
    assets = {item["currency"]: _amount(item["book_balance"]) for item in data["assets"]}
    assert assets == {"CNY": Decimal("1070"), "USD": Decimal("100")}
    assert "total" not in data


async def test_account_balances_per_account_and_currency_totals(
    db_client: AsyncClient,
    household_headers: dict[str, str],
    auth_for_household: Any,
    create_household: Any,
):
    account_a = await _create_account(db_client, household_headers, name="账户A")
    account_b = await _create_account(db_client, household_headers, name="账户B")
    usd_account = await _create_account(
        db_client, household_headers, name="美元账户", currency="USD"
    )
    inactive = await _create_account(db_client, household_headers, name="停用账户")
    await _set_opening(db_client, household_headers, account_a["id"], "500")
    await _set_opening(db_client, household_headers, account_b["id"], "200")
    await _set_opening(db_client, household_headers, usd_account["id"], "50", exchange_rate="7.10")
    await _set_opening(db_client, household_headers, inactive["id"], "100")
    await _create_transaction(
        db_client,
        household_headers,
        account_id=account_a["id"],
        transaction_type="income",
        amount="100",
        transaction_date="2026-06-10T09:00:00+08:00",
        status="confirmed",
    )
    deactivated = await db_client.put(
        f"/api/v1/accounts/{inactive['id']}",
        headers=household_headers,
        json={"is_active": False},
    )
    assert deactivated.status_code == 200, deactivated.text

    second_id = await create_household()
    second_headers = await auth_for_household(second_id)
    other = await _create_account(db_client, second_headers, name="别人账户")
    await _set_opening(db_client, second_headers, other["id"], "999")

    data = await _statistics(db_client, household_headers, "account-balances")
    totals = {
        item["currency"]: (_amount(item["book_balance"]), item["account_count"])
        for item in data["balances"]
    }
    assert totals == {"CNY": (Decimal("900"), 3), "USD": (Decimal("50"), 1)}

    by_id = {
        item["account_id"]: {
            line["currency"]: _amount(line["book_balance"]) for line in item["balances"]
        }
        for item in data["accounts"]
    }
    assert by_id[account_a["id"]] == {"CNY": Decimal("600")}
    assert by_id[account_b["id"]] == {"CNY": Decimal("200")}
    assert by_id[usd_account["id"]] == {"USD": Decimal("50")}
    assert by_id[inactive["id"]] == {"CNY": Decimal("100")}
    assert other["id"] not in by_id
    inactive_row = next(item for item in data["accounts"] if item["account_id"] == inactive["id"])
    assert inactive_row["is_active"] is False


async def test_balance_statistics_include_transfer_principal(
    db_client: AsyncClient,
    db_app,
    household: dict,
    household_headers: dict[str, str],
):
    account = await _create_account(db_client, household_headers, name="转出账户")
    target = await _create_account(db_client, household_headers, name="转入账户")
    await _set_opening(db_client, household_headers, account["id"], "1000")
    fee_category = await _find_category(db_client, household_headers, "金融手续费")

    async with db_app.state.db_session_factory() as session:
        transfer = Transfer(
            household_id=UUID(household["id"]),
            from_account_id=UUID(account["id"]),
            to_account_id=UUID(target["id"]),
            from_amount=Decimal("500"),
            from_currency="CNY",
            to_amount=Decimal("500"),
            to_currency="CNY",
            exchange_rate=Decimal("1"),
            fee=Decimal("5"),
            fee_currency="CNY",
            transfer_date=datetime.fromisoformat("2026-06-10T10:00:00+08:00"),
            status="confirmed",
        )
        session.add(transfer)
        await session.flush()
        session.add(
            Transaction(
                household_id=UUID(household["id"]),
                account_id=UUID(account["id"]),
                category_id=UUID(fee_category["id"]),
                transaction_type="expense",
                amount=Decimal("5"),
                currency="CNY",
                base_amount=Decimal("5"),
                base_currency="CNY",
                exchange_rate=Decimal("1"),
                exchange_rate_date=transfer.transfer_date.date(),
                transaction_date=transfer.transfer_date,
                description="Transfer fee",
                source="system",
                status="confirmed",
                transfer_id=transfer.id,
            )
        )
        await session.commit()

    balances = await _statistics(db_client, household_headers, "account-balances")
    by_id = {
        item["account_id"]: {
            line["currency"]: _amount(line["book_balance"]) for line in item["balances"]
        }
        for item in balances["accounts"]
    }
    assert by_id[account["id"]] == {"CNY": Decimal("495")}
    assert by_id[target["id"]] == {"CNY": Decimal("500")}
    assert balances["balances"] == [
        {
            "currency": "CNY",
            "book_balance": "995.00000000",
            "account_count": 2,
        }
    ]

    overview = await _statistics(
        db_client,
        household_headers,
        "overview",
        "start_date=2026-06-01&end_date=2026-06-30",
    )
    assert _amount(overview["income"]) == Decimal("0")
    assert _amount(overview["expense"]) == Decimal("5")
    assert overview["assets"] == [{"currency": "CNY", "book_balance": "995.00000000"}]


async def test_balance_statistics_are_empty_without_accounts(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    balances = await _statistics(db_client, household_headers, "account-balances")
    assert balances["balances"] == []
    assert balances["accounts"] == []

    overview = await _statistics(db_client, household_headers, "overview")
    assert overview["account_count"] == 0
    assert overview["assets"] == []
    assert _amount(overview["income"]) == Decimal("0")
    assert _amount(overview["expense"]) == Decimal("0")


async def test_invalid_ranges_and_granularity(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    inverted = await db_client.get(
        "/api/v1/statistics/income-expense?start_date=2026-02-01&end_date=2026-01-01",
        headers=household_headers,
    )
    assert inverted.status_code == 400
    assert inverted.json()["error_code"] == "INVALID_DATE_RANGE"

    too_large = await db_client.get(
        "/api/v1/statistics/cashflow?start_date=2000-01-01&end_date=2020-12-31&granularity=day",
        headers=household_headers,
    )
    assert too_large.status_code == 400
    assert too_large.json()["error_code"] == "DATE_RANGE_TOO_LARGE"

    bad_granularity = await db_client.get(
        "/api/v1/statistics/monthly?granularity=week", headers=household_headers
    )
    assert bad_granularity.status_code == 422
    assert bad_granularity.json()["error_code"] == "VALIDATION_ERROR"


async def test_openapi_documents_statistics_paths(
    db_client: AsyncClient, household_headers: dict[str, str]
):
    payload = (await db_client.get("/openapi.json")).json()
    expected = {
        "/api/v1/statistics/income-expense",
        "/api/v1/statistics/category",
        "/api/v1/statistics/monthly",
        "/api/v1/statistics/cashflow",
        "/api/v1/statistics/overview",
        "/api/v1/statistics/account-balances",
    }
    assert expected <= set(payload["paths"])
