"""CSV/XLSX import: upload, mapping, preview, dedupe, bulk edits, confirm (2B-1/2B-3)."""

import asyncio
import io
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from httpx import AsyncClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import select

from app.core.config import get_settings
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
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["data"]["items"] if item["name"] == name)


async def _create_category(
    client: AsyncClient, headers: dict[str, str], name: str, category_type: str
) -> dict:
    response = await client.post(
        "/api/v1/categories",
        headers=headers,
        json={"name": name, "category_type": category_type},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _upload(
    client: AsyncClient,
    headers: dict[str, str],
    text: str | None = None,
    *,
    content: bytes | None = None,
    filename: str = "import.csv",
    account_id: str | None = None,
    source_format: str | None = "csv",
    allow_duplicate_file: bool | None = None,
) -> Any:
    data = content if content is not None else (text or "").encode("utf-8")
    form: dict[str, str] = {}
    if source_format is not None:
        form["source_format"] = source_format
    if account_id is not None:
        form["account_id"] = account_id
    if allow_duplicate_file is not None:
        form["allow_duplicate_file"] = str(allow_duplicate_file).lower()
    return await client.post(
        "/api/v1/imports",
        headers=headers,
        files={"file": (filename, data, "text/csv")},
        data=form,
    )


async def _mapping(
    client: AsyncClient,
    headers: dict[str, str],
    batch_id: str,
    columns: dict[str, str],
    *,
    amount_mode: str = "signed_positive_income",
    **extra: object,
) -> Any:
    return await client.put(
        f"/api/v1/imports/{batch_id}/mapping",
        headers=headers,
        json={"columns": columns, "amount_mode": amount_mode, **extra},
    )


async def _preview(client: AsyncClient, headers: dict[str, str], batch_id: str) -> Any:
    return await client.post(f"/api/v1/imports/{batch_id}/preview", headers=headers)


async def _confirm(
    client: AsyncClient,
    headers: dict[str, str],
    batch_id: str,
    body: dict[str, object] | None = None,
) -> Any:
    return await client.post(
        f"/api/v1/imports/{batch_id}/confirm", headers=headers, json=body or {}
    )


async def _confirmed_import(
    client: AsyncClient,
    headers: dict[str, str],
    text: str,
    columns: dict[str, str],
    *,
    account_id: str | None = None,
    amount_mode: str = "signed_positive_income",
    confirm_body: dict[str, object] | None = None,
    **extra: object,
) -> dict:
    uploaded = await _upload(client, headers, text, account_id=account_id)
    assert uploaded.status_code == 201, uploaded.text
    batch_id = uploaded.json()["data"]["id"]
    mapped = await _mapping(client, headers, batch_id, columns, amount_mode=amount_mode, **extra)
    assert mapped.status_code == 200, mapped.text
    previewed = await _preview(client, headers, batch_id)
    assert previewed.status_code == 200, previewed.text
    confirmed = await _confirm(client, headers, batch_id, confirm_body)
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()["data"]


async def _transactions(
    client: AsyncClient, headers: dict[str, str], account_id: str
) -> list[dict]:
    response = await client.get(
        f"/api/v1/transactions?account_id={account_id}&page_size=100",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["items"]


async def _book_balance(
    client: AsyncClient, headers: dict[str, str], account_id: str, currency: str = "CNY"
) -> Decimal:
    response = await client.get(f"/api/v1/accounts/{account_id}/balances", headers=headers)
    assert response.status_code == 200, response.text
    line = next(
        item for item in response.json()["data"]["balances"] if item["currency"] == currency
    )
    return Decimal(line["book_balance"])


async def _rows_by_number(response: dict) -> dict[int, dict]:
    return {item["row_number"]: item for item in response["data"]["preview"]}


def _remove_import_file(batch_id: str) -> None:
    Path(get_settings().import_storage_dir, f"{batch_id}.csv").unlink()


def _xlsx_bytes(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


async def test_full_flow_upload_map_preview_confirm(
    db_client: AsyncClient, db_app: Any, household_headers: dict[str, str]
) -> None:
    account = await _create_account(db_client, household_headers)
    await _set_opening(db_client, household_headers, account["id"], "1000")
    csv_text = (
        "日期,金额,收/支,备注,分类,币种,汇率,流水号\n"
        "2026-06-01,100.00,收入,工资,工资,CNY,,inc-1\n"
        "2026-06-02,-30.00,支出,午餐,餐饮,CNY,,exp-1\n"
    )

    uploaded = await _upload(db_client, household_headers, csv_text, account_id=account["id"])
    assert uploaded.status_code == 201, uploaded.text
    batch = uploaded.json()["data"]
    assert batch["status"] == "uploaded"
    assert batch["source_format"] == "csv"
    assert batch["original_filename"] == "import.csv"
    assert batch["columns"] == ["日期", "金额", "收/支", "备注", "分类", "币种", "汇率", "流水号"]
    assert batch["total_rows"] == 2
    assert batch["sample_rows"] == []

    detail = await db_client.get(f"/api/v1/imports/{batch['id']}", headers=household_headers)
    assert detail.status_code == 200, detail.text
    assert len(detail.json()["data"]["sample_rows"]) == 2

    columns = {
        "transaction_date": "日期",
        "amount": "金额",
        "description": "备注",
        "category": "分类",
        "currency": "币种",
        "exchange_rate": "汇率",
        "external_id": "流水号",
    }
    mapped = await _mapping(db_client, household_headers, batch["id"], columns)
    assert mapped.status_code == 200, mapped.text
    mapped_batch = mapped.json()["data"]
    assert mapped_batch["status"] == "mapped"
    assert mapped_batch["mapping_version"] == 1
    assert mapped_batch["mapping"]["amount_mode"] == "signed_positive_income"

    previewed = await _preview(db_client, household_headers, batch["id"])
    assert previewed.status_code == 200, previewed.text
    preview = previewed.json()["data"]
    assert preview["status"] == "previewed"
    assert preview["total_rows"] == 2
    assert preview["valid_rows"] == 2
    assert preview["invalid_rows"] == 0
    assert preview["duplicate_rows"] == 0
    rows = await _rows_by_number(previewed.json())
    assert rows[1]["status"] == "valid"
    assert rows[1]["normalized_data"]["transaction_type"] == "income"
    assert rows[1]["normalized_data"]["amount"] == "100.00000000"
    assert rows[1]["normalized_data"]["transaction_date"].endswith("+08:00")
    assert rows[2]["normalized_data"]["transaction_type"] == "expense"

    listed_rows = await db_client.get(
        f"/api/v1/imports/{batch['id']}/rows?status=valid", headers=household_headers
    )
    assert listed_rows.status_code == 200, listed_rows.text
    assert listed_rows.json()["data"]["total"] == 2

    confirmed = await _confirm(db_client, household_headers, batch["id"])
    assert confirmed.status_code == 200, confirmed.text
    finished = confirmed.json()["data"]
    assert finished["status"] == "completed"
    assert finished["imported_rows"] == 2
    assert finished["error_code"] is None
    assert finished["confirmed_at"] is not None
    assert finished["completed_at"] is not None

    replayed = await db_client.post(
        f"/api/v1/imports/{batch['id']}/confirm", headers=household_headers
    )
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["data"]["imported_rows"] == 2

    transactions = [
        item
        for item in await _transactions(db_client, household_headers, account["id"])
        if item["source"] == "import"
    ]
    assert len(transactions) == 2
    assert {item["source"] for item in transactions} == {"import"}
    assert {item["status"] for item in transactions} == {"confirmed"}
    assert await _book_balance(db_client, household_headers, account["id"]) == Decimal("1070")

    async with db_app.state.db_session_factory() as session:
        logs = list(
            (
                await session.scalars(
                    select(AuditLog).where(AuditLog.entity_id == UUID(batch["id"]))
                )
            ).all()
        )
    actions = {log.action for log in logs}
    assert {"import.create", "import.mapping", "import.preview"} <= actions
    assert {"import.confirm", "import.execute"} <= actions
    assert all("raw_data" not in str(log.after_data or {}) for log in logs)

    paths = db_app.openapi()["paths"]
    assert "/api/v1/imports" in paths
    assert "/api/v1/imports/{batch_id}/mapping" in paths
    assert "/api/v1/imports/{batch_id}/preview" in paths
    assert "/api/v1/imports/{batch_id}/confirm" in paths
    assert "/api/v1/imports/{batch_id}/rows/{row_id}" in paths


async def test_preview_collects_row_errors_and_manual_correction(
    db_client: AsyncClient, household_headers: dict[str, str]
) -> None:
    account = await _create_account(db_client, household_headers)
    await _set_opening(db_client, household_headers, account["id"], "1000")
    salary = await _find_category(db_client, household_headers, "工资")
    dining = await _find_category(db_client, household_headers, "餐饮")
    # Same name as the seeded income category creates a genuinely ambiguous lookup.
    await _create_category(db_client, household_headers, "奖金", "income")

    appearance = "x" * 2001
    long_id = "e" * 256
    csv_text = (
        "日期,金额,分类,币种,汇率,备注,流水号\n"
        "2026-06-01,10,工资,CNY,,ok,\n"
        "not-a-date,10,工资,CNY,,,\n"
        "2026-06-01,abc,餐饮,CNY,,,\n"
        "2026-06-01,-10,工资,CNY,,,\n"
        "2026-06-01,10,不存在,CNY,,,\n"
        "2026-06-01,10,餐饮,XYZ,,,\n"
        "2026-06-01,1.234,餐饮,CNY,,,\n"
        "2026-06-01,10,餐饮,USD,,,\n"
        f"2026-06-01,10,餐饮,CNY,,{appearance},\n"
        f"2026-06-01,10,工资,CNY,,,{long_id}\n"
        "2026-06-01,10\n"
        "2026-06-01,10,奖金,CNY,,,\n"
        "2026-06-01,0,餐饮,CNY,,,\n"
    )
    uploaded = await _upload(db_client, household_headers, csv_text, account_id=account["id"])
    assert uploaded.status_code == 201, uploaded.text
    batch_id = uploaded.json()["data"]["id"]
    columns = {
        "transaction_date": "日期",
        "amount": "金额",
        "category": "分类",
        "currency": "币种",
        "exchange_rate": "汇率",
        "description": "备注",
        "external_id": "流水号",
    }
    mapped = await _mapping(db_client, household_headers, batch_id, columns)
    assert mapped.status_code == 200, mapped.text
    previewed = await _preview(db_client, household_headers, batch_id)
    assert previewed.status_code == 200, previewed.text
    data = previewed.json()["data"]
    assert data["total_rows"] == 13
    assert data["valid_rows"] == 1
    assert data["invalid_rows"] == 12
    rows = await _rows_by_number(previewed.json())

    expected = {
        2: "DATE_INVALID",
        3: "AMOUNT_INVALID",
        4: "CATEGORY_TYPE_MISMATCH",
        5: "CATEGORY_NOT_FOUND",
        6: "CURRENCY_INVALID",
        7: "AMOUNT_PRECISION",
        8: "EXCHANGE_RATE_REQUIRED",
        9: "DESCRIPTION_TOO_LONG",
        10: "EXTERNAL_ID_TOO_LONG",
        11: "ROW_SHAPE_INVALID",
        12: "CATEGORY_AMBIGUOUS",
        13: "AMOUNT_INVALID",
    }
    for row_number, code in expected.items():
        codes = {error["code"] for error in rows[row_number]["errors"]}
        assert code in codes, (row_number, codes)
        assert rows[row_number]["status"] == "invalid"

    corrected = await db_client.put(
        f"/api/v1/imports/{batch_id}/rows/{rows[2]['id']}",
        headers=household_headers,
        json={
            "normalized_data": {
                "account_id": account["id"],
                "transaction_type": "income",
                "amount": "20.00000000",
                "currency": "CNY",
                "exchange_rate": "1",
                "base_amount": "20.00000000",
                "base_currency": "CNY",
                "transaction_date": "2026-06-03T00:00:00+08:00",
                "exchange_rate_date": "2026-06-03",
                "category_id": salary["id"],
                "description": "corrected",
                "row_number": 2,
            },
            "status": "valid",
        },
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["data"]["status"] == "valid"
    assert corrected.json()["data"]["errors"] == []

    skipped = await db_client.put(
        f"/api/v1/imports/{batch_id}/rows/{rows[5]['id']}",
        headers=household_headers,
        json={"status": "skipped"},
    )
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["data"]["status"] == "skipped"

    confirmed = await _confirm(db_client, household_headers, batch_id)
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()["data"]
    assert result["status"] == "partial"
    assert result["imported_rows"] == 2
    assert result["error_code"] == "IMPORT_PARTIAL"

    transactions = [
        item
        for item in await _transactions(db_client, household_headers, account["id"])
        if item["source"] == "import"
    ]
    assert {item["description"] for item in transactions} == {"ok", "corrected"}
    assert dining["id"]


async def test_amount_modes_and_foreign_currency(
    db_client: AsyncClient, household_headers: dict[str, str]
) -> None:
    cny = await _create_account(db_client, household_headers, name="主账户")
    await _set_opening(db_client, household_headers, cny["id"], "1000")
    usd = await _create_account(db_client, household_headers, name="美元账户", currency="USD")
    await _set_opening(db_client, household_headers, usd["id"], "100", exchange_rate="7.2")

    expense_positive = await _confirmed_import(
        db_client,
        household_headers,
        "日期,金额,备注\n2026-06-01,25,pos-expense\n2026-06-02,-5,neg-income\n",
        {"transaction_date": "日期", "amount": "金额", "description": "备注"},
        account_id=cny["id"],
        amount_mode="signed_positive_expense",
    )
    assert expense_positive["status"] == "completed"
    by_description = {
        item["description"]: item
        for item in await _transactions(db_client, household_headers, cny["id"])
    }
    assert by_description["pos-expense"]["transaction_type"] == "expense"
    assert by_description["neg-income"]["transaction_type"] == "income"

    typed_upload = await _upload(
        db_client,
        household_headers,
        "日期,金额,方向,备注\n"
        "2026-06-01,10,支出,typed-expense\n"
        "2026-06-02,20,收入,typed-income\n"
        "2026-06-03,5,未知,bad-direction\n"
        "2026-06-04,-5,支出,negative-typed\n",
        account_id=cny["id"],
    )
    assert typed_upload.status_code == 201, typed_upload.text
    typed_id = typed_upload.json()["data"]["id"]
    mapped = await _mapping(
        db_client,
        household_headers,
        typed_id,
        {
            "transaction_date": "日期",
            "amount": "金额",
            "direction": "方向",
            "description": "备注",
        },
        amount_mode="type_column",
        direction_map={"支出": "expense", "收入": "income"},
    )
    assert mapped.status_code == 200, mapped.text
    typed_preview = await _preview(db_client, household_headers, typed_id)
    assert typed_preview.status_code == 200, typed_preview.text
    typed_rows = await _rows_by_number(typed_preview.json())
    assert typed_rows[3]["errors"][0]["code"] == "DIRECTION_INVALID"
    assert typed_rows[4]["errors"][0]["code"] == "AMOUNT_INVALID"
    typed_confirm = await _confirm(db_client, household_headers, typed_id)
    assert typed_confirm.status_code == 200, typed_confirm.text
    assert typed_confirm.json()["data"]["status"] == "partial"

    debit_upload = await _upload(
        db_client,
        household_headers,
        "日期,借方,贷方,备注\n"
        "2026-06-01,15,,debit-row\n"
        "2026-06-02,,25,credit-row\n"
        "2026-06-03,5,5,both-row\n"
        "2026-06-04,0,0,zero-row\n"
        "2026-06-05,-1,,negative-row\n",
        account_id=cny["id"],
    )
    assert debit_upload.status_code == 201, debit_upload.text
    debit_id = debit_upload.json()["data"]["id"]
    mapped = await _mapping(
        db_client,
        household_headers,
        debit_id,
        {
            "transaction_date": "日期",
            "debit": "借方",
            "credit": "贷方",
            "description": "备注",
        },
        amount_mode="debit_credit",
    )
    assert mapped.status_code == 200, mapped.text
    debit_preview = await _preview(db_client, household_headers, debit_id)
    assert debit_preview.status_code == 200, debit_preview.text
    assert debit_preview.json()["data"]["valid_rows"] == 2
    assert debit_preview.json()["data"]["invalid_rows"] == 3
    debit_confirm = await _confirm(db_client, household_headers, debit_id)
    assert debit_confirm.status_code == 200, debit_confirm.text
    assert debit_confirm.json()["data"]["status"] == "partial"
    by_description = {
        item["description"]: item
        for item in await _transactions(db_client, household_headers, cny["id"])
    }
    assert by_description["debit-row"]["transaction_type"] == "expense"
    assert by_description["credit-row"]["transaction_type"] == "income"

    fx = await _confirmed_import(
        db_client,
        household_headers,
        "日期,金额,币种,汇率,备注\n2026-06-01,10,USD,7.2,usd-row\n2026-06-02,20,CNY,2,cny-row\n",
        {
            "transaction_date": "日期",
            "amount": "金额",
            "currency": "币种",
            "exchange_rate": "汇率",
            "description": "备注",
        },
        account_id=usd["id"],
    )
    assert fx["status"] == "completed"
    by_description = {
        item["description"]: item
        for item in await _transactions(db_client, household_headers, usd["id"])
    }
    assert by_description["usd-row"]["currency"] == "USD"
    assert Decimal(by_description["usd-row"]["exchange_rate"]) == Decimal("7.2")
    assert Decimal(by_description["usd-row"]["base_amount"]) == Decimal("72")
    assert by_description["usd-row"]["base_currency"] == "CNY"
    assert Decimal(by_description["cny-row"]["exchange_rate"]) == Decimal("1")
    assert Decimal(by_description["cny-row"]["base_amount"]) == Decimal("20")


async def test_duplicate_detection_file_and_row_level(
    db_client: AsyncClient, household_headers: dict[str, str]
) -> None:
    account = await _create_account(db_client, household_headers)
    await _set_opening(db_client, household_headers, account["id"], "1000")
    salary = await _find_category(db_client, household_headers, "工资")
    dining = await _find_category(db_client, household_headers, "餐饮")

    existing = await db_client.post(
        "/api/v1/transactions",
        headers=household_headers,
        json={
            "account_id": account["id"],
            "category_id": salary["id"],
            "transaction_type": "income",
            "amount": "100",
            "transaction_date": "2026-06-01T08:00:00+08:00",
            "external_id": "ext-1",
            "status": "confirmed",
        },
    )
    assert existing.status_code == 201, existing.text
    fingerprint_original = await db_client.post(
        "/api/v1/transactions",
        headers=household_headers,
        json={
            "account_id": account["id"],
            "category_id": dining["id"],
            "transaction_type": "expense",
            "amount": "30",
            "transaction_date": "2026-06-02T00:00:00+08:00",
            "description": "午餐",
            "status": "confirmed",
        },
    )
    assert fingerprint_original.status_code == 201, fingerprint_original.text

    csv_text = (
        "日期,金额,分类,币种,备注,流水号\n"
        "2026-06-01,100,工资,CNY,,ext-1\n"
        "2026-06-02,-30,餐饮,CNY,午餐,\n"
        "2026-06-03,40,工资,CNY,,\n"
        "2026-06-03,40,工资,CNY,,\n"
    )
    columns = {
        "transaction_date": "日期",
        "amount": "金额",
        "category": "分类",
        "currency": "币种",
        "description": "备注",
        "external_id": "流水号",
    }
    uploaded = await _upload(db_client, household_headers, csv_text, account_id=account["id"])
    assert uploaded.status_code == 201, uploaded.text
    batch_id = uploaded.json()["data"]["id"]
    assert (await _mapping(db_client, household_headers, batch_id, columns)).status_code == 200
    previewed = await _preview(db_client, household_headers, batch_id)
    assert previewed.status_code == 200, previewed.text
    data = previewed.json()["data"]
    assert data["valid_rows"] == 1
    assert data["duplicate_rows"] == 3
    rows = await _rows_by_number(previewed.json())
    assert rows[1]["duplicate_of_transaction_id"] == existing.json()["data"]["id"]
    assert rows[2]["duplicate_of_transaction_id"] == fingerprint_original.json()["data"]["id"]
    assert rows[4]["status"] == "duplicate"
    assert rows[4]["errors"] == []

    confirmed = await _confirm(db_client, household_headers, batch_id)
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()["data"]
    assert result["status"] == "partial"
    assert result["imported_rows"] == 1
    imported = [
        item
        for item in await _transactions(db_client, household_headers, account["id"])
        if item["source"] == "import"
    ]
    assert len(imported) == 1

    duplicate_file = await _upload(db_client, household_headers, csv_text, account_id=account["id"])
    assert duplicate_file.status_code == 409
    assert duplicate_file.json()["error_code"] == "IMPORT_FILE_DUPLICATE"
    allowed_file = await _upload(
        db_client,
        household_headers,
        csv_text,
        account_id=account["id"],
        allow_duplicate_file=True,
    )
    assert allowed_file.status_code == 201, allowed_file.text
    allowed_id = allowed_file.json()["data"]["id"]
    assert (await _mapping(db_client, household_headers, allowed_id, columns)).status_code == 200
    assert (await _preview(db_client, household_headers, allowed_id)).status_code == 200
    allowed_confirm = await _confirm(
        db_client, household_headers, allowed_id, {"on_duplicate": "allow"}
    )
    assert allowed_confirm.status_code == 200, allowed_confirm.text
    assert allowed_confirm.json()["data"]["status"] == "completed"
    assert allowed_confirm.json()["data"]["imported_rows"] == 4


async def test_confirmed_expense_negative_balance_but_draft_allowed(
    db_client: AsyncClient, household_headers: dict[str, str]
) -> None:
    account = await _create_account(db_client, household_headers)
    await _set_opening(db_client, household_headers, account["id"], "10")
    csv_text = "日期,金额,备注\n2026-06-01,-100,big-expense\n"
    columns = {"transaction_date": "日期", "amount": "金额", "description": "备注"}

    uploaded = await _upload(db_client, household_headers, csv_text, account_id=account["id"])
    assert uploaded.status_code == 201, uploaded.text
    batch_id = uploaded.json()["data"]["id"]
    assert (await _mapping(db_client, household_headers, batch_id, columns)).status_code == 200
    assert (await _preview(db_client, household_headers, batch_id)).status_code == 200
    failed = await _confirm(db_client, household_headers, batch_id)
    assert failed.status_code == 200, failed.text
    result = failed.json()["data"]
    assert result["status"] == "failed"
    assert result["imported_rows"] == 0
    assert result["error_code"] == "IMPORT_FAILED"
    rows = await db_client.get(f"/api/v1/imports/{batch_id}/rows", headers=household_headers)
    assert rows.json()["data"]["items"][0]["errors"][0]["code"] == "INSUFFICIENT_BALANCE"

    draft = await _confirmed_import(
        db_client,
        household_headers,
        csv_text,
        columns,
        account_id=account["id"],
        confirm_body={"create_status": "draft"},
    )
    assert draft["status"] == "completed"
    assert draft["imported_rows"] == 1
    transactions = [
        item
        for item in await _transactions(db_client, household_headers, account["id"])
        if item["source"] == "import"
    ]
    assert [item["status"] for item in transactions] == ["draft"]
    assert await _book_balance(db_client, household_headers, account["id"]) == Decimal("10")


async def test_account_category_resolution(
    db_client: AsyncClient, household_headers: dict[str, str]
) -> None:
    account = await _create_account(db_client, household_headers, name="主账户")
    await _set_opening(db_client, household_headers, account["id"], "100")
    dining = await _find_category(db_client, household_headers, "餐饮")
    salary = await _find_category(db_client, household_headers, "工资")

    uploaded = await _upload(
        db_client,
        household_headers,
        "日期,金额,账户,分类,备注\n"
        f"2026-06-01,5,主账户,支出/餐饮,path-row\n"
        f"2026-06-02,6,{account['id']},{dining['id']},uuid-row\n"
        "2026-06-03,7,不存在账户,吃饭,unknown-account\n",
    )
    assert uploaded.status_code == 201, uploaded.text
    batch_id = uploaded.json()["data"]["id"]
    mapped = await _mapping(
        db_client,
        household_headers,
        batch_id,
        {
            "transaction_date": "日期",
            "amount": "金额",
            "account": "账户",
            "category": "分类",
            "description": "备注",
        },
        amount_mode="signed_positive_expense",
        account_map={"主账户": account["id"]},
        category_map={"吃饭": dining["id"]},
    )
    assert mapped.status_code == 200, mapped.text
    previewed = await _preview(db_client, household_headers, batch_id)
    assert previewed.status_code == 200, previewed.text
    assert previewed.json()["data"]["valid_rows"] == 2
    assert previewed.json()["data"]["invalid_rows"] == 1
    rows = await _rows_by_number(previewed.json())
    assert rows[3]["errors"][0]["code"] == "ACCOUNT_NOT_FOUND"
    assert rows[1]["normalized_data"]["category_id"] == dining["id"]
    assert rows[2]["normalized_data"]["category_id"] == dining["id"]

    default_upload = await _upload(
        db_client,
        household_headers,
        "日期,金额,备注\n2026-06-04,8,default-category\n",
        account_id=account["id"],
    )
    assert default_upload.status_code == 201, default_upload.text
    default_id = default_upload.json()["data"]["id"]
    mapped = await _mapping(
        db_client,
        household_headers,
        default_id,
        {"transaction_date": "日期", "amount": "金额", "description": "备注"},
        default_category_id=salary["id"],
    )
    assert mapped.status_code == 200, mapped.text
    previewed = await _preview(db_client, household_headers, default_id)
    assert previewed.status_code == 200, previewed.text
    assert previewed.json()["data"]["preview"][0]["normalized_data"]["category_id"] == salary["id"]


async def test_mapping_validation_and_state_machine(
    db_client: AsyncClient, household_headers: dict[str, str]
) -> None:
    account = await _create_account(db_client, household_headers)
    salary = await _find_category(db_client, household_headers, "工资")
    csv_text = "日期,金额,备注\n2026-06-01,10,row\n"
    columns = {"transaction_date": "日期", "amount": "金额", "description": "备注"}

    uploaded = await _upload(db_client, household_headers, csv_text, account_id=account["id"])
    assert uploaded.status_code == 201, uploaded.text
    batch_id = uploaded.json()["data"]["id"]

    unmapped_preview = await _preview(db_client, household_headers, batch_id)
    assert unmapped_preview.status_code == 400
    assert unmapped_preview.json()["error_code"] == "IMPORT_MAPPING_INVALID"

    missing_amount = await _mapping(
        db_client, household_headers, batch_id, {"transaction_date": "日期"}
    )
    assert missing_amount.status_code == 400
    assert missing_amount.json()["error_code"] == "IMPORT_MAPPING_INVALID"

    bad_column = await _mapping(
        db_client,
        household_headers,
        batch_id,
        {"transaction_date": "日期", "amount": "不存在的列"},
    )
    assert bad_column.status_code == 400
    assert bad_column.json()["error_code"] == "IMPORT_MAPPING_INVALID"

    bad_format = await _mapping(
        db_client,
        household_headers,
        batch_id,
        columns,
        date_formats=["%Q"],
    )
    assert bad_format.status_code == 400
    assert bad_format.json()["error_code"] == "IMPORT_MAPPING_INVALID"

    typed_without_map = await _mapping(
        db_client,
        household_headers,
        batch_id,
        {**columns, "direction": "备注"},
        amount_mode="type_column",
    )
    assert typed_without_map.status_code == 400
    assert typed_without_map.json()["error_code"] == "IMPORT_MAPPING_INVALID"

    invalid_delimiter = await _mapping(
        db_client, household_headers, batch_id, columns, delimiter="^"
    )
    assert invalid_delimiter.status_code == 422
    invalid_encoding = await _mapping(
        db_client, household_headers, batch_id, columns, encoding="latin-1"
    )
    assert invalid_encoding.status_code == 422
    invalid_direction = await _mapping(
        db_client,
        household_headers,
        batch_id,
        columns,
        direction_map={"收入": "sideways"},
    )
    assert invalid_direction.status_code == 422

    assert (await _mapping(db_client, household_headers, batch_id, columns)).status_code == 200
    header_too_high = await _mapping(db_client, household_headers, batch_id, columns, header_row=5)
    assert header_too_high.status_code == 200
    preview_too_high = await _preview(db_client, household_headers, batch_id)
    assert preview_too_high.status_code == 400
    assert preview_too_high.json()["error_code"] == "IMPORT_HEADER_INVALID"
    assert (await _mapping(db_client, household_headers, batch_id, columns)).status_code == 200

    gb_upload = await _upload(
        db_client,
        household_headers,
        content="日期,金额,备注\n2026-06-01,10,编码\n".encode("gb18030"),
        account_id=account["id"],
    )
    assert gb_upload.status_code == 201, gb_upload.text
    gb_id = gb_upload.json()["data"]["id"]
    gb_mapping = await _mapping(db_client, household_headers, gb_id, columns, encoding="utf-8")
    assert gb_mapping.status_code == 200
    gb_preview = await _preview(db_client, household_headers, gb_id)
    assert gb_preview.status_code == 400
    assert gb_preview.json()["error_code"] == "IMPORT_ENCODING_UNSUPPORTED"

    missing_file_upload = await _upload(
        db_client, household_headers, csv_text, account_id=account["id"]
    )
    missing_id = missing_file_upload.json()["data"]["id"]
    await asyncio.to_thread(_remove_import_file, missing_id)
    assert (await _mapping(db_client, household_headers, missing_id, columns)).status_code == 200
    missing_preview = await _preview(db_client, household_headers, missing_id)
    assert missing_preview.status_code == 409
    assert missing_preview.json()["error_code"] == "IMPORT_FILE_MISSING"

    assert (await _mapping(db_client, household_headers, batch_id, columns)).status_code == 200
    cancelled = await db_client.post(
        f"/api/v1/imports/{batch_id}/cancel", headers=household_headers
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"]["status"] == "cancelled"
    blocked = await _mapping(db_client, household_headers, batch_id, columns)
    assert blocked.status_code == 409
    assert blocked.json()["error_code"] == "IMPORT_STATE_INVALID"
    confirm_blocked = await _confirm(db_client, household_headers, batch_id)
    assert confirm_blocked.status_code == 409
    deleted = await db_client.delete(f"/api/v1/imports/{batch_id}", headers=household_headers)
    assert deleted.status_code == 200, deleted.text
    gone = await db_client.get(f"/api/v1/imports/{batch_id}", headers=household_headers)
    assert gone.status_code == 404
    assert gone.json()["error_code"] == "IMPORT_NOT_FOUND"

    completed = await _confirmed_import(
        db_client, household_headers, csv_text, columns, account_id=account["id"]
    )
    not_deletable = await db_client.delete(
        f"/api/v1/imports/{completed['id']}", headers=household_headers
    )
    assert not_deletable.status_code == 409
    assert not_deletable.json()["error_code"] == "IMPORT_STATE_INVALID"

    assert salary["id"]


async def test_file_validation_limits(
    db_client: AsyncClient,
    household_headers: dict[str, str],
    monkeypatch: Any,
) -> None:
    account = await _create_account(db_client, household_headers)

    empty = await _upload(db_client, household_headers, "", account_id=account["id"])
    assert empty.status_code == 400
    assert empty.json()["error_code"] == "IMPORT_HEADER_INVALID"

    unsupported = await _upload(
        db_client,
        household_headers,
        content=b"PK\x03\x04",
        filename="book.xlsx",
        account_id=account["id"],
    )
    assert unsupported.status_code == 415
    assert unsupported.json()["error_code"] == "IMPORT_FILE_TYPE_UNSUPPORTED"

    unsupported_format = await _upload(
        db_client,
        household_headers,
        "日期,金额\n2026-06-01,1\n",
        source_format="xlsx",
        account_id=account["id"],
    )
    assert unsupported_format.status_code == 415
    assert unsupported_format.json()["error_code"] == "IMPORT_FILE_TYPE_UNSUPPORTED"

    invalid_header = await _upload(
        db_client, household_headers, "日期,,金额\n2026-06-01,1\n", account_id=account["id"]
    )
    assert invalid_header.status_code == 400
    assert invalid_header.json()["error_code"] == "IMPORT_HEADER_INVALID"

    monkeypatch.setenv("IMPORT_MAX_FILE_MB", "0")
    get_settings.cache_clear()
    too_large = await _upload(
        db_client, household_headers, "日期,金额\n2026-06-01,1\n", account_id=account["id"]
    )
    assert too_large.status_code == 413
    assert too_large.json()["error_code"] == "IMPORT_FILE_TOO_LARGE"

    monkeypatch.setenv("IMPORT_MAX_FILE_MB", "10")
    monkeypatch.setenv("IMPORT_MAX_ROWS", "2")
    get_settings.cache_clear()
    too_many = await _upload(
        db_client,
        household_headers,
        "日期,金额\n2026-06-01,1\n2026-06-02,2\n2026-06-03,3\n",
        account_id=account["id"],
    )
    assert too_many.status_code == 400
    assert too_many.json()["error_code"] == "IMPORT_TOO_MANY_ROWS"


async def test_household_isolation_listing_and_account_scope(
    db_client: AsyncClient, household_headers: dict[str, str], household: dict
) -> None:
    account = await _create_account(db_client, household_headers)
    other = await db_client.post(
        "/api/v1/households", json={"name": "另一个家庭", "base_currency": "CNY"}
    )
    assert other.status_code == 201, other.text
    other_household = other.json()["data"]
    other_headers = {"X-Household-Id": other_household["id"]}
    other_account = await _create_account(db_client, other_headers, name="外部账户")

    uploaded = await _upload(
        db_client,
        household_headers,
        "日期,金额,备注\n2026-06-01,10,row\n",
        account_id=account["id"],
    )
    assert uploaded.status_code == 201, uploaded.text
    batch_id = uploaded.json()["data"]["id"]

    scoped = [
        ("get", f"/api/v1/imports/{batch_id}"),
        ("get", f"/api/v1/imports/{batch_id}/rows"),
        ("post", f"/api/v1/imports/{batch_id}/preview"),
        ("post", f"/api/v1/imports/{batch_id}/confirm"),
        ("post", f"/api/v1/imports/{batch_id}/cancel"),
        ("delete", f"/api/v1/imports/{batch_id}"),
    ]
    for method, path in scoped:
        response = await getattr(db_client, method)(path, headers=other_headers)
        assert response.status_code == 404, (path, response.text)
        assert response.json()["error_code"] == "IMPORT_NOT_FOUND"

    mapping = await _mapping(
        db_client,
        other_headers,
        batch_id,
        {"transaction_date": "日期", "amount": "金额"},
    )
    assert mapping.status_code == 404
    assert mapping.json()["error_code"] == "IMPORT_NOT_FOUND"

    own_list = await db_client.get("/api/v1/imports", headers=household_headers)
    assert own_list.status_code == 200, own_list.text
    assert own_list.json()["data"]["total"] == 1
    other_list = await db_client.get("/api/v1/imports", headers=other_headers)
    assert other_list.json()["data"]["total"] == 0
    filtered = await db_client.get("/api/v1/imports?status=completed", headers=household_headers)
    assert filtered.json()["data"]["total"] == 0
    bad_sort = await db_client.get("/api/v1/imports?sort_by=bogus", headers=household_headers)
    assert bad_sort.status_code == 400
    assert bad_sort.json()["error_code"] == "INVALID_SORT_FIELD"
    bad_row_status = await db_client.get(
        f"/api/v1/imports/{batch_id}/rows?status=bogus", headers=household_headers
    )
    assert bad_row_status.status_code == 400
    assert bad_row_status.json()["error_code"] == "INVALID_ROW_STATUS"

    foreign_account = await _upload(
        db_client,
        household_headers,
        "日期,金额\n2026-06-01,1\n",
        account_id=other_account["id"],
    )
    assert foreign_account.status_code == 400
    assert foreign_account.json()["error_code"] == "IMPORT_ACCOUNT_INVALID"

    no_account = await _upload(db_client, household_headers, "日期,金额\n2026-06-01,1\n")
    no_account_id = no_account.json()["data"]["id"]
    assert (
        await _mapping(
            db_client,
            household_headers,
            no_account_id,
            {"transaction_date": "日期", "amount": "金额"},
        )
    ).status_code == 200
    no_account_preview = await _preview(db_client, household_headers, no_account_id)
    assert no_account_preview.status_code == 400
    assert no_account_preview.json()["error_code"] == "IMPORT_ACCOUNT_INVALID"

    foreign_map_upload = await _upload(
        db_client,
        household_headers,
        "日期,金额,账户\n2026-06-01,1,外部\n",
        account_id=account["id"],
    )
    foreign_map_id = foreign_map_upload.json()["data"]["id"]
    assert (
        await _mapping(
            db_client,
            household_headers,
            foreign_map_id,
            {"transaction_date": "日期", "amount": "金额", "account": "账户"},
            account_map={"外部": other_account["id"]},
        )
    ).status_code == 200
    foreign_map_preview = await _preview(db_client, household_headers, foreign_map_id)
    assert foreign_map_preview.status_code == 400
    assert foreign_map_preview.json()["error_code"] == "IMPORT_ACCOUNT_INVALID"

    inactive = await _create_account(db_client, household_headers, name="停用账户")
    updated = await db_client.put(
        f"/api/v1/accounts/{inactive['id']}",
        headers=household_headers,
        json={"is_active": False},
    )
    assert updated.status_code == 200, updated.text
    inactive_upload = await _upload(
        db_client,
        household_headers,
        "日期,金额\n2026-06-01,1\n",
        account_id=inactive["id"],
    )
    assert inactive_upload.status_code == 409
    assert inactive_upload.json()["error_code"] == "ACCOUNT_INACTIVE"

    unknown_row = await db_client.put(
        f"/api/v1/imports/{batch_id}/rows/00000000-0000-0000-0000-000000000099",
        headers=household_headers,
        json={"status": "valid"},
    )
    assert unknown_row.status_code == 404
    assert unknown_row.json()["error_code"] == "IMPORT_ROW_NOT_FOUND"
    assert household["id"]


async def test_xlsx_upload_preview_confirm(
    db_client: AsyncClient, household_headers: dict[str, str]
) -> None:
    account = await _create_account(db_client, household_headers)
    await _set_opening(db_client, household_headers, account["id"], "1000")
    content = _xlsx_bytes(
        [
            ["日期", "金额", "备注", "分类", "币种", "流水号"],
            [datetime(2026, 6, 1), 100.5, "xlsx-income", "工资", "CNY", "xlsx-1"],
            ["2026-06-02", -20, "xlsx-expense", "餐饮", "CNY", "xlsx-2"],
        ]
    )
    uploaded = await _upload(
        db_client,
        household_headers,
        content=content,
        filename="book.xlsx",
        source_format=None,
        account_id=account["id"],
    )
    assert uploaded.status_code == 201, uploaded.text
    batch = uploaded.json()["data"]
    assert batch["source_format"] == "xlsx"
    assert batch["columns"] == ["日期", "金额", "备注", "分类", "币种", "流水号"]
    assert batch["total_rows"] == 2

    columns = {
        "transaction_date": "日期",
        "amount": "金额",
        "description": "备注",
        "category": "分类",
        "currency": "币种",
        "external_id": "流水号",
    }
    mapped = await _mapping(db_client, household_headers, batch["id"], columns)
    assert mapped.status_code == 200, mapped.text
    previewed = await _preview(db_client, household_headers, batch["id"])
    assert previewed.status_code == 200, previewed.text
    data = previewed.json()["data"]
    assert data["valid_rows"] == 2
    assert data["invalid_rows"] == 0
    rows = await _rows_by_number(previewed.json())
    assert rows[1]["normalized_data"]["amount"] == "100.50000000"
    assert rows[1]["normalized_data"]["transaction_date"].startswith("2026-06-01")
    assert rows[2]["normalized_data"]["transaction_type"] == "expense"

    confirmed = await _confirm(db_client, household_headers, batch["id"])
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["status"] == "completed"
    imported = [
        item
        for item in await _transactions(db_client, household_headers, account["id"])
        if item["source"] == "import"
    ]
    assert len(imported) == 2
    assert {item["description"] for item in imported} == {"xlsx-income", "xlsx-expense"}


async def test_template_download_csv_and_xlsx(db_client: AsyncClient) -> None:
    csv_response = await db_client.get("/api/v1/imports/template?format=csv")
    assert csv_response.status_code == 200, csv_response.text
    assert "text/csv" in csv_response.headers["content-type"]
    assert "attachment" in csv_response.headers["content-disposition"]
    csv_text = csv_response.content.decode("utf-8-sig")
    assert csv_text.splitlines()[0] == ",".join(
        [
            "交易日期",
            "金额",
            "收支方向",
            "借方",
            "贷方",
            "备注",
            "分类",
            "币种",
            "汇率",
            "外部流水号",
            "账户",
        ]
    )
    assert len(csv_text.splitlines()) == 3

    xlsx_response = await db_client.get("/api/v1/imports/template?format=xlsx")
    assert xlsx_response.status_code == 200, xlsx_response.text
    assert "spreadsheetml" in xlsx_response.headers["content-type"]
    workbook = load_workbook(io.BytesIO(xlsx_response.content), read_only=True)
    try:
        sheet = workbook.worksheets[0]
        values = list(sheet.iter_rows(values_only=True))
    finally:
        workbook.close()
    assert values[0][0] == "交易日期"
    assert values[1][0] == "2026-06-01"
    assert len(values) == 3

    invalid = await db_client.get("/api/v1/imports/template?format=pdf")
    assert invalid.status_code == 422


async def test_fuzzy_duplicate_detection_opt_in(
    db_client: AsyncClient, household_headers: dict[str, str]
) -> None:
    account = await _create_account(db_client, household_headers)
    await _set_opening(db_client, household_headers, account["id"], "1000")
    dining = await _find_category(db_client, household_headers, "餐饮")
    existing = await db_client.post(
        "/api/v1/transactions",
        headers=household_headers,
        json={
            "account_id": account["id"],
            "category_id": dining["id"],
            "transaction_type": "expense",
            "amount": "100",
            "transaction_date": "2026-06-01T08:00:00+08:00",
            "description": "午餐费用",
            "status": "confirmed",
        },
    )
    assert existing.status_code == 201, existing.text

    csv_text = "日期,金额,备注\n2026-06-02,-100,午餐费\n2026-06-06,-100,午餐费用\n"
    columns = {
        "transaction_date": "日期",
        "amount": "金额",
        "description": "备注",
    }
    uploaded = await _upload(db_client, household_headers, csv_text, account_id=account["id"])
    assert uploaded.status_code == 201, uploaded.text
    batch_id = uploaded.json()["data"]["id"]
    assert (await _mapping(db_client, household_headers, batch_id, columns)).status_code == 200
    plain = await _preview(db_client, household_headers, batch_id)
    assert plain.status_code == 200, plain.text
    assert plain.json()["data"]["valid_rows"] == 2
    assert plain.json()["data"]["duplicate_rows"] == 0

    fuzzy = await _mapping(
        db_client,
        household_headers,
        batch_id,
        columns,
        fuzzy_dedupe=True,
        fuzzy_threshold=0.85,
        fuzzy_date_window_days=1,
    )
    assert fuzzy.status_code == 200, fuzzy.text
    previewed = await _preview(db_client, household_headers, batch_id)
    assert previewed.status_code == 200, previewed.text
    data = previewed.json()["data"]
    assert data["valid_rows"] == 1
    assert data["duplicate_rows"] == 1
    rows = await _rows_by_number(previewed.json())
    assert rows[1]["status"] == "duplicate"
    assert rows[1]["duplicate_of_transaction_id"] == existing.json()["data"]["id"]
    assert rows[1]["errors"][0]["code"] == "DUPLICATE_FUZZY"
    assert rows[2]["status"] == "valid"

    confirmed = await _confirm(db_client, household_headers, batch_id)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["status"] == "partial"
    assert confirmed.json()["data"]["imported_rows"] == 1


async def test_bulk_row_update_and_skip(
    db_client: AsyncClient,
    db_app: Any,
    household_headers: dict[str, str],
) -> None:
    account = await _create_account(db_client, household_headers)
    await _set_opening(db_client, household_headers, account["id"], "1000")
    salary = await _find_category(db_client, household_headers, "工资")
    csv_text = "日期,金额,备注\nbad-date,10,broken-1\n2026-06-02,10,good\nbad-date,20,broken-2\n"
    uploaded = await _upload(db_client, household_headers, csv_text, account_id=account["id"])
    assert uploaded.status_code == 201, uploaded.text
    batch_id = uploaded.json()["data"]["id"]
    columns = {"transaction_date": "日期", "amount": "金额", "description": "备注"}
    assert (await _mapping(db_client, household_headers, batch_id, columns)).status_code == 200
    previewed = await _preview(db_client, household_headers, batch_id)
    assert previewed.status_code == 200, previewed.text
    assert previewed.json()["data"]["valid_rows"] == 1
    assert previewed.json()["data"]["invalid_rows"] == 2
    rows = await _rows_by_number(previewed.json())

    skipped = await db_client.post(
        f"/api/v1/imports/{batch_id}/rows/skip",
        headers=household_headers,
        json={"scope": "invalid"},
    )
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["data"]["skipped_rows"] == 2
    assert skipped.json()["data"]["batch"]["invalid_rows"] == 0

    bulk = await db_client.put(
        f"/api/v1/imports/{batch_id}/rows",
        headers=household_headers,
        json={
            "updates": [
                {
                    "row_id": rows[1]["id"],
                    "status": "valid",
                    "normalized_data": {
                        "account_id": account["id"],
                        "transaction_type": "income",
                        "amount": "20.00000000",
                        "currency": "CNY",
                        "exchange_rate": "1",
                        "base_amount": "20.00000000",
                        "base_currency": "CNY",
                        "transaction_date": "2026-06-01T00:00:00+08:00",
                        "exchange_rate_date": "2026-06-01",
                        "category_id": salary["id"],
                        "description": "bulk-fixed",
                        "row_number": 1,
                    },
                }
            ]
        },
    )
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["data"]["items"][0]["status"] == "valid"
    assert bulk.json()["data"]["batch"]["valid_rows"] == 2

    duplicate_ids = await db_client.put(
        f"/api/v1/imports/{batch_id}/rows",
        headers=household_headers,
        json={
            "updates": [
                {"row_id": rows[2]["id"], "status": "skipped"},
                {"row_id": rows[2]["id"], "status": "valid"},
            ]
        },
    )
    assert duplicate_ids.status_code == 400
    assert duplicate_ids.json()["error_code"] == "IMPORT_ROW_DUPLICATE"

    unknown = await db_client.put(
        f"/api/v1/imports/{batch_id}/rows",
        headers=household_headers,
        json={
            "updates": [
                {
                    "row_id": "00000000-0000-0000-0000-000000000099",
                    "status": "skipped",
                }
            ]
        },
    )
    assert unknown.status_code == 404
    assert unknown.json()["error_code"] == "IMPORT_ROW_NOT_FOUND"

    async with db_app.state.db_session_factory() as session:
        logs = list(
            (
                await session.scalars(select(AuditLog).where(AuditLog.entity_id == UUID(batch_id)))
            ).all()
        )
    actions = {log.action for log in logs}
    assert {"import.rows_bulk_skip", "import.rows_bulk_update"} <= actions

    confirmed = await _confirm(db_client, household_headers, batch_id)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["status"] == "partial"
    assert confirmed.json()["data"]["imported_rows"] == 2
    completed_edit = await db_client.post(
        f"/api/v1/imports/{batch_id}/rows/skip",
        headers=household_headers,
        json={"scope": "valid"},
    )
    assert completed_edit.status_code == 409
    assert completed_edit.json()["error_code"] == "IMPORT_STATE_INVALID"
