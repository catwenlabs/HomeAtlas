"""CSV import use cases (Phase 2B-1 synchronous skeleton)."""

import asyncio
import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import TransactionSource, TransactionStatus, TransactionType
from app.core.exceptions import AppError, NotFoundError
from app.core.money import quantize_amount, quantize_money
from app.core.pagination import Pagination, resolve_sort
from app.modules.accounts.models import Account
from app.modules.accounts.service import get_account_currency_balance
from app.modules.audit.service import write_audit
from app.modules.categories.models import Category
from app.modules.currencies.models import Currency
from app.modules.households.models import Household
from app.modules.imports.models import ImportBatch, ImportRow
from app.modules.imports.schemas import (
    ImportBatchRead,
    ImportConfirm,
    ImportMapping,
    ImportPreviewRead,
    ImportRowRead,
    ImportRowUpdate,
)
from app.modules.transactions.models import Transaction

EXCHANGE_RATE_PLACES = 12
MAX_COLUMNS = 100
PREVIEW_SAMPLE_ROWS = 50
SAMPLE_ROWS = 10
DEFAULT_DATE_FORMATS = (
    "%Y/%m/%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y%m%d",
)

_EDITABLE_STATES = {"uploaded", "mapped", "previewed"}
_FINISHED_STATES = {"completed", "partial"}
_ROW_STATUSES = {"pending", "valid", "invalid", "duplicate", "imported", "skipped"}

_SORTABLE = {
    "created_at": ImportBatch.created_at,
    "updated_at": ImportBatch.updated_at,
    "status": ImportBatch.status,
    "total_rows": ImportBatch.total_rows,
}


@dataclass(frozen=True)
class ParsedFile:
    headers: list[str]
    rows: list[list[str]]
    delimiter: str
    encoding: str


@dataclass(frozen=True)
class NormalizeContext:
    household: Household
    mapping: ImportMapping
    headers: list[str]
    header_index: dict[str, int]
    default_account: Account | None
    accounts_by_id: dict[UUID, Account]
    categories: list[Category]
    categories_by_id: dict[UUID, Category]
    currencies: dict[str, Currency]
    base_currency: str
    tz: ZoneInfo


def _error(code: str, field: str, message: str) -> dict[str, str]:
    return {"code": code, "field": field, "message": message}


def _batch_response(
    batch: ImportBatch, sample_rows: list[list[str]] | None = None
) -> dict[str, Any]:
    payload = ImportBatchRead.model_validate(batch).model_copy(
        update={"sample_rows": sample_rows or []}
    )
    return payload.model_dump(mode="json")


def _row_response(row: ImportRow) -> dict[str, Any]:
    return ImportRowRead.model_validate(row).model_dump(mode="json")


def _audit_data(batch: ImportBatch) -> dict[str, Any]:
    return {
        "status": batch.status,
        "source_format": batch.source_format,
        "original_filename": batch.original_filename,
        "file_sha256": batch.file_sha256,
        "total_rows": batch.total_rows,
        "valid_rows": batch.valid_rows,
        "invalid_rows": batch.invalid_rows,
        "duplicate_rows": batch.duplicate_rows,
        "imported_rows": batch.imported_rows,
        "mapping_version": batch.mapping_version,
        "error_code": batch.error_code,
    }


async def get_batch(session: AsyncSession, household_id: UUID, batch_id: UUID) -> ImportBatch:
    batch = await session.scalar(
        select(ImportBatch).where(
            ImportBatch.id == batch_id,
            ImportBatch.household_id == household_id,
        )
    )
    if batch is None:
        raise NotFoundError("Import batch not found", error_code="IMPORT_NOT_FOUND")
    return batch


async def get_row(session: AsyncSession, batch_id: UUID, row_id: UUID) -> ImportRow:
    row = await session.scalar(
        select(ImportRow).where(
            ImportRow.id == row_id,
            ImportRow.batch_id == batch_id,
        )
    )
    if row is None:
        raise NotFoundError("Import row not found", error_code="IMPORT_ROW_NOT_FOUND")
    return row


def _ensure_state(batch: ImportBatch, allowed: set[str], action: str) -> None:
    if batch.status not in allowed:
        raise AppError(
            f"Import batch cannot be {action} in status {batch.status}",
            status_code=409,
            error_code="IMPORT_STATE_INVALID",
        )


def _storage_path(batch_id: UUID) -> Path:
    return Path(get_settings().import_storage_dir) / f"{batch_id}.csv"


async def _write_file(path: Path, data: bytes) -> None:
    await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_bytes, data)


async def _read_file(path: Path) -> bytes:
    try:
        return await asyncio.to_thread(path.read_bytes)
    except FileNotFoundError as exc:
        raise AppError(
            "Import file is no longer available; upload it again",
            status_code=409,
            error_code="IMPORT_FILE_MISSING",
        ) from exc


async def _remove_file(path: Path | None) -> None:
    if path is None:
        return
    await asyncio.to_thread(path.unlink, True)


def _decode(data: bytes, encoding: str | None) -> tuple[str, str]:
    candidates = [encoding] if encoding else ["utf-8-sig", "gb18030"]
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            return data.decode(candidate), candidate
        except UnicodeDecodeError:
            continue
    raise AppError(
        "Unsupported or invalid file encoding",
        status_code=400,
        error_code="IMPORT_ENCODING_UNSUPPORTED",
    )


