#!/usr/bin/env python3
"""Seed the local HomeAtlas dev instance with demo accounts, investments and loans.

Everything goes through the public HTTP API, so all business rules (opening
balances, fund transfers, audit logs) run exactly like a real user's actions.

Usage:
    apps/api/.venv/bin/python scripts/seed_demo.py

Environment overrides:
    HOMEATLAS_API       default http://127.0.0.1:8000/api/v1
    HOMEATLAS_USER      default demo
    HOMEATLAS_PASSWORD  default demo12345

The script is idempotent: entities are matched by name and skipped if present.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import date
from typing import Any

API = os.environ.get("HOMEATLAS_API", "http://127.0.0.1:8000/api/v1")
USERNAME = os.environ.get("HOMEATLAS_USER", "demo")
PASSWORD = os.environ.get("HOMEATLAS_PASSWORD", "demo12345")

TODAY = date.today().isoformat()
_token: str | None = None


def call(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    auth: bool = True,
) -> Any:
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(API + path, data=body, method=method)
    request.add_header("Content-Type", "application/json")
    if auth and _token:
        request.add_header("Authorization", f"Bearer {_token}")
    try:
        with urllib.request.urlopen(request) as response:
            envelope = json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode()
        raise SystemExit(f"{method} {path} -> HTTP {error.code}: {detail}") from error
    if not envelope.get("success"):
        raise SystemExit(f"{method} {path} -> {envelope}")
    return envelope["data"]


def items(path: str) -> list[dict[str, Any]]:
    return call("GET", path).get("items", [])


def pick(name: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((row for row in rows if row.get("name") == name), None)


def login() -> None:
    global _token
    data = call(
        "POST",
        "/auth/login",
        {"username": USERNAME, "password": PASSWORD},
        auth=False,
    )
    _token = data["access_token"]
    print(f"✓ 登录成功：{USERNAME} / {PASSWORD}")


def seed_accounts() -> dict[str, str]:
    existing = {row["name"]: row["id"] for row in items("/accounts?page_size=100")}
    specs = [
        ("招商银行储蓄卡", "bank", "CNY", "招商银行", "120000", None),
        ("支付宝余额", "wallet", "CNY", "支付宝", "8000", None),
        ("微信零钱", "wallet", "CNY", "微信", "2500", None),
        ("港币储蓄", "bank", "HKD", "汇丰银行", "50000", "0.915"),
        ("美元储蓄", "bank", "USD", "汇丰银行", "25000", "7.12"),
        ("美股券商", "investment", "USD", "Interactive Brokers", "20000", "7.12"),
    ]
    for name, account_type, currency, institution, opening, rate in specs:
        if name in existing:
            account_id = existing[name]
            print(f"· 账户已存在：{name}")
        else:
            account = call(
                "POST",
                "/accounts",
                {
                    "name": name,
                    "account_type": account_type,
                    "currency": currency,
                    "institution": institution,
                },
            )
            account_id = account["id"]
            existing[name] = account_id
            print(f"✓ 账户：{name}")
        balance: dict[str, Any] = {
            "amount": opening,
            "currency": currency,
            "description": "演示期初余额",
            "transaction_date": f"{TODAY}T09:00:00",
        }
        if rate is not None:
            balance["exchange_rate"] = rate
        call("PUT", f"/accounts/{account_id}/opening-balance", balance)
        print(f"  ↳ 期初余额：{opening} {currency}")
    return existing


def seed_rates() -> None:
    existing = items("/exchange-rates?page_size=100")
    for base, quote, rate in [("USD", "CNY", "7.12"), ("HKD", "CNY", "0.915")]:
        if any(
            r["base_currency"] == base and r["quote_currency"] == quote
            for r in existing
        ):
            print(f"· 汇率已存在：{base}/{quote}")
            continue
        call(
            "POST",
            "/exchange-rates",
            {
                "base_currency": base,
                "quote_currency": quote,
                "rate": rate,
                "rate_date": TODAY,
            },
        )
        print(f"✓ 汇率：{base}/{quote} = {rate}")


def seed_tags() -> dict[str, str]:
    existing = {row["name"]: row["id"] for row in items("/investment-tags")}
    for name, color in [
        ("长期持有", "#2563EB"),
        ("稳健", "#16A34A"),
        ("高风险", "#DC2626"),
    ]:
        if name in existing:
            continue
        tag = call("POST", "/investment-tags", {"name": name, "color": color})
        existing[name] = tag["id"]
        print(f"✓ 标签：{name}")
    return existing


def seed_investments(accounts: dict[str, str], tags: dict[str, str]) -> None:
    existing = {row["name"]: row for row in items("/investments?page_size=100")}

    specs: list[dict[str, Any]] = [
        {
            "name": "贵州茅台",
            "investment_type": "stock",
            "principal": "150000",
            "current_value": "178400",
            "currency": "CNY",
            "start_date": "2023-03-15",
            "remark": "独立快照：不关联资金账户",
            "tag_ids": [tags["长期持有"], tags["高风险"]],
            "holdings": [("SH", "600519", "100", "1500")],
        },
        {
            "name": "腾讯控股",
            "investment_type": "stock",
            "principal": "80000",
            "current_value": "94500",
            "currency": "HKD",
            "start_date": "2023-08-10",
            "tag_ids": [tags["长期持有"]],
            "holdings": [("HK", "00700", "200", "350")],
        },
        {
            "name": "标普500指数基金",
            "investment_type": "fund",
            "account_id": accounts["美股券商"],
            "currency": "USD",
            "current_value": "23500",
            "start_date": "2024-01-05",
            "fund_transfer": {
                "from_account_id": accounts["美元储蓄"],
                "from_amount": "20000",
            },
            "tag_ids": [tags["长期持有"]],
            "holdings": [("US", "VOO", "40", "480")],
        },
        {
            "name": "天天盈货币基金",
            "investment_type": "daily",
            "principal": "30000",
            "current_value": "30350",
            "currency": "CNY",
            "annual_rate": "0.0185",
            "liquidity": "T0",
            "start_date": "2024-06-01",
            "tag_ids": [tags["稳健"]],
        },
        {
            "name": "三年定期存款",
            "investment_type": "fixed",
            "principal": "100000",
            "current_value": "100000",
            "currency": "CNY",
            "annual_rate": "0.028",
            "liquidity": "T3",
            "start_date": "2024-02-01",
            "end_date": "2027-02-01",
            "tag_ids": [tags["稳健"]],
        },
        {
            "name": "国债 2024",
            "investment_type": "bond",
            "principal": "50000",
            "current_value": "51800",
            "currency": "CNY",
            "annual_rate": "0.026",
            "start_date": "2024-04-10",
            "end_date": "2029-04-10",
            "tag_ids": [tags["稳健"]],
        },
    ]

    for spec in specs:
        holdings = spec.pop("holdings", [])
        name = spec["name"]
        if name in existing:
            investment = existing[name]
            print(f"· 投资已存在：{name}")
        else:
            investment = call("POST", "/investments", spec)
            existing[name] = investment
            print(f"✓ 投资：{name}（{investment['currency']}）")

        current_holdings = items(f"/investments/{investment['id']}/holdings")
        if holdings and not current_holdings:
            for market, symbol, quantity, cost_price in holdings:
                call(
                    "POST",
                    f"/investments/{investment['id']}/holdings",
                    {
                        "market": market,
                        "symbol": symbol,
                        "quantity": quantity,
                        "cost_price": cost_price,
                    },
                )
            print(f"  ↳ 持股：{', '.join(h[0] + ':' + h[1] for h in holdings)}")


def seed_loans() -> None:
    existing = {row["name"]: row for row in items("/loans?page_size=100")}
    specs = [
        {
            "name": "招商银行房贷",
            "institution": "建设银行",
            "principal": "2000000",
            "remaining_principal": "1520000",
            "currency": "CNY",
            "annual_rate": "0.039",
            "start_date": "2020-06-18",
            "end_date": "2050-06-18",
            "due_day": 20,
            "repayment_type": "monthly_interest",
            "remark": "等额本息演示：剩余本金手动维护",
        },
        {
            "name": "招行消费贷",
            "institution": "招商银行",
            "principal": "80000",
            "remaining_principal": "62000",
            "currency": "CNY",
            "annual_rate": "0.058",
            "start_date": "2025-01-10",
            "end_date": "2027-01-10",
            "due_day": 10,
            "repayment_type": "monthly_interest",
        },
        {
            "name": "已结清车贷",
            "institution": "平安银行",
            "principal": "180000",
            "remaining_principal": "45000",
            "currency": "CNY",
            "annual_rate": "0.048",
            "start_date": "2022-05-01",
            "end_date": "2027-05-01",
            "due_day": 5,
            "repayment_type": "monthly_interest",
        },
    ]
    for spec in specs:
        name = spec["name"]
        if name in existing:
            print(f"· 贷款已存在：{name}")
            continue
        loan = call("POST", "/loans", spec)
        print(f"✓ 贷款：{name}（剩余 {loan['remaining_principal']}）")
        if name == "已结清车贷":
            call("POST", f"/loans/{loan['id']}/settle", {"settled_date": TODAY})
            print("  ↳ 已标记结清")


def main() -> None:
    login()
    seed_rates()
    accounts = seed_accounts()
    tags = seed_tags()
    seed_investments(accounts, tags)
    seed_loans()
    snapshot = call("POST", "/assets/snapshots")
    print(
        "✓ 今日净资产快照："
        f"{snapshot['net_worth']} {snapshot['base_currency']}"
        f"（现金 {snapshot['total_cash']} / 投资 {snapshot['total_invested']}"
        f" / 负债 {snapshot['total_liabilities']}）"
    )
    print(
        "\n完成。打开 http://127.0.0.1:5180 用 demo / demo12345 登录查看「资产负债」。\n"
    )


if __name__ == "__main__":
    main()
