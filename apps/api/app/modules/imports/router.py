"""Import endpoints (Phase 2B-3: CSV/XLSX, template, bulk row edits)."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dependencies import get_db
from app.core.pagination import PaginationDep, page_payload
from app.core.responses import success_response
from app.modules.households.dependencies import CurrentHousehold
from app.modules.imports import service
from app.modules.imports.models import ImportBatch
from app.modules.imports.schemas import (
    ImportConfirm,
    ImportMapping,
    ImportRowBulkSkip,
    ImportRowBulkUpdate,
    ImportRowUpdate,
)

router = APIRouter(prefix="/imports", tags=["imports"])

SessionDep = Annotated[AsyncSession, Depends(get_db)]


def _payload(batch: ImportBatch, sample_rows: list[list[str]] | None = None) -> dict[str, Any]:
    return service.batch_response(batch, sample_rows)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_import(
    session: SessionDep,
    household: CurrentHousehold,
    file: Annotated[UploadFile, File()],
    source_format: Annotated[str | None, Form()] = None,
    account_id: Annotated[UUID | None, Form()] = None,
    allow_duplicate_file: Annotated[bool, Form()] = False,
) -> dict[str, Any]:
    limit = get_settings().import_max_file_mb * 1024 * 1024 + 1
    data = await file.read(limit)
    batch = await service.create_import(
        session,
        household,
        filename=file.filename,
        data=data,
        source_format=source_format,
        account_id=account_id,
        allow_duplicate_file=allow_duplicate_file,
    )
    return success_response(_payload(batch))


@router.get("")
async def list_imports(
    session: SessionDep,
    household: CurrentHousehold,
    pagination: PaginationDep,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    batches, total = await service.list_imports(
        session, household, pagination, status=status_filter
    )
    return success_response(page_payload([_payload(item) for item in batches], total, pagination))


@router.get("/template")
async def download_template(
    file_format: Annotated[str, Query(alias="format", pattern="^(csv|xlsx)$")] = "csv",
) -> Response:
    if file_format == "xlsx":
        content = service.template_xlsx()
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "homeatlas-import-template.xlsx"
    else:
        content = service.template_csv()
        media_type = "text/csv; charset=utf-8"
        filename = "homeatlas-import-template.csv"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{batch_id}")
async def get_import(
    session: SessionDep, household: CurrentHousehold, batch_id: UUID
) -> dict[str, Any]:
    batch, sample_rows = await service.batch_detail(session, household, batch_id)
    return success_response(_payload(batch, sample_rows))


@router.put("/{batch_id}/mapping")
async def update_mapping(
    session: SessionDep,
    household: CurrentHousehold,
    batch_id: UUID,
    payload: ImportMapping,
) -> dict[str, Any]:
    batch = await service.update_mapping(session, household, batch_id, payload)
    return success_response(_payload(batch))


@router.post("/{batch_id}/preview")
async def preview_import(
    session: SessionDep, household: CurrentHousehold, batch_id: UUID
) -> dict[str, Any]:
    batch, preview = await service.preview_import(session, household, batch_id)
    return success_response(service.preview_response(batch, preview))


@router.get("/{batch_id}/rows")
async def list_rows(
    session: SessionDep,
    household: CurrentHousehold,
    batch_id: UUID,
    pagination: PaginationDep,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    rows, total = await service.list_rows(
        session, household, batch_id, pagination, status=status_filter
    )
    return success_response(
        page_payload([service.row_response(row) for row in rows], total, pagination)
    )


@router.put("/{batch_id}/rows")
async def bulk_update_rows(
    session: SessionDep,
    household: CurrentHousehold,
    batch_id: UUID,
    payload: ImportRowBulkUpdate,
) -> dict[str, Any]:
    batch, rows = await service.bulk_update_rows(session, household, batch_id, payload)
    return success_response(
        {
            "batch": _payload(batch),
            "items": [service.row_response(row) for row in rows],
        }
    )


@router.post("/{batch_id}/rows/skip")
async def bulk_skip_rows(
    session: SessionDep,
    household: CurrentHousehold,
    batch_id: UUID,
    payload: Annotated[ImportRowBulkSkip | None, Body()] = None,
) -> dict[str, Any]:
    batch, skipped = await service.bulk_skip_rows(
        session, household, batch_id, payload or ImportRowBulkSkip()
    )
    return success_response({"batch": _payload(batch), "skipped_rows": skipped})


@router.put("/{batch_id}/rows/{row_id}")
async def update_row(
    session: SessionDep,
    household: CurrentHousehold,
    batch_id: UUID,
    row_id: UUID,
    payload: ImportRowUpdate,
) -> dict[str, Any]:
    row = await service.update_row(session, household, batch_id, row_id, payload)
    return success_response(service.row_response(row))


@router.post("/{batch_id}/confirm")
async def confirm_import(
    session: SessionDep,
    household: CurrentHousehold,
    batch_id: UUID,
    payload: Annotated[ImportConfirm | None, Body()] = None,
) -> dict[str, Any]:
    batch = await service.confirm_import(session, household, batch_id, payload or ImportConfirm())
    return success_response(_payload(batch))


@router.post("/{batch_id}/cancel")
async def cancel_import(
    session: SessionDep, household: CurrentHousehold, batch_id: UUID
) -> dict[str, Any]:
    batch = await service.cancel_import(session, household, batch_id)
    return success_response(_payload(batch))


@router.delete("/{batch_id}")
async def delete_import(
    session: SessionDep, household: CurrentHousehold, batch_id: UUID
) -> dict[str, Any]:
    await service.delete_import(session, household, batch_id)
    return success_response(None, "Import batch deleted")