def _detect_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:10])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _parse_text(text: str, delimiter: str, header_row: int) -> ParsedFile:
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    raw_rows = [row for row in reader if any(cell.strip() for cell in row)]
    if len(raw_rows) < header_row:
        raise AppError(
            "The file has no usable header row",
            status_code=400,
            error_code="IMPORT_HEADER_INVALID",
        )
    headers = [cell.strip().lstrip("\ufeff") for cell in raw_rows[header_row - 1]]
    if not headers or any(not header for header in headers):
        raise AppError(
            "The header row contains empty column names",
            status_code=400,
            error_code="IMPORT_HEADER_INVALID",
        )
    if len(headers) > MAX_COLUMNS:
        raise AppError(
            f"The file contains more than {MAX_COLUMNS} columns",
            status_code=400,
            error_code="IMPORT_HEADER_INVALID",
        )
    rows = [list(row) for row in raw_rows[header_row:]]
    if len(rows) > get_settings().import_max_rows:
        raise AppError(
            f"The file contains more than {get_settings().import_max_rows} rows",
            status_code=400,
            error_code="IMPORT_TOO_MANY_ROWS",
        )
    return ParsedFile(
        headers=headers,
        rows=rows,
        delimiter=delimiter,
        encoding="",
    )


def _mapping_from_batch(batch: ImportBatch) -> ImportMapping:
    if not batch.mapping:
        raise AppError(
            "Import mapping has not been configured",
            status_code=400,
            error_code="IMPORT_MAPPING_INVALID",
        )
    try:
        return ImportMapping.model_validate(batch.mapping)
    except ValidationError as exc:
        raise AppError(
            "Import mapping is invalid",
            status_code=400,
            error_code="IMPORT_MAPPING_INVALID",
        ) from exc


def _validate_mapping(mapping: ImportMapping, headers: list[str]) -> None:
    columns = mapping.columns
    required_fields: list[str] = ["transaction_date"]
    if mapping.amount_mode == "debit_credit":
        required_fields.extend(["debit", "credit"])
    else:
        required_fields.append("amount")
    if mapping.amount_mode == "type_column":
        required_fields.append("direction")
    if mapping.amount_mode == "type_column" and not mapping.direction_map:
        raise AppError(
            "direction_map is required for amount_mode=type_column",
            status_code=400,
            error_code="IMPORT_MAPPING_INVALID",
        )
    for field in required_fields:
        if not getattr(columns, field):
            raise AppError(
                f"Mapping field {field} is required for amount_mode={mapping.amount_mode}",
                status_code=400,
                error_code="IMPORT_MAPPING_INVALID",
            )
    header_set = set(headers)
    for standard, source in columns.model_dump().items():
        if source and source not in header_set:
            raise AppError(
                f"Mapped column {source!r} for {standard} does not exist in the file",
                status_code=400,
                error_code="IMPORT_MAPPING_INVALID",
            )
    for fmt in mapping.date_formats:
        try:
            datetime.strptime("2000-01-01", fmt)
        except ValueError as exc:
            raise AppError(
                f"Invalid date format: {fmt}",
                status_code=400,
                error_code="IMPORT_MAPPING_INVALID",
            ) from exc


async def _active_account(
    session: AsyncSession, household_id: UUID, account_id: UUID | None
) -> Account | None:
    if account_id is None:
        return None
    account = await session.scalar(
        select(Account).where(
            Account.id == account_id,
            Account.household_id == household_id,
        )
    )
    if account is None:
        raise AppError(
            "Target account does not belong to this household",
            status_code=400,
            error_code="IMPORT_ACCOUNT_INVALID",
        )
    if not account.is_active:
        raise AppError(
            "Target account is inactive",
            status_code=409,
            error_code="ACCOUNT_INACTIVE",
        )
    return account


async def create_import(
    session: AsyncSession,
    household: Household,
    *,
    filename: str | None,
    data: bytes,
    source_format: str,
    account_id: UUID | None,
    allow_duplicate_file: bool,
) -> ImportBatch:
    settings = get_settings()
    if source_format != "csv":
        raise AppError(
            "Only CSV import is supported in Phase 2B-1",
            status_code=415,
            error_code="IMPORT_FILE_TYPE_UNSUPPORTED",
        )
    suffix = Path(filename or "").suffix.lower()
    if suffix and suffix not in {".csv", ".txt"}:
        raise AppError(
            "Only .csv files are supported",
            status_code=415,
            error_code="IMPORT_FILE_TYPE_UNSUPPORTED",
        )
    if len(data) > settings.import_max_file_mb * 1024 * 1024:
        raise AppError(
            f"File exceeds the {settings.import_max_file_mb} MB limit",
            status_code=413,
            error_code="IMPORT_FILE_TOO_LARGE",
        )
    if not data:
        raise AppError(
            "The uploaded file is empty",
            status_code=400,
            error_code="IMPORT_HEADER_INVALID",
        )

    text, encoding = _decode(data, None)
    delimiter = _detect_delimiter(text)
    parsed = _parse_text(text, delimiter, 1)
    sha256 = hashlib.sha256(data).hexdigest()

    if not allow_duplicate_file:
        duplicate = await session.scalar(
            select(func.count())
            .select_from(ImportBatch)
            .where(
                ImportBatch.household_id == household.id,
                ImportBatch.file_sha256 == sha256,
                ImportBatch.status.in_(tuple(_FINISHED_STATES)),
            )
        )
        if duplicate:
            raise AppError(
                "This file has already been imported",
                status_code=409,
                error_code="IMPORT_FILE_DUPLICATE",
            )

    await _active_account(session, household.id, account_id)

    batch_id = uuid4()
    path = _storage_path(batch_id)
    await _write_file(path, data)
    batch = ImportBatch(
        id=batch_id,
        household_id=household.id,
        account_id=account_id,
        status="uploaded",
        source_format=source_format,
        original_filename=filename,
        stored_path=str(path),
        file_sha256=sha256,
        file_size_bytes=len(data),
        columns=parsed.headers,
        mapping={
            "header_row": 1,
            "delimiter": delimiter,
            "encoding": encoding,
            "columns": {},
        },
        total_rows=len(parsed.rows),
    )
    session.add(batch)
    await session.flush()
    for row_number, raw in enumerate(parsed.rows, start=1):
        session.add(
            ImportRow(
                batch_id=batch.id,
                row_number=row_number,
                raw_data=raw,
                status="pending",
            )
        )
    write_audit(
        session,
        household_id=household.id,
        action="import.create",
        entity_type="import_batch",
        entity_id=batch.id,
        after=_audit_data(batch),
    )
    await session.commit()
    await session.refresh(batch)
    return batch


