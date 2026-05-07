"""
Lead API routes.
线索管理接口：支持分页、按状态/归属人过滤、创建/更新/删除线索，
并在写入时自动计算 A 卡评分。
"""

from __future__ import annotations

import io
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import can_edit_owned_resource, get_current_user
from app.db.session import get_db
from app.models import Lead, User
from app.schemas import LeadCreate, LeadOut, LeadUpdate, MessageResponse, PaginatedResponse
from app.services.crm_rules_service import normalize_lead_status, status_to_active
from app.services.scoring_service import SCORING_FIELD_KEYS, calculate_card_score
from app.services.table_import_service import (
    LEAD_IMPORT_COLUMNS,
    build_template_file,
    empty_to_none,
    import_error_message,
    parse_import_table,
)

router = APIRouter(prefix="/api/leads", tags=["leads"])


def _lead_dimensions_from_model(lead: Lead) -> dict[str, str | None]:
    return {field_name: getattr(lead, field_name) for field_name in SCORING_FIELD_KEYS}


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


def _is_active_for_review(review_status: str | None, status: str | None) -> bool:
    if str(review_status or "").strip().lower() != "approved":
        return False
    return status_to_active(status or "new")


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
                lead.is_active = _is_active_for_review(lead.review_status, lead.status)

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


def _new_lead_from_data(data: dict[str, Any], current_user: User) -> Lead:
    scoring = calculate_card_score(data)
    status = normalize_lead_status(data.get("status"))
    # 支持导入时传入 _owner_id_override，否则使用当前用户
    owner_id = data.get("_owner_id_override") if "_owner_id_override" in data else current_user.id
    return Lead(
        name=data["name"],
        company=data.get("company"),
        email=data.get("email"),
        phone=data.get("phone"),
        source=data.get("source"),
        status=status,
        score=scoring.total_score,
        card_score=scoring.total_score,
        card_level=scoring.card_level,
        is_active=False,
        review_status="pending",
        owner_id=owner_id,
        score_detail_json=scoring.detail,
        custom_fields=data.get("custom_fields") or {},
        **scoring.dimensions,
    )


def _validated_import_data(payload: dict[str, Any]) -> dict[str, Any]:
    owner_override_present = "_owner_id_override" in payload
    owner_id_override = payload.get("_owner_id_override")
    data = LeadCreate.model_validate(payload).model_dump(exclude_unset=True)
    if owner_override_present:
        data["_owner_id_override"] = owner_id_override
    return data


def _is_yes(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"是", "yes", "y", "true", "1", "通过", "pass", "passed"}


async def _resolve_owner_id_by_name(db: AsyncSession, owner_name: str | None) -> str | None:
    """
    根据负责人姓名解析 owner_id。
    如果系统中存在同名的已注册用户，返回该用户 id；否则返回 None。
    """
    text = str(owner_name or "").strip()
    if not text:
        return None
    result = await db.execute(select(User).where(User.username == text))
    user = result.scalar_one_or_none()
    return str(user.id) if user else None


def _is_no(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"否", "no", "n", "false", "0", "不通过", "fail", "failed"}


def _lead_status_from_import(value: str | None, custom_fields: dict[str, Any]) -> str:
    aliases = {
        "": "",
        "新建": "new",
        "新增": "new",
        "new": "new",
        "跟进": "follow_up",
        "跟进中": "follow_up",
        "follow_up": "follow_up",
        "working": "follow_up",
        "已转化": "converted",
        "转化": "converted",
        "converted": "converted",
        "无效": "invalid",
        "invalid": "invalid",
        "disqualified": "invalid",
        "归档": "archived",
        "archived": "archived",
    }
    normalized = aliases.get(str(value or "").strip().lower())
    if normalized:
        return normalized
    if _is_yes(custom_fields.get("third_review_pass")):
        return "converted"
    if _is_yes(custom_fields.get("second_review_pass")):
        return "follow_up"
    if _is_no(custom_fields.get("first_review_pass")):
        return "invalid"
    return "new"


