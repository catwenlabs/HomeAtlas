"""Pydantic schemas for CSV/Excel data import (Phase 2B-1)."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

AmountMode = Literal[
    "signed_positive_income",
    "signed_positive_expense",
    "type_column",
    "debit_credit",
]


class ColumnMapping(BaseModel):
    """Maps standard fields to source column names."""

    transaction_date: str | None = None
    amount: str | None = None
    direction: str | None = None
    debit: str | None = None
    credit: str | None = None
    description: str | None = None
    category: str | None = None
    currency: str | None = None
    external_id: str | None = None
    exchange_rate: str | None = None
    account: str | None = None


class ImportMapping(BaseModel):
    header_row: Annotated[int, Field(ge=1)] = 1
    delimiter: str | None = None
    encoding: str | None = None
    columns: ColumnMapping
    amount_mode: AmountMode = "signed_positive_income"
    direction_map: dict[str, str] = Field(default_factory=dict)
    default_category_id: UUID | None = None
    category_map: dict[str, UUID] = Field(default_factory=dict)
    account_map: dict[str, UUID] = Field(default_factory=dict)
    date_formats: list[str] = Field(default_factory=list)

    @field_validator("delimiter")
    @classmethod
    def _validate_delimiter(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in {",", ";", "\t", "|"}:
            raise ValueError("delimiter must be one of , ; tab |")
        return value

    @field_validator("encoding")
    @classmethod
    def _validate_encoding(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.lower().replace("_", "-")
        if normalized not in {"utf-8", "utf-8-sig", "gb18030"}:
            raise ValueError("encoding must be utf-8, utf-8-sig, or gb18030")
        return normalized

    @field_validator("direction_map")
    @classmethod
    def _validate_direction_map(cls, value: dict[str, str]) -> dict[str, str]:
        for direction in value.values():
            if direction not in {"income", "expense"}:
                raise ValueError("direction_map values must be income or expense")
        return value


class ImportConfirm(BaseModel):
    on_duplicate: Literal["skip", "allow"] = "skip"
    create_status: Literal["confirmed", "draft"] = "confirmed"


class ImportRowUpdate(BaseModel):
    normalized_data: dict[str, Any] | None = None
    status: Literal["pending", "valid", "skipped"] | None = None


class ImportRowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID
    row_number: int
    raw_data: list[str]
    normalized_data: dict[str, Any] | None
    row_hash: str | None
    status: str
    errors: list[dict[str, Any]]
    transaction_id: UUID | None
    duplicate_of_transaction_id: UUID | None
    created_at: datetime
    updated_at: datetime


class ImportBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    household_id: UUID
    account_id: UUID | None
    status: str
    source_format: str
    original_filename: str | None
    file_sha256: str
    file_size_bytes: int
    columns: list[str]
    sample_rows: list[list[str]] = Field(default_factory=list)
    mapping: dict[str, Any] | None
    mapping_version: int
    total_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_rows: int
    imported_rows: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None
    completed_at: datetime | None


class ImportPreviewRead(ImportBatchRead):
    preview: list[ImportRowRead] = Field(default_factory=list)