async def update_mapping(
    session: AsyncSession,
    household: Household,
    batch_id: UUID,
    mapping: ImportMapping,
) -> ImportBatch:
    batch = await get_batch(session, household.id, batch_id)
    _ensure_state(batch, _EDITABLE_STATES, "mapped")
    _validate_mapping(mapping, list(batch.columns))
    before = _audit_data(batch)
    batch.mapping = mapping.model_dump(mode="json")
    batch.mapping_version += 1
    batch.status = "mapped"
    batch.error_code = None
    batch.error_message = None
    write_audit(
        session,
        household_id=household.id,
        action="import.mapping",
        entity_type="import_batch",
        entity_id=batch.id,
        before=before,
        after=_audit_data(batch),
    )
    await session.commit()
    await session.refresh(batch)
    return batch


def _cell(raw: list[str], header_index: dict[str, int], column: str | None) -> str:
    if column is None:
        return ""
    index = header_index.get(column)
    if index is None or index >= len(raw):
        return ""
    return raw[index].strip()


def _parse_decimal(value: str) -> Decimal:
    cleaned = value.strip().replace(",", "").replace(" ", "")
    for symbol in ("¥", "$", "€", "£"):
        cleaned = cleaned.replace(symbol, "")
    if not cleaned:
        raise InvalidOperation
    return Decimal(cleaned)


def _parse_datetime(value: str, formats: list[str], tz: ZoneInfo) -> datetime:
    text = value.strip()
    if not text:
        raise ValueError("empty date")
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None
    if parsed is None:
        for fmt in formats or DEFAULT_DATE_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError("unrecognized date")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed


def _resolve_category(
    context: NormalizeContext, value: str, transaction_type: str, errors: list[dict[str, str]]
) -> Category | None:
    if value:
        mapped = context.mapping.category_map.get(value)
        category: Category | None = None
        if mapped is not None:
            category = context.categories_by_id.get(mapped)
        else:
            try:
                category = context.categories_by_id.get(UUID(value))
            except ValueError:
                candidate = value.rsplit("/", 1)[-1].strip()
                matches = [item for item in context.categories if item.name == candidate]
                if len(matches) > 1:
                    errors.append(
                        _error(
                            "CATEGORY_AMBIGUOUS",
                            "category",
                            f"Category {candidate!r} matches multiple categories",
                        )
                    )
                    return None
                category = matches[0] if matches else None
        if category is None:
            errors.append(_error("CATEGORY_NOT_FOUND", "category", f"Category {value!r} not found"))
            return None
    elif context.mapping.default_category_id is not None:
        category = context.categories_by_id.get(context.mapping.default_category_id)
        if category is None:
            errors.append(
                _error(
                    "CATEGORY_NOT_FOUND",
                    "category",
                    "default_category_id does not belong to this household",
                )
            )
            return None
    else:
        return None

    if not category.is_active:
        errors.append(
            _error("CATEGORY_INACTIVE", "category", f"Category {category.name!r} is inactive")
        )
        return None
    if category.category_type != transaction_type:
        errors.append(
            _error(
                "CATEGORY_TYPE_MISMATCH",
                "category",
                f"Category {category.name!r} is {category.category_type}, "
                f"row is {transaction_type}",
            )
        )
        return None
    return category


