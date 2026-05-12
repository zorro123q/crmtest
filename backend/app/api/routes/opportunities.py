"""
Opportunity API routes.
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import can_edit_owned_resource, get_current_user
from app.db.session import get_db
from app.models import Opportunity, User
from app.schemas import (
    MessageResponse,
    OpportunityCreate,
    OpportunityOut,
    OpportunityUpdate,
    PaginatedResponse,
    StageMoveRequest,
)
from app.services.crm_rules_service import (
    DEFAULT_OPPORTUNITY_STAGE,
    NEGOTIATION_STAGE,
    QUOTE_STAGE,
    STAGE_DEFAULT_PROBABILITY,
    STAGE_ORDER,
    WON_STAGE,
    LOST_STAGE,
    derive_opportunity_status,
    normalize_opportunity_stage,
    status_to_active,
)
from app.services.scoring_service import SCORING_FIELD_KEYS, calculate_card_score
from app.services.table_import_service import (
    OPPORTUNITY_IMPORT_COLUMNS,
    build_template_file,
    empty_to_none,
    import_error_message,
    parse_import_table,
)
from app.services.owner_identity_service import owner_name_matches_user, resolve_owner_id_by_name

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])

BUSINESS_FIELD_KEYS = (
    "customer_name",
    "customer_type",
    "requirement_desc",
    "product_name",
    "estimated_cycle",
    "opportunity_level",
    "project_date",
    "project_members",
    "solution_communication",
    "poc_status",
    "key_person_approved",
    "bid_probability",
    "contract_negotiation",
    "project_type",
    "contract_signed",
    "handoff_completed",
)

LEGACY_CUSTOM_FIELD_ALIASES = {
    "customer_name": ("customer_name", "company"),
    "customer_type": ("customer_type",),
    "requirement_desc": ("requirement_desc", "notes", "demand"),
    "product_name": ("product_name", "product"),
    "estimated_cycle": ("estimated_cycle",),
    "opportunity_level": ("opportunity_level", "level"),
    "project_date": ("project_date",),
    "project_members": ("project_members",),
    "solution_communication": ("solution_communication",),
    "poc_status": ("poc_status",),
    "key_person_approved": ("key_person_approved", "approve"),
    "bid_probability": ("bid_probability", "bcard"),
    "contract_negotiation": ("contract_negotiation",),
    "project_type": ("project_type",),
    "contract_signed": ("contract_signed", "signed"),
    "handoff_completed": ("handoff_completed",),
}


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _pick_first_non_empty(*values):
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            trimmed = value.strip()
            if trimmed == "":
                continue
            return trimmed
        return value
    return None


def _normalize_business_payload(data: dict) -> dict:
    normalized = dict(data)
    custom_fields = dict(normalized.get("custom_fields") or {})

    for field_name, aliases in LEGACY_CUSTOM_FIELD_ALIASES.items():
        top_value = normalized.get(field_name)
        alias_values = [custom_fields.get(alias) for alias in aliases]
        normalized[field_name] = _pick_first_non_empty(top_value, *alias_values)

    normalized["custom_fields"] = custom_fields
    return normalized


def _opportunity_dimensions_from_model(opportunity: Opportunity) -> dict[str, str | None]:
    return {field_name: getattr(opportunity, field_name) for field_name in SCORING_FIELD_KEYS}


def _opportunity_dimensions_from_payload(data: dict) -> dict[str, str | None]:
    return {field_name: data.get(field_name) for field_name in SCORING_FIELD_KEYS}


def _build_opportunity_name(data: dict) -> str:
    raw_name = str(data.get("name") or "").strip()
    if raw_name:
        return raw_name

    customer_name = str(data.get("customer_name") or "").strip()
    product_name = str(data.get("product_name") or "").strip()

    if customer_name and product_name:
        return f"{customer_name} - {product_name}"
    if customer_name:
        return customer_name
    if product_name:
        return product_name
    return "未命名商机"


def _merge_custom_fields(existing: dict | None, data: dict) -> dict:
    merged = {**(existing or {})}

    for field_name in BUSINESS_FIELD_KEYS:
        value = data.get(field_name)
        if value is not None:
            merged[field_name] = value

    # 继续保留旧字段名，兼容旧页面/旧数据
    if data.get("customer_name") is not None:
        merged["company"] = data.get("customer_name")
    if data.get("requirement_desc") is not None:
        merged["notes"] = data.get("requirement_desc")
        merged["demand"] = data.get("requirement_desc")
    if data.get("product_name") is not None:
        merged["product"] = data.get("product_name")
    if data.get("opportunity_level") is not None:
        merged["level"] = data.get("opportunity_level")
    if data.get("bid_probability") is not None:
        merged["bcard"] = data.get("bid_probability")
    if data.get("key_person_approved") is not None:
        merged["approve"] = data.get("key_person_approved")
    if data.get("contract_signed") is not None:
        merged["signed"] = data.get("contract_signed")

    return merged


def _normalize_history_text(value: object) -> str:
    return str(value or "").strip()


def _append_solution_communication_history(
    custom_fields: dict | None,
    *,
    previous_value: object = None,
    next_value: object = None,
    current_user: User,
    changed_at: datetime,
    force: bool = False,
) -> dict:
    merged = dict(custom_fields or {})
    previous_text = _normalize_history_text(previous_value)
    next_text = _normalize_history_text(next_value)

    if not force and previous_text == next_text:
        return merged
    if force and not next_text:
        return merged

    raw_history = merged.get("solution_communication_history")
    history = list(raw_history) if isinstance(raw_history, list) else []
    history.append(
        {
            "previous": previous_text,
            "value": next_text,
            "changed_at": changed_at.isoformat(),
            "changed_by_id": str(current_user.id),
            "changed_by_name": current_user.username,
        }
    )
    merged["solution_communication_history"] = history
    return merged


def _is_active_for_review(review_status: str | None, status: str | None) -> bool:
    if str(review_status or "").strip().lower() != "approved":
        return False
    return status_to_active(status or "new")


def _apply_business_fields(opportunity: Opportunity, data: dict):
    for field_name in BUSINESS_FIELD_KEYS:
        if field_name in data:
            setattr(opportunity, field_name, data[field_name])


def _sync_stage_state(
    opportunity: Opportunity,
    next_stage: str,
    changed_at: datetime,
    *,
    override_closed_at: bool = False,
    override_probability: int | None = None,
):
    normalized_stage = normalize_opportunity_stage(next_stage)
    stage_changed = opportunity.stage != normalized_stage
    history = list(opportunity.stage_history or [])

    if stage_changed and history:
        last = history[-1]
        if "exited_at" not in last:
            entered_at = _parse_iso_datetime(last.get("entered_at"))
            last["exited_at"] = changed_at.isoformat()
            last["days"] = max(0, (changed_at - entered_at).days) if entered_at else 0

    if stage_changed or not history:
        history.append({"stage": normalized_stage, "entered_at": changed_at.isoformat()})

    opportunity.stage_history = history
    opportunity.stage = normalized_stage
    opportunity.probability = (
        override_probability
        if override_probability is not None
        else STAGE_DEFAULT_PROBABILITY.get(
            normalized_stage,
            STAGE_DEFAULT_PROBABILITY[DEFAULT_OPPORTUNITY_STAGE],
        )
    )

    if normalized_stage in {WON_STAGE, LOST_STAGE}:
        if override_closed_at or opportunity.closed_at is None or stage_changed:
            opportunity.closed_at = changed_at
    elif stage_changed:
        opportunity.closed_at = None


def _new_opportunity_from_data(data: dict, current_user: User) -> Opportunity:
    scoring = calculate_card_score(_opportunity_dimensions_from_payload(data))
    now = datetime.now(timezone.utc)

    stage = normalize_opportunity_stage(data.get("stage"))
    status = str(data.get("status") or "new").strip().lower()
    if status != "archived":
        status = derive_opportunity_status(stage, status)

    # 支持导入时传入 _owner_id_override，否则使用当前用户
    owner_id = data.get("_owner_id_override") if "_owner_id_override" in data else current_user.id

    opportunity = Opportunity(
        name=_build_opportunity_name(data),
        account_id=str(data["account_id"]) if data.get("account_id") else None,
        contact_id=str(data["contact_id"]) if data.get("contact_id") else None,
        owner_id=owner_id,
        amount=data.get("amount"),
        close_date=data.get("close_date"),
        source=data.get("source"),
        status=status,
        is_active=False,
        review_status="pending",
        card_score=scoring.total_score,
        card_level=scoring.card_level,
        score_detail_json=scoring.detail,
        ai_confidence=data.get("ai_confidence"),
        ai_raw_text=data.get("ai_raw_text"),
        ai_extracted=data.get("ai_extracted") or {},
        custom_fields=_merge_custom_fields(data.get("custom_fields") or {}, data),
        customer_name=data.get("customer_name"),
        customer_type=data.get("customer_type"),
        requirement_desc=data.get("requirement_desc"),
        product_name=data.get("product_name"),
        estimated_cycle=data.get("estimated_cycle"),
        opportunity_level=data.get("opportunity_level"),
        project_date=data.get("project_date"),
        project_members=data.get("project_members"),
        solution_communication=data.get("solution_communication"),
        poc_status=data.get("poc_status"),
        key_person_approved=data.get("key_person_approved"),
        bid_probability=data.get("bid_probability"),
        contract_negotiation=data.get("contract_negotiation"),
        project_type=data.get("project_type"),
        contract_signed=data.get("contract_signed"),
        handoff_completed=data.get("handoff_completed"),
        **scoring.dimensions,
    )

    opportunity.custom_fields = _append_solution_communication_history(
        opportunity.custom_fields,
        next_value=opportunity.solution_communication,
        current_user=current_user,
        changed_at=now,
        force=True,
    )
    _sync_stage_state(opportunity, stage, now, override_probability=data.get("probability"))
    return opportunity


def _validated_import_data(payload: dict) -> dict:
    owner_override_present = "_owner_id_override" in payload
    owner_id_override = payload.get("_owner_id_override")
    data = OpportunityCreate.model_validate(payload).model_dump(exclude_unset=True)
    if owner_override_present:
        data["_owner_id_override"] = owner_id_override
    return _normalize_business_payload(data)


def _is_yes(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"是", "yes", "y", "true", "1", "已签订"}


def _parse_import_amount(value: str | None) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = re.sub(r"[,，￥¥\s]", "", text)
    if normalized.endswith("万"):
        return float(normalized[:-1]) * 10000
    return float(normalized)


def _opportunity_stage_from_import(value: str | None, row: dict[str, str]) -> str:
    aliases = {
        DEFAULT_OPPORTUNITY_STAGE.lower(): DEFAULT_OPPORTUNITY_STAGE,
        "初步接触": DEFAULT_OPPORTUNITY_STAGE,
        "new": DEFAULT_OPPORTUNITY_STAGE,
        QUOTE_STAGE.lower(): QUOTE_STAGE,
        "方案报价": QUOTE_STAGE,
        "quote": QUOTE_STAGE,
        NEGOTIATION_STAGE.lower(): NEGOTIATION_STAGE,
        "合同谈判": NEGOTIATION_STAGE,
        "negotiation": NEGOTIATION_STAGE,
        WON_STAGE.lower(): WON_STAGE,
        "赢单": WON_STAGE,
        "won": WON_STAGE,
        LOST_STAGE.lower(): LOST_STAGE,
        "输单": LOST_STAGE,
        "lost": LOST_STAGE,
    }
    normalized = aliases.get(str(value or "").strip().lower())
    if normalized:
        return normalized
    if _is_yes(row.get("contract_signed")):
        return WON_STAGE
    if row.get("contract_negotiation"):
        return NEGOTIATION_STAGE
    if row.get("solution_communication") or row.get("poc_status") or _is_yes(row.get("key_person_approved")):
        return QUOTE_STAGE
    return DEFAULT_OPPORTUNITY_STAGE


def _opportunity_status_from_import(value: str | None, row: dict[str, str]) -> str:
    aliases = {
        "": "",
        "新建": "new",
        "新增": "new",
        "new": "new",
        "跟进": "follow_up",
        "跟进中": "follow_up",
        "follow_up": "follow_up",
        "已赢单": "won",
        "赢单": "won",
        "won": "won",
        "已输单": "lost",
        "输单": "lost",
        "lost": "lost",
        "归档": "archived",
        "archived": "archived",
    }
    normalized = aliases.get(str(value or "").strip().lower())
    if normalized:
        return normalized
    return "won" if _is_yes(row.get("contract_signed")) else "follow_up"


def _opportunity_payload_from_import_row(row: dict[str, str], current_user: User) -> dict:
    customer_name = str(row.get("customer_name") or "").strip()
    product_name = str(row.get("product_name") or "").strip()
    if not customer_name:
        raise ValueError("客户名称必填")
    if not product_name:
        raise ValueError("涉及产品必填")

    # serial_no 不入库，只读取后丢弃
    serial_no = row.get("serial_no")

    # 从 Excel 读取负责人姓名（无论是否已注册都要保存）
    owner_name_from_excel = row.get("owner_name_display") or ""

    custom_fields = {
        "owner_name_display": owner_name_from_excel,
        "customer_name": customer_name,
        "customer_type": row.get("customer_type") or "",
        "requirement_desc": row.get("requirement_desc") or "",
        "product_name": product_name,
        "estimated_cycle": row.get("estimated_cycle") or "",
        "opportunity_level": row.get("opportunity_level") or "",
        "project_date": row.get("project_date") or "",
        "project_members": row.get("project_members") or "",
        "solution_communication": row.get("solution_communication") or "",
        "poc_status": row.get("poc_status") or "",
        "key_person_approved": row.get("key_person_approved") or "",
        "bid_probability": row.get("bid_probability") or "",
        "contract_negotiation": row.get("contract_negotiation") or "",
        "project_type": row.get("project_type") or "",
        "contract_signed": row.get("contract_signed") or "",
        "handoff_completed": row.get("handoff_completed") or "",
        "company": customer_name,
        "demand": row.get("requirement_desc") or "",
        "product": product_name,
        "level": row.get("opportunity_level") or "",
        "bcard": row.get("bid_probability") or "",
        "approve": row.get("key_person_approved") or "",
        "signed": row.get("contract_signed") or "",
        "notes": row.get("requirement_desc") or "",
        "import_user_id": current_user.id,
        "import_username": current_user.username,
    }

    return {
        "name": f"{customer_name} - {product_name}",
        "stage": _opportunity_stage_from_import(row.get("stage"), row),
        "status": _opportunity_status_from_import(row.get("status"), row),
        "amount": _parse_import_amount(row.get("amount")),
        "source": "import",
        "customer_name": customer_name,
        "customer_type": empty_to_none(row.get("customer_type")),
        "requirement_desc": empty_to_none(row.get("requirement_desc")),
        "product_name": product_name,
        "estimated_cycle": empty_to_none(row.get("estimated_cycle")),
        "opportunity_level": empty_to_none(row.get("opportunity_level")),
        "project_date": empty_to_none(row.get("project_date")),
        "project_members": empty_to_none(row.get("project_members")),
        "solution_communication": empty_to_none(row.get("solution_communication")),
        "poc_status": empty_to_none(row.get("poc_status")),
        "key_person_approved": empty_to_none(row.get("key_person_approved")),
        "bid_probability": empty_to_none(row.get("bid_probability")),
        "contract_negotiation": empty_to_none(row.get("contract_negotiation")),
        "project_type": empty_to_none(row.get("project_type")),
        "contract_signed": empty_to_none(row.get("contract_signed")),
        "handoff_completed": empty_to_none(row.get("handoff_completed")),
        "custom_fields": custom_fields,
    }


@router.get("", response_model=PaginatedResponse, summary="Opportunity list")
async def list_opportunities(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    stage: Optional[str] = None,
    status: Optional[str] = None,
    review_status: Optional[str] = None,
    owner_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = select(Opportunity).options(selectinload(Opportunity.owner))

    if stage:
        query = query.where(Opportunity.stage == normalize_opportunity_stage(stage))
    if status:
        query = query.where(Opportunity.status == str(status).strip().lower())
    if review_status:
        query = query.where(Opportunity.review_status == str(review_status).strip().lower())
    if owner_id:
        query = query.where(Opportunity.owner_id == str(owner_id))

    total_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(total_query)).scalar() or 0

    result = await db.execute(
        query.order_by(Opportunity.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    opportunities = result.scalars().all()

    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        data=[OpportunityOut.model_validate(item) for item in opportunities],
    )


@router.get("/funnel", summary="Opportunity funnel summary")
async def funnel_summary(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = select(
        Opportunity.stage,
        func.count(Opportunity.id).label("count"),
        func.coalesce(func.sum(Opportunity.amount), 0).label("total_amount"),
        func.avg(Opportunity.probability).label("avg_prob"),
    )
    query = query.group_by(Opportunity.stage)

    result = await db.execute(query)
    rows = result.all()
    grouped = {
        row.stage: {
            "count": row.count,
            "total_amount": float(row.total_amount),
            "avg_prob": float(row.avg_prob or 0),
        }
        for row in rows
    }

    return {
        "funnel": [
            {
                "stage": stage_name,
                "count": grouped.get(stage_name, {}).get("count", 0),
                "total_amount": grouped.get(stage_name, {}).get("total_amount", 0),
                "avg_prob": grouped.get(stage_name, {}).get("avg_prob", 0),
            }
            for stage_name in STAGE_ORDER
        ]
    }


@router.post("", response_model=OpportunityOut, status_code=201, summary="Create opportunity")
async def create_opportunity(
    payload: OpportunityCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    raw_data = payload.model_dump(exclude_unset=True)
    data = _normalize_business_payload(raw_data)
    opportunity = _new_opportunity_from_data(data, current_user)
    db.add(opportunity)
    await db.commit()
    await db.refresh(opportunity)
    await db.refresh(opportunity, ["owner"])
    return OpportunityOut.model_validate(opportunity)


@router.get("/import-template", summary="Download opportunity import template")
async def download_opportunity_import_template(
    format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
    _: User = Depends(get_current_user),
):
    content, media_type, extension = build_template_file(OPPORTUNITY_IMPORT_COLUMNS, format)
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="opportunities_import_template.{extension}"'},
    )


@router.post("/import", summary="Import opportunities from xlsx/csv")
async def import_opportunities(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    try:
        rows = parse_import_table(file.filename or "", content, OPPORTUNITY_IMPORT_COLUMNS)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    errors: list[dict[str, object]] = []
    created = 0
    for row in rows:
        try:
            raw_payload = _opportunity_payload_from_import_row(row.values, current_user)

            # 解析负责人：如果 Excel 中有负责人姓名，尝试绑定到已注册用户
            owner_name = raw_payload["custom_fields"].get("owner_name_display")
            if owner_name:
                # 尝试解析负责人 ID，如果未注册则保持 None
                resolved_owner_id = await resolve_owner_id_by_name(db, owner_name)
                raw_payload["_owner_id_override"] = resolved_owner_id
                # resolved_owner_id 是 None 时表示负责人未注册，不要 fallback 到 current_user.id

            data = _validated_import_data(raw_payload)
            db.add(_new_opportunity_from_data(data, current_user))
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


@router.patch("/{opp_id}", response_model=OpportunityOut, summary="Update opportunity")
async def update_opportunity(
    opp_id: UUID,
    payload: OpportunityUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    opportunity = await _get_opp_or_403(opp_id, db, current_user)
    if owner_name_matches_user(
        current_user,
        (opportunity.custom_fields or {}).get("owner_name_display"),
    ) and str(opportunity.owner_id or "") != str(current_user.id):
        opportunity.owner_id = current_user.id

    previous_solution_communication = opportunity.solution_communication
    raw_data = payload.model_dump(exclude_unset=True)
    data = _normalize_business_payload(raw_data)
    custom_fields = data.pop("custom_fields", None)

    for field_name in ("name", "amount", "close_date", "source"):
        if field_name in data:
            setattr(opportunity, field_name, data[field_name])

    _apply_business_fields(opportunity, data)

    next_stage = data.get("stage", opportunity.stage)
    next_status = data.get("status", opportunity.status)
    if str(next_status or "").strip().lower() != "archived":
        next_status = derive_opportunity_status(next_stage, next_status)

    dimensions = _opportunity_dimensions_from_model(opportunity)
    for field_name in SCORING_FIELD_KEYS:
        if field_name in data:
            dimensions[field_name] = data[field_name]

    scoring = calculate_card_score(dimensions)
    for field_name, value in scoring.dimensions.items():
        setattr(opportunity, field_name, value)

    opportunity.card_score = scoring.total_score
    opportunity.card_level = scoring.card_level
    opportunity.score_detail_json = scoring.detail
    opportunity.status = str(next_status).strip().lower()
    opportunity.is_active = _is_active_for_review(opportunity.review_status, opportunity.status)

    if "stage" in data:
        _sync_stage_state(
            opportunity,
            next_stage,
            datetime.now(timezone.utc),
            override_probability=data.get("probability"),
        )
    elif "probability" in data:
        opportunity.probability = data["probability"]

    if custom_fields is not None:
        opportunity.custom_fields = {**(opportunity.custom_fields or {}), **custom_fields}

    opportunity.custom_fields = _merge_custom_fields(opportunity.custom_fields or {}, data)
    if "solution_communication" in data:
        opportunity.custom_fields = _append_solution_communication_history(
            opportunity.custom_fields,
            previous_value=previous_solution_communication,
            next_value=opportunity.solution_communication,
            current_user=current_user,
            changed_at=datetime.now(timezone.utc),
        )

    await db.commit()
    await db.refresh(opportunity)
    await db.refresh(opportunity, ["owner"])
    return OpportunityOut.model_validate(opportunity)


@router.patch("/{opp_id}/stage", response_model=OpportunityOut, summary="Move opportunity stage")
async def move_stage(
    opp_id: UUID,
    payload: StageMoveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    opportunity = await _get_opp_or_403(opp_id, db, current_user)
    _sync_stage_state(opportunity, payload.stage, datetime.now(timezone.utc), override_closed_at=True)
    if opportunity.status != "archived":
        opportunity.status = derive_opportunity_status(opportunity.stage, opportunity.status)
        opportunity.is_active = _is_active_for_review(opportunity.review_status, opportunity.status)

    await db.commit()
    await db.refresh(opportunity)
    await db.refresh(opportunity, ["owner"])
    return OpportunityOut.model_validate(opportunity)


@router.delete("/{opp_id}", response_model=MessageResponse, summary="Delete opportunity")
async def delete_opportunity(
    opp_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    opportunity = await _get_opp_or_403(opp_id, db, current_user)
    await db.delete(opportunity)
    await db.commit()
    return MessageResponse(message="商机已删除")


async def _get_opp_or_404(opp_id: UUID, db: AsyncSession) -> Opportunity:
    result = await db.execute(
        select(Opportunity).where(Opportunity.id == str(opp_id)).options(selectinload(Opportunity.owner))
    )
    opportunity = result.scalar_one_or_none()
    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return opportunity


async def _get_opp_or_403(opp_id: UUID, db: AsyncSession, current_user: User) -> Opportunity:
    result = await db.execute(
        select(Opportunity).where(Opportunity.id == str(opp_id)).options(selectinload(Opportunity.owner))
    )
    opportunity = result.scalar_one_or_none()
    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    if not _can_edit_opportunity(current_user, opportunity):
        raise HTTPException(status_code=403, detail="You cannot modify another user's opportunity")
    return opportunity


def _can_edit_opportunity(current_user: User, opportunity: Opportunity) -> bool:
    if can_edit_owned_resource(current_user, opportunity.owner_id):
        return True
    custom_fields = opportunity.custom_fields or {}
    return owner_name_matches_user(current_user, custom_fields.get("owner_name_display"))
