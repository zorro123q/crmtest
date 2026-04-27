"""
Lead API routes.
线索管理接口：支持分页、按状态/归属人过滤、创建/更新/删除线索，
并在写入时自动计算 A 卡评分。
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import can_edit_owned_resource, get_current_user
from app.db.session import get_db
from app.models import Lead, User
from app.schemas import LeadCreate, LeadOut, LeadUpdate, MessageResponse, PaginatedResponse
from app.services.crm_rules_service import normalize_lead_status, status_to_active
from app.services.scoring_service import SCORING_FIELD_KEYS, calculate_card_score

router = APIRouter(prefix="/api/leads", tags=["leads"])


def _lead_dimensions_from_model(lead: Lead) -> dict[str, str | None]:
    return {field_name: getattr(lead, field_name) for field_name in SCORING_FIELD_KEYS}


def _normalize_name(value: str | None) -> str:
    return str(value or "").strip().lower()


def _has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_has_meaningful_value(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return bool(value)
    return True


def _merge_custom_fields(
    current_custom_fields: dict[str, Any] | None,
    incoming_custom_fields: dict[str, Any] | None,
    *,
    ignore_empty: bool = False,
) -> dict[str, Any]:
    merged = dict(current_custom_fields or {})
    if not incoming_custom_fields:
        return merged

    for key, value in incoming_custom_fields.items():
        if ignore_empty and not _has_meaningful_value(value):
            continue
        merged[key] = value
    return merged


def _apply_lead_payload(
    lead: Lead,
    data: dict[str, Any],
    *,
    ignore_empty: bool = False,
    preserve_existing_status: bool = False,
) -> None:
    for field_name in ("name", "company", "email", "phone", "source"):
        if field_name not in data:
            continue
        value = data[field_name]
        if ignore_empty and not _has_meaningful_value(value):
            continue
        setattr(lead, field_name, value)

    if "status" in data:
        status_value = data["status"]
        if not (ignore_empty and not _has_meaningful_value(status_value)):
            normalized_status = normalize_lead_status(str(status_value))
            if not (
                preserve_existing_status
                and normalized_status == "new"
                and lead.status
                and lead.status != "new"
            ):
                lead.status = normalized_status
                lead.is_active = status_to_active(lead.status)

    dimensions = _lead_dimensions_from_model(lead)
    for field_name in SCORING_FIELD_KEYS:
        if field_name not in data:
            continue
        value = data[field_name]
        if ignore_empty and not _has_meaningful_value(value):
            continue
        dimensions[field_name] = value

    scoring = calculate_card_score(dimensions)
    for field_name, value in scoring.dimensions.items():
        setattr(lead, field_name, value)

    lead.score = scoring.total_score
    lead.card_score = scoring.total_score
    lead.card_level = scoring.card_level
    lead.score_detail_json = scoring.detail

    if "custom_fields" in data:
        lead.custom_fields = _merge_custom_fields(
            lead.custom_fields,
            data.get("custom_fields"),
            ignore_empty=ignore_empty,
        )


async def _find_latest_lead_by_name(name: str, db: AsyncSession) -> Lead | None:
    normalized_name = _normalize_name(name)
    if not normalized_name:
        return None

    result = await db.execute(
        select(Lead)
        .where(func.lower(func.trim(Lead.name)) == normalized_name)
        .options(selectinload(Lead.owner))
        .order_by(Lead.updated_at.desc(), Lead.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


@router.get("", response_model=PaginatedResponse, summary="线索列表（支持分页）")
async def list_leads(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=200, description="每页条数，最大 200"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    owner_id: Optional[UUID] = Query(None, description="按归属人 ID 过滤"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    分页查询线索列表。
    - 默认每页 20 条，最大每页 200 条，防止大数据量一次性加载到内存。
    - 支持按状态（status）和归属人（owner_id）过滤。
    """
    query = select(Lead).options(selectinload(Lead.owner)).order_by(Lead.created_at.desc())

    if status:
        query = query.where(Lead.status == normalize_lead_status(status))
    if owner_id:
        query = query.where(Lead.owner_id == str(owner_id))

    # 先查总数
    total_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(total_query)).scalar() or 0

    # 再分页查数据
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    leads = result.scalars().all()

    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        data=[LeadOut.model_validate(lead) for lead in leads],
    )


@router.post("", response_model=LeadOut, status_code=201, summary="Create lead")
async def create_lead(
    payload: LeadCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = payload.model_dump(exclude_unset=True)
    existing = await _find_latest_lead_by_name(data["name"], db)

    if existing:
        if not can_edit_owned_resource(current_user, existing.owner_id):
            raise HTTPException(status_code=403, detail="已存在同名线索，当前账号不能覆盖他人数据")

        _apply_lead_payload(
            existing,
            data,
            ignore_empty=True,
            preserve_existing_status=True,
        )
        await db.commit()
        await db.refresh(existing)
        await db.refresh(existing, ["owner"])
        response.status_code = 200
        return LeadOut.model_validate(existing)

    scoring = calculate_card_score(data)
    custom_fields = data.get("custom_fields") or {}
    lead = Lead(
        name=data["name"],
        company=data.get("company"),
        email=data.get("email"),
        phone=data.get("phone"),
        source=data.get("source"),
        status=normalize_lead_status(data.get("status")),
        score=scoring.total_score,
        card_score=scoring.total_score,
        card_level=scoring.card_level,
        is_active=status_to_active(data.get("status", "new")),
        owner_id=current_user.id,
        score_detail_json=scoring.detail,
        custom_fields=custom_fields,
        **scoring.dimensions,
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    await db.refresh(lead, ["owner"])
    return LeadOut.model_validate(lead)


@router.patch("/{lead_id}", response_model=LeadOut, summary="Update lead")
async def update_lead(
    lead_id: UUID,
    payload: LeadUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    lead = await _get_lead_or_403(lead_id, db, current_user)
    data = payload.model_dump(exclude_unset=True)
    _apply_lead_payload(lead, data)

    await db.commit()
    await db.refresh(lead)
    await db.refresh(lead, ["owner"])
    return LeadOut.model_validate(lead)


@router.delete("/{lead_id}", response_model=MessageResponse, summary="Delete lead")
async def delete_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    lead = await _get_lead_or_403(lead_id, db, current_user)
    await db.delete(lead)
    await db.commit()
    return MessageResponse(message="线索已删除")


async def _get_lead_or_403(lead_id: UUID, db: AsyncSession, current_user: User) -> Lead:
    result = await db.execute(select(Lead).where(Lead.id == str(lead_id)).options(selectinload(Lead.owner)))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在")
    if not can_edit_owned_resource(current_user, lead.owner_id):
        raise HTTPException(status_code=403, detail="你不能操作其他人的线索")
    return lead