def _normalize_row(
    raw: list[str],
    row_number: int,
    context: NormalizeContext,
) -> tuple[dict[str, Any], list[dict[str, str]], datetime | None]:
    errors: list[dict[str, str]] = []
    normalized: dict[str, Any] = {}
    mapping = context.mapping
    columns = mapping.columns

    if len(raw) != len(context.headers):
        errors.append(
            _error(
                "ROW_SHAPE_INVALID",
                "row",
                f"Expected {len(context.headers)} columns, got {len(raw)}",
            )
        )
        return normalized, errors, None

    account = context.default_account
    account_value = _cell(raw, context.header_index, columns.account)
    if account_value:
        account_id = mapping.account_map.get(account_value)
        if account_id is None:
            try:
                account_id = UUID(account_value)
            except ValueError:
                account_id = None
        account = context.accounts_by_id.get(account_id) if account_id else None
        if account is None:
            errors.append(
                _error(
                    "ACCOUNT_NOT_FOUND",
                    "account",
                    f"Account {account_value!r} not found in this household",
                )
            )
    if account is None:
        errors.append(_error("ACCOUNT_NOT_FOUND", "account", "No target account resolved"))
    elif not account.is_active:
        errors.append(
            _error("ACCOUNT_INACTIVE", "account", f"Account {account.name!r} is inactive")
        )

    transaction_type: str | None = None
    amount: Decimal | None = None
    try:
        if mapping.amount_mode == "debit_credit":
            debit_value = _cell(raw, context.header_index, columns.debit)
            credit_value = _cell(raw, context.header_index, columns.credit)
            debit = _parse_decimal(debit_value) if debit_value else Decimal("0")
            credit = _parse_decimal(credit_value) if credit_value else Decimal("0")
            if debit < 0 or credit < 0 or (debit > 0 and credit > 0):
                raise InvalidOperation
            if debit > 0:
                transaction_type = TransactionType.EXPENSE.value
                amount = debit
            elif credit > 0:
                transaction_type = TransactionType.INCOME.value
                amount = credit
            else:
                raise InvalidOperation
        else:
            amount_value = _cell(raw, context.header_index, columns.amount)
            if not amount_value:
                raise InvalidOperation
            signed_amount = _parse_decimal(amount_value)
            if signed_amount == 0:
                raise InvalidOperation
            if mapping.amount_mode == "signed_positive_income":
                transaction_type = (
                    TransactionType.INCOME.value
                    if signed_amount > 0
                    else TransactionType.EXPENSE.value
                )
                amount = abs(signed_amount)
            elif mapping.amount_mode == "signed_positive_expense":
                transaction_type = (
                    TransactionType.EXPENSE.value
                    if signed_amount > 0
                    else TransactionType.INCOME.value
                )
                amount = abs(signed_amount)
            else:
                direction_value = _cell(raw, context.header_index, columns.direction)
                direction = mapping.direction_map.get(direction_value)
                if direction is None and direction_value.lower() in {"income", "expense"}:
                    direction = direction_value.lower()
                if direction is None:
                    errors.append(
                        _error(
                            "DIRECTION_INVALID",
                            "direction",
                            f"Unknown direction {direction_value!r}",
                        )
                    )
                elif signed_amount < 0:
                    raise InvalidOperation
                else:
                    transaction_type = direction
                    amount = signed_amount
    except (InvalidOperation, ValueError):
        errors.append(_error("AMOUNT_INVALID", "amount", "Invalid amount or direction"))
        amount = None

    if amount is not None and transaction_type is not None:
        currency = None
        rate = Decimal("1")
        base_amount = Decimal("0")
        try:
            currency_code = _cell(raw, context.header_index, columns.currency)
            if not currency_code and account is not None:
                currency_code = str(account.currency).strip()
            currency_code = (currency_code or context.base_currency).upper()
            currency = context.currencies.get(currency_code)
            if currency is None:
                errors.append(
                    _error(
                        "CURRENCY_INVALID",
                        "currency",
                        f"Unknown currency {currency_code!r}",
                    )
                )
            else:
                rounded = quantize_amount(amount, currency.decimal_places)
                if rounded != amount:
                    errors.append(
                        _error(
                            "AMOUNT_PRECISION",
                            "amount",
                            f"Amount exceeds {currency.decimal_places} decimal places",
                        )
                    )
                else:
                    amount = rounded

                rate_value = _cell(raw, context.header_index, columns.exchange_rate)
                rate = Decimal("1")
                if currency.code != context.base_currency:
                    if not rate_value:
                        errors.append(
                            _error(
                                "EXCHANGE_RATE_REQUIRED",
                                "exchange_rate",
                                f"exchange_rate is required for {currency.code}",
                            )
                        )
                    else:
                        try:
                            rate = _parse_decimal(rate_value)
                        except (InvalidOperation, ValueError):
                            errors.append(
                                _error(
                                    "EXCHANGE_RATE_INVALID",
                                    "exchange_rate",
                                    f"Invalid exchange rate {rate_value!r}",
                                )
                            )
                        if rate <= 0:
                            errors.append(
                                _error(
                                    "EXCHANGE_RATE_INVALID",
                                    "exchange_rate",
                                    "exchange_rate must be positive",
                                )
                            )
                rate = quantize_amount(rate, EXCHANGE_RATE_PLACES)
                base_amount = quantize_money(amount * rate)
        except (InvalidOperation, ValueError):
            errors.append(_error("AMOUNT_INVALID", "amount", "Invalid amount"))
            currency = None
            rate = Decimal("1")
            base_amount = Decimal("0")
    else:
        currency = None
        rate = Decimal("1")
        base_amount = Decimal("0")

    date_value = _cell(raw, context.header_index, columns.transaction_date)
    try:
        occurred_at = _parse_datetime(date_value, mapping.date_formats, context.tz)
    except ValueError:
        errors.append(_error("DATE_INVALID", "transaction_date", f"Invalid date {date_value!r}"))
        occurred_at = None

    category = (
        _resolve_category(
            context,
            _cell(raw, context.header_index, columns.category),
            transaction_type or "",
            errors,
        )
        if transaction_type is not None
        else None
    )
    description = _cell(raw, context.header_index, columns.description) or None
    if description is not None and len(description) > 2000:
        errors.append(
            _error("DESCRIPTION_TOO_LONG", "description", "Description exceeds 2000 chars")
        )
    external_id = _cell(raw, context.header_index, columns.external_id) or None
    if external_id is not None and len(external_id) > 255:
        errors.append(
            _error("EXTERNAL_ID_TOO_LONG", "external_id", "external_id exceeds 255 chars")
        )

    if account is not None:
        normalized["account_id"] = str(account.id)
    if transaction_type is not None:
        normalized["transaction_type"] = transaction_type
    if amount is not None:
        normalized["amount"] = format(quantize_money(amount), "f")
    if currency is not None:
        normalized["currency"] = currency.code
    normalized["exchange_rate"] = format(rate, "f")
    normalized["base_amount"] = format(base_amount, "f")
    normalized["base_currency"] = context.base_currency
    if occurred_at is not None:
        normalized["transaction_date"] = occurred_at.isoformat()
        normalized["exchange_rate_date"] = occurred_at.date().isoformat()
    if category is not None:
        normalized["category_id"] = str(category.id)
    if description is not None:
        normalized["description"] = description
    if external_id is not None:
        normalized["external_id"] = external_id
    normalized["row_number"] = row_number
    return normalized, errors, occurred_at


