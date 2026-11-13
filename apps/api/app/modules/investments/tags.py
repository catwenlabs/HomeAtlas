"""Investment tag CRUD (asset-design sections 4.5, 6.3)."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.modules.audit.service import write_audit
from app.modules.investments.models import InvestmentTag, InvestmentTagLink
from app.modules.investments.schemas import TagCreate, TagUpdate


def _audit_data(tag: InvestmentTag) -> dict[str, Any]:
    return {"name": tag.name, "color": tag.color}


async def get_tag(session: AsyncSession, household_id: UUID, tag_id: UUID) -> InvestmentTag:
    tag = await session.scalar(
        select(InvestmentTag).where(
            InvestmentTag.id == tag_id,
            InvestmentTag.household_id == household_id,
        )
    )
    if tag is None:
        raise NotFoundError("Investment tag not found", error_code="TAG_NOT_FOUND")
    return tag


async def create_tag(
    session: AsyncSession, household_id: UUID, payload: TagCreate
) -> InvestmentTag:
    duplicate = await session.scalar(
        select(func.count())
        .select_from(InvestmentTag)
        .where(
            InvestmentTag.household_id == household_id,
            InvestmentTag.name == payload.name,
        )
    )
    if duplicate:
        raise AppError(
            f"Tag '{payload.name}' already exists",
            status_code=409,
            error_code="TAG_DUPLICATE",
        )
    tag = InvestmentTag(
        household_id=household_id,
        name=payload.name,
        color=payload.color,
    )
    session.add(tag)
    await session.flush()
    write_audit(
        session,
        household_id=household_id,
        action="investment_tag.create",
        entity_type="investment_tag",
        entity_id=tag.id,
        after=_audit_data(tag),
    )
    await session.commit()
    await session.refresh(tag)
    return tag


async def update_tag(
    session: AsyncSession, household_id: UUID, tag_id: UUID, payload: TagUpdate
) -> InvestmentTag:
    tag = await get_tag(session, household_id, tag_id)
    before = _audit_data(tag)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("name") is not None and changes["name"] != tag.name:
        duplicate = await session.scalar(
            select(func.count())
            .select_from(InvestmentTag)
            .where(
                InvestmentTag.household_id == household_id,
                InvestmentTag.name == changes["name"],
                InvestmentTag.id != tag.id,
            )
        )
        if duplicate:
            raise AppError(
                f"Tag '{changes['name']}' already exists",
                status_code=409,
                error_code="TAG_DUPLICATE",
            )
        tag.name = changes["name"]
    if "color" in changes:
        tag.color = changes["color"]
    await session.flush()
    write_audit(
        session,
        household_id=household_id,
        action="investment_tag.update",
        entity_type="investment_tag",
        entity_id=tag.id,
        before=before,
        after=_audit_data(tag),
    )
    await session.commit()
    await session.refresh(tag)
    return tag


async def delete_tag(session: AsyncSession, household_id: UUID, tag_id: UUID) -> None:
    tag = await get_tag(session, household_id, tag_id)
    links = await session.scalar(
        select(func.count())
        .select_from(InvestmentTagLink)
        .where(InvestmentTagLink.tag_id == tag.id)
    )
    if links:
        raise AppError(
            f"Tag '{tag.name}' is used by {links} investment(s)",
            status_code=409,
            error_code="TAG_IN_USE",
        )
    before = _audit_data(tag)
    await session.delete(tag)
    write_audit(
        session,
        household_id=household_id,
        action="investment_tag.delete",
        entity_type="investment_tag",
        entity_id=tag.id,
        before=before,
    )
    await session.commit()


async def list_tags(session: AsyncSession, household_id: UUID) -> list[InvestmentTag]:
    return list(
        (
            await session.scalars(
                select(InvestmentTag)
                .where(InvestmentTag.household_id == household_id)
                .order_by(InvestmentTag.created_at.asc(), InvestmentTag.name.asc())
            )
        ).all()
    )