def _lead_payload_from_import_row(row: dict[str, str], current_user: User) -> dict[str, Any]:
    unit_name = str(row.get("unit_name") or "").strip()
    if not unit_name:
        raise ValueError("单位名称必填")

    # serial_no 不入库，只读取后丢弃
    serial_no = row.get("serial_no")

    custom_fields = {
        "business_owner": row.get("business_owner") or "",
        "unit_name": unit_name,
        "industry_category": row.get("industry_category") or "",
        "customer_type": row.get("customer_type") or "",
        "opportunity_level": row.get("opportunity_level") or "",
        "requirement_desc": row.get("requirement_desc") or "",
        "budget_amount": row.get("budget_amount") or "",
        "lead_source": row.get("lead_source") or "",
        "purchased_related_products": row.get("purchased_related_products") or "",
        "first_review_pass": row.get("first_review_pass") or "",
        "visit_key_time": row.get("visit_key_time") or "",
        "decision_chain_info": row.get("decision_chain_info") or "",
        "cooperation_intent": row.get("cooperation_intent") or "",
        "next_visit_plan": row.get("next_visit_plan") or "",
        "second_review_pass": row.get("second_review_pass") or "",
        "cooperation_scheme_status": row.get("cooperation_scheme_status") or "",
        "key_person_approved": row.get("key_person_approved") or "",
        "next_step_plan": row.get("next_step_plan") or "",
        "third_review_pass": row.get("third_review_pass") or "",
        "import_user_id": current_user.id,
        "import_username": current_user.username,
    }

    return {
        "name": unit_name,
        "company": unit_name,
        "email": empty_to_none(row.get("email")),
        "phone": empty_to_none(row.get("phone")),
        "source": empty_to_none(row.get("lead_source")),
        "status": _lead_status_from_import(row.get("status"), custom_fields),
        "custom_fields": custom_fields,
    }


@router.get("", response_model=PaginatedResponse, summary="线索列表（支持分页）")
async def list_leads(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=200, description="每页条数，最大 200"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    review_status: Optional[str] = Query(None, description="按管理员审核状态过滤"),
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
    if review_status:
        query = query.where(Lead.review_status == str(review_status).strip().lower())
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = payload.model_dump(exclude_unset=True)
    lead = _new_lead_from_data(data, current_user)
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    await db.refresh(lead, ["owner"])
    return LeadOut.model_validate(lead)


@router.get("/import-template", summary="Download lead import template")
async def download_lead_import_template(
    format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
    _: User = Depends(get_current_user),
):
    content, media_type, extension = build_template_file(LEAD_IMPORT_COLUMNS, format)
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="leads_import_template.{extension}"'},
    )


@router.post("/import", summary="Import leads from xlsx/csv")
async def import_leads(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    try:
        rows = parse_import_table(file.filename or "", content, LEAD_IMPORT_COLUMNS)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    errors: list[dict[str, Any]] = []
    created = 0
    for row in rows:
        try:
            payload = _lead_payload_from_import_row(row.values, current_user)

            # 解析负责人：如果 Excel 中有负责人姓名，尝试绑定到已注册用户
            owner_name = payload["custom_fields"].get("business_owner")
            if owner_name:
                # 尝试解析负责人 ID，如果未注册则保持 None
                resolved_owner_id = await _resolve_owner_id_by_name(db, owner_name)
                payload["_owner_id_override"] = resolved_owner_id
                # resolved_owner_id 是 None 时表示负责人未注册，不要 fallback 到 current_user.id

            data = _validated_import_data(payload)
            db.add(_new_lead_from_data(data, current_user))
            created += 1
        except Exception as exc:
            errors.append({"row": row.row_number, "message": import_error_message(exc)})

    if created:
        await db.commit()

    return {
        "total": len(rows),
        "created": created,
        "failed": len(errors),
        "errors": errors[:50],
    }


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


async def _get_lead_or_404(lead_id: UUID, db: AsyncSession) -> Lead:
    result = await db.execute(select(Lead).where(Lead.id == str(lead_id)).options(selectinload(Lead.owner)))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在")
    return lead


async def _get_lead_or_403(lead_id: UUID, db: AsyncSession, current_user: User) -> Lead:
    result = await db.execute(select(Lead).where(Lead.id == str(lead_id)).options(selectinload(Lead.owner)))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在")
    if not can_edit_owned_resource(current_user, lead.owner_id):
        raise HTTPException(status_code=403, detail="你不能操作其他人的线索")
    return lead