def _fingerprint(
    account_id: str,
    transaction_type: str,
    amount: str,
    currency: str,
    occurred_at: datetime,
    description: str | None,
) -> str:
    key = "|".join(
        [
            account_id,
            transaction_type,
            format(quantize_money(Decimal(amount)), "f"),
            currency,
            occurred_at.astimezone(UTC).replace(microsecond=0).isoformat(),
            (description or "").strip(),
        ]
    )
    return hashlib.sha256(key.encode()).hexdigest()


async def _build_context(
    session: AsyncSession, batch: ImportBatch, mapping: ImportMapping, headers: list[str]
) -> NormalizeContext:
    household = await session.get(Household, batch.household_id)
    if household is None:  # pragma: no cover - FK guarantees it
        raise NotFoundError("Household not found", error_code="HOUSEHOLD_NOT_FOUND")
    base_currency = str(household.base_currency).strip()
    default_account = await _active_account(session, household.id, batch.account_id)
    if default_account is None and not mapping.columns.account:
        raise AppError(
            "account_id is required when the file has no account column",
            status_code=400,
            error_code="IMPORT_ACCOUNT_INVALID",
        )

    accounts = list(
        (await session.scalars(select(Account).where(Account.household_id == household.id))).all()
    )
    accounts_by_id = {account.id: account for account in accounts}
    for alias, account_id in mapping.account_map.items():
        if account_id not in accounts_by_id:
            raise AppError(
                f"account_map entry {alias!r} does not belong to this household",
                status_code=400,
                error_code="IMPORT_ACCOUNT_INVALID",
            )

    categories = list(
        (await session.scalars(select(Category).where(Category.household_id == household.id))).all()
    )
    currencies = list((await session.scalars(select(Currency))).all())
    return NormalizeContext(
        household=household,
        mapping=mapping,
        headers=headers,
        header_index={header: index for index, header in enumerate(headers)},
        default_account=default_account,
        accounts_by_id=accounts_by_id,
        categories=categories,
        categories_by_id={category.id: category for category in categories},
        currencies={currency.code: currency for currency in currencies},
        base_currency=base_currency,
        tz=ZoneInfo(household.timezone),
    )


async def _mark_duplicates(
    session: AsyncSession,
    batch: ImportBatch,
    rows: list[ImportRow],
    context: NormalizeContext,
) -> None:
    candidates = [
        row for row in rows if row.status == "pending" and row.normalized_data is not None
    ]
    if not candidates:
        return
    dates = [
        datetime.fromisoformat(str(row.normalized_data["transaction_date"]))
        for row in candidates
        if row.normalized_data and row.normalized_data.get("transaction_date")
    ]
    if not dates:
        return
    start = min(dates)
    end = max(dates)

    existing = list(
        (
            await session.scalars(
                select(Transaction).where(
                    Transaction.household_id == batch.household_id,
                    Transaction.transaction_type.in_(
                        (TransactionType.INCOME.value, TransactionType.EXPENSE.value)
                    ),
                    Transaction.status.in_(
                        (TransactionStatus.DRAFT.value, TransactionStatus.CONFIRMED.value)
                    ),
                    Transaction.transfer_id.is_(None),
                    Transaction.transaction_date >= start,
                    Transaction.transaction_date <= end,
                )
            )
        ).all()
    )
    fingerprint_to_id: dict[str, UUID] = {}
    for transaction in existing:
        fingerprint = _fingerprint(
            str(transaction.account_id),
            transaction.transaction_type,
            format(transaction.amount, "f"),
            str(transaction.currency).strip(),
            transaction.transaction_date,
            transaction.description,
        )
        fingerprint_to_id.setdefault(fingerprint, transaction.id)

    account_ids = {
        UUID(str(row.normalized_data["account_id"]))
        for row in candidates
        if row.normalized_data and row.normalized_data.get("account_id")
    }
    external_ids = {
        str(row.normalized_data["external_id"])
        for row in candidates
        if row.normalized_data and row.normalized_data.get("external_id")
    }
    external_matches: dict[tuple[str, str], UUID] = {}
    if external_ids:
        external_rows = (
            await session.execute(
                select(
                    Transaction.id,
                    Transaction.account_id,
                    Transaction.external_id,
                ).where(
                    Transaction.household_id == batch.household_id,
                    Transaction.account_id.in_(account_ids),
                    Transaction.external_id.in_(external_ids),
                    Transaction.status.in_(
                        (TransactionStatus.DRAFT.value, TransactionStatus.CONFIRMED.value)
                    ),
                )
            )
        ).all()
        for txn_id, txn_account_id, txn_external_id in external_rows:
            external_matches[(str(txn_account_id), str(txn_external_id))] = txn_id

    seen_in_batch: dict[str, UUID | None] = {}
    for row in rows:
        if row.status != "pending" or row.normalized_data is None:
            continue
        normalized = row.normalized_data
        if row.errors:
            row.status = "invalid"
            continue
        account_id = str(normalized["account_id"])
        external_id = normalized.get("external_id")
        occurred_at = datetime.fromisoformat(str(normalized["transaction_date"]))
        fingerprint = _fingerprint(
            account_id,
            str(normalized["transaction_type"]),
            str(normalized["amount"]),
            str(normalized["currency"]),
            occurred_at,
            normalized.get("description"),
        )
        row.row_hash = fingerprint
        duplicate_of = None
        if external_id is not None:
            duplicate_of = external_matches.get((account_id, str(external_id)))
        if duplicate_of is None:
            duplicate_of = fingerprint_to_id.get(fingerprint)
        if duplicate_of is None and fingerprint in seen_in_batch:
            duplicate_of = seen_in_batch[fingerprint]
        if duplicate_of is not None or fingerprint in seen_in_batch:
            row.status = "duplicate"
            row.duplicate_of_transaction_id = duplicate_of
        else:
            row.status = "valid"
            seen_in_batch[fingerprint] = None


async def preview_import(
    session: AsyncSession,
    household: Household,
    batch_id: UUID,
) -> tuple[ImportBatch, list[ImportRow]]:
    batch = await get_batch(session, household.id, batch_id)
    _ensure_state(batch, _EDITABLE_STATES, "previewed")
    mapping = _mapping_from_batch(batch)
    if not batch.stored_path:
        raise AppError(
            "Import file is missing",
            status_code=409,
            error_code="IMPORT_FILE_MISSING",
        )
    data = await _read_file(Path(batch.stored_path))
    text, encoding = _decode(data, mapping.encoding)
    delimiter = mapping.delimiter or _detect_delimiter(text)
    parsed = _parse_text(text, delimiter, mapping.header_row)
    _validate_mapping(mapping, parsed.headers)

    await session.execute(delete(ImportRow).where(ImportRow.batch_id == batch.id))
    batch.columns = parsed.headers
    batch.total_rows = len(parsed.rows)
    batch.status = "mapped"
    batch.error_code = None
    batch.error_message = None
    rows: list[ImportRow] = []
    for row_number, raw in enumerate(parsed.rows, start=1):
        row = ImportRow(
            batch_id=batch.id,
            row_number=row_number,
            raw_data=raw,
            status="pending",
        )
        session.add(row)
        rows.append(row)
    await session.flush()

    context = await _build_context(session, batch, mapping, parsed.headers)
    for row in rows:
        normalized, errors, _ = _normalize_row(row.raw_data, row.row_number, context)
        row.normalized_data = normalized or None
        row.errors = errors
        if errors:
            row.status = "invalid"
        else:
            row.status = "pending"
    await session.flush()
    await _mark_duplicates(session, batch, rows, context)

    valid = sum(1 for row in rows if row.status == "valid")
    invalid = sum(1 for row in rows if row.status == "invalid")
    duplicate = sum(1 for row in rows if row.status == "duplicate")
    batch.valid_rows = valid
    batch.invalid_rows = invalid
    batch.duplicate_rows = duplicate
    batch.imported_rows = 0
    batch.status = "previewed"
    write_audit(
        session,
        household_id=household.id,
        action="import.preview",
        entity_type="import_batch",
        entity_id=batch.id,
        after=_audit_data(batch),
    )
    await session.commit()
    await session.refresh(batch)
    preview = sorted(rows, key=lambda item: item.row_number)[:PREVIEW_SAMPLE_ROWS]
    for row in preview:
        await session.refresh(row)
    return batch, preview


async def _preload_execution(
    session: AsyncSession, household_id: UUID
) -> tuple[dict[UUID, Account], dict[UUID, Category]]:
    accounts = list(
        (await session.scalars(select(Account).where(Account.household_id == household_id))).all()
    )
    categories = list(
        (await session.scalars(select(Category).where(Category.household_id == household_id))).all()
    )
    return (
        {account.id: account for account in accounts},
        {category.id: category for category in categories},
    )


async def _execute_row(
    session: AsyncSession,
    household: Household,
    row: ImportRow,
    accounts: dict[UUID, Account],
    categories: dict[UUID, Category],
    create_status: str,
) -> tuple[str, dict[str, str] | None]:
    normalized = row.normalized_data
    if not normalized:
        return "invalid", _error("IMPORT_ROW_INVALID", "row", "Row has no normalized data")
    try:
        account_id = UUID(str(normalized["account_id"]))
        account = accounts.get(account_id)
        if account is None:
            return "invalid", _error("ACCOUNT_NOT_FOUND", "account", "Account not found")
        if not account.is_active:
            return "invalid", _error("ACCOUNT_INACTIVE", "account", "Account is inactive")
        if (
            create_status == TransactionStatus.CONFIRMED.value
            and normalized["transaction_type"] == TransactionType.EXPENSE.value
        ):
            balance = await get_account_currency_balance(
                session, account.id, str(normalized["currency"])
            )
            amount = Decimal(str(normalized["amount"]))
            if balance - amount < 0:
                return "invalid", _error(
                    "INSUFFICIENT_BALANCE",
                    "amount",
                    f"Insufficient {normalized['currency']} balance",
                )
        category_id = (
            UUID(str(normalized["category_id"])) if normalized.get("category_id") else None
        )
        category = None
        if category_id is not None:
            category = categories.get(category_id)
            if category is None:
                return "invalid", _error("CATEGORY_NOT_FOUND", "category", "Category not found")
            if not category.is_active:
                return "invalid", _error("CATEGORY_INACTIVE", "category", "Category is inactive")
            if category.category_type != normalized["transaction_type"]:
                return "invalid", _error(
                    "CATEGORY_TYPE_MISMATCH", "category", "Category type mismatch"
                )
        description = normalized.get("description")
        external_id = normalized.get("external_id")
        transaction = Transaction(
            household_id=household.id,
            account_id=account.id,
            category_id=category.id if category else None,
            transaction_type=str(normalized["transaction_type"]),
            amount=Decimal(str(normalized["amount"])),
            currency=str(normalized["currency"]),
            base_amount=Decimal(str(normalized["base_amount"])),
            base_currency=str(normalized["base_currency"]),
            exchange_rate=Decimal(str(normalized["exchange_rate"])),
            exchange_rate_date=date.fromisoformat(str(normalized["exchange_rate_date"])),
            transaction_date=datetime.fromisoformat(str(normalized["transaction_date"])),
            description=str(description) if description else None,
            source=TransactionSource.IMPORT.value,
            external_id=str(external_id) if external_id else None,
            status=create_status,
        )
        session.add(transaction)
        await session.flush()
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        return "invalid", _error("IMPORT_ROW_INVALID", "row", str(exc))
    row.transaction_id = transaction.id
    return "imported", None


async def confirm_import(
    session: AsyncSession,
    household: Household,
    batch_id: UUID,
    payload: ImportConfirm,
) -> ImportBatch:
    batch = await get_batch(session, household.id, batch_id)
    if batch.status in _FINISHED_STATES:
        return batch
    if batch.status != "previewed":
        raise AppError(
            f"Import batch must be previewed before confirmation (currently {batch.status})",
            status_code=409,
            error_code="IMPORT_STATE_INVALID",
        )

    rows = list(
        (
            await session.scalars(
                select(ImportRow)
                .where(ImportRow.batch_id == batch.id)
                .order_by(ImportRow.row_number.asc())
            )
        ).all()
    )
    accounts, categories = await _preload_execution(session, household.id)
    create_status = TransactionStatus(payload.create_status).value
    before = _audit_data(batch)
    imported = 0
    invalid = 0
    for row in rows:
        if row.status == "imported":
            imported += 1
            continue
        if row.status == "invalid":
            invalid += 1
            continue
        if row.status == "skipped":
            continue
        if row.status == "duplicate" and payload.on_duplicate == "skip":
            row.status = "skipped"
            continue
        if row.status not in {"valid", "duplicate"}:
            row.status = "invalid"
            row.errors = [_error("IMPORT_ROW_INVALID", "row", "Row was not valid at preview")]
            invalid += 1
            continue
        savepoint = await session.begin_nested()
        try:
            result, error = await _execute_row(
                session, household, row, accounts, categories, create_status
            )
            if result == "imported":
                await savepoint.commit()
                row.status = "imported"
                row.errors = []
                row.duplicate_of_transaction_id = None
                imported += 1
            else:
                await savepoint.rollback()
                row.status = "invalid"
                row.errors = [error] if error else []
                invalid += 1
        except Exception:  # pragma: no cover - safety net for DB errors
            await savepoint.rollback()
            raise

    duplicate_count = batch.duplicate_rows
    batch.imported_rows = imported
    batch.invalid_rows = invalid
    batch.duplicate_rows = duplicate_count
    batch.confirmed_at = datetime.now(UTC)
    batch.completed_at = datetime.now(UTC)
    if imported == batch.total_rows:
        batch.status = "completed"
        batch.error_code = None
        batch.error_message = None
    elif imported > 0:
        batch.status = "partial"
        batch.error_code = "IMPORT_PARTIAL"
        batch.error_message = "Some rows were invalid, duplicates, or skipped"
    else:
        batch.status = "failed"
        batch.error_code = "IMPORT_FAILED"
        batch.error_message = "No rows were imported"
    write_audit(
        session,
        household_id=household.id,
        action="import.confirm",
        entity_type="import_batch",
        entity_id=batch.id,
        before=before,
        after={
            "on_duplicate": payload.on_duplicate,
            "create_status": create_status,
        },
    )
    write_audit(
        session,
        household_id=household.id,
        action="import.execute",
        entity_type="import_batch",
        entity_id=batch.id,
        after=_audit_data(batch),
    )
    await session.commit()
    await session.refresh(batch)
    return batch


async def list_imports(
    session: AsyncSession,
    household: Household,
    pagination: Pagination,
    *,
    status: str | None = None,
) -> tuple[list[ImportBatch], int]:
    filters = [ImportBatch.household_id == household.id]
    if status is not None:
        filters.append(ImportBatch.status == status)
    total = await session.scalar(select(func.count()).select_from(ImportBatch).where(*filters))
    column, descending = resolve_sort(
        pagination.sort_by, pagination.sort_order, _SORTABLE, "created_at"
    )
    stmt = (
        select(ImportBatch)
        .where(*filters)
        .order_by(column.desc() if descending else column.asc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return list((await session.scalars(stmt)).all()), int(total or 0)


async def list_rows(
    session: AsyncSession,
    household: Household,
    batch_id: UUID,
    pagination: Pagination,
    *,
    status: str | None = None,
) -> tuple[list[ImportRow], int]:
    batch = await get_batch(session, household.id, batch_id)
    filters = [ImportRow.batch_id == batch.id]
    if status is not None:
        if status not in _ROW_STATUSES:
            raise AppError(
                f"Unsupported row status: {status}",
                status_code=400,
                error_code="INVALID_ROW_STATUS",
            )
        filters.append(ImportRow.status == status)
    total = await session.scalar(select(func.count()).select_from(ImportRow).where(*filters))
    stmt = (
        select(ImportRow)
        .where(*filters)
        .order_by(ImportRow.row_number.asc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    return list((await session.scalars(stmt)).all()), int(total or 0)


async def update_row(
    session: AsyncSession,
    household: Household,
    batch_id: UUID,
    row_id: UUID,
    payload: ImportRowUpdate,
) -> ImportRow:
    batch = await get_batch(session, household.id, batch_id)
    _ensure_state(batch, _EDITABLE_STATES, "edited")
    row = await get_row(session, batch.id, row_id)
    before = {
        "status": row.status,
        "normalized_data": row.normalized_data,
        "errors": row.errors,
    }
    if payload.normalized_data is not None:
        row.normalized_data = payload.normalized_data
        row.row_hash = None
        row.errors = []
        row.status = payload.status or "pending"
    elif payload.status is not None:
        row.status = payload.status
        if payload.status == "valid":
            row.errors = []
    write_audit(
        session,
        household_id=household.id,
        action="import.row_update",
        entity_type="import_row",
        entity_id=row.id,
        before=before,
        after={
            "status": row.status,
            "normalized_data": row.normalized_data,
            "errors": row.errors,
        },
    )
    await session.flush()
    batch.valid_rows = int(
        await session.scalar(
            select(func.count())
            .select_from(ImportRow)
            .where(ImportRow.batch_id == batch.id, ImportRow.status == "valid")
        )
        or 0
    )
    batch.invalid_rows = int(
        await session.scalar(
            select(func.count())
            .select_from(ImportRow)
            .where(ImportRow.batch_id == batch.id, ImportRow.status == "invalid")
        )
        or 0
    )
    batch.duplicate_rows = int(
        await session.scalar(
            select(func.count())
            .select_from(ImportRow)
            .where(ImportRow.batch_id == batch.id, ImportRow.status == "duplicate")
        )
        or 0
    )
    await session.commit()
    await session.refresh(row)
    return row


async def cancel_import(session: AsyncSession, household: Household, batch_id: UUID) -> ImportBatch:
    batch = await get_batch(session, household.id, batch_id)
    _ensure_state(batch, _EDITABLE_STATES, "cancelled")
    before = _audit_data(batch)
    batch.status = "cancelled"
    write_audit(
        session,
        household_id=household.id,
        action="import.cancel",
        entity_type="import_batch",
        entity_id=batch.id,
        before=before,
        after=_audit_data(batch),
    )
    await session.commit()
    await session.refresh(batch)
    return batch


async def delete_import(session: AsyncSession, household: Household, batch_id: UUID) -> None:
    batch = await get_batch(session, household.id, batch_id)
    _ensure_state(
        batch,
        {"uploaded", "mapped", "previewed", "cancelled", "failed", "expired"},
        "deleted",
    )
    write_audit(
        session,
        household_id=household.id,
        action="import.delete",
        entity_type="import_batch",
        entity_id=batch.id,
        before=_audit_data(batch),
    )
    path = Path(batch.stored_path) if batch.stored_path else None
    await _remove_file(path)
    await session.delete(batch)
    await session.commit()


async def batch_detail(
    session: AsyncSession, household: Household, batch_id: UUID
) -> tuple[ImportBatch, list[list[str]]]:
    batch = await get_batch(session, household.id, batch_id)
    rows = list(
        (
            await session.scalars(
                select(ImportRow.raw_data)
                .where(ImportRow.batch_id == batch.id)
                .order_by(ImportRow.row_number.asc())
                .limit(SAMPLE_ROWS)
            )
        ).all()
    )
    return batch, rows


def preview_response(batch: ImportBatch, preview: list[ImportRow]) -> dict[str, Any]:
    payload = ImportPreviewRead.model_validate(batch).model_copy(
        update={
            "sample_rows": [row.raw_data for row in preview[:SAMPLE_ROWS]],
            "preview": [ImportRowRead.model_validate(row) for row in preview],
        }
    )
    return payload.model_dump(mode="json")


def batch_response(
    batch: ImportBatch, sample_rows: list[list[str]] | None = None
) -> dict[str, Any]:
    return _batch_response(batch, sample_rows)


def row_response(row: ImportRow) -> dict[str, Any]:
    return _row_response(row)
