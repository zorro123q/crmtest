"""
Opportunity API routes.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import (
    apply_data_scope,
    can_edit_owned_resource,
    get_current_user,
    require_min_role,
)
from app.db.session import get_db
from app.models import Opportunity, User
from app.schemas import (
    OpportunityCreate,
    OpportunityOut,
    OpportunityUpdate,
    PaginatedResponse,
    StageMoveRequest,
)

router = APIRouter(prefix="/api/opportunities", tags=["商机"])

STAGE_DEFAULT_PROB = {
    "初步接洽": 20,
    "方案报价": 40,
    "合同谈判": 70,
    "赢单": 100,
    "输单": 0,
}


@router.get("", response_model=PaginatedResponse, summary="商机列表")
async def list_opportunities(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    stage: Optional[str] = None,
    owner_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Opportunity).options(selectinload(Opportunity.owner))
    query = apply_data_scope(query, Opportunity, current_user)

    if stage:
        query = query.where(Opportunity.stage == stage)
    if owner_id:
        query = query.where(Opportunity.owner_id == str(owner_id))

    total_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(total_query)).scalar()

    query = query.order_by(Opportunity.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    opps = result.scalars().all()

    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        data=[OpportunityOut.model_validate(opp) for opp in opps],
    )


@router.get("/funnel", summary="商机漏斗汇总")
async def funnel_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(
        Opportunity.stage,
        func.count(Opportunity.id).label("count"),
        func.coalesce(func.sum(Opportunity.amount), 0).label("total_amount"),
        func.avg(Opportunity.probability).label("avg_prob"),
    )
    query = apply_data_scope(query, Opportunity, current_user)
    query = query.group_by(Opportunity.stage)

    result = await db.execute(query)
    rows = result.all()

    stages_order = ["初步接洽", "方案报价", "合同谈判", "赢单", "输单"]
    data = {
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
                "count": data.get(stage_name, {}).get("count", 0),
                "total_amount": data.get(stage_name, {}).get("total_amount", 0),
                "avg_prob": data.get(stage_name, {}).get("avg_prob", 0),
            }
            for stage_name in stages_order
        ]
    }


@router.post("", response_model=OpportunityOut, status_code=201, summary="创建商机")
async def create_opportunity(
    payload: OpportunityCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    opp = Opportunity(
        **payload.model_dump(exclude_none=True),
        owner_id=current_user.id,
        probability=payload.probability or STAGE_DEFAULT_PROB.get(payload.stage, 20),
        stage_history=[{"stage": payload.stage, "entered_at": datetime.now(timezone.utc).isoformat()}],
    )
    db.add(opp)
    await db.flush()
    await db.refresh(opp, ["owner"])
    return OpportunityOut.model_validate(opp)


@router.patch("/{opp_id}", response_model=OpportunityOut, summary="更新商机")
async def update_opportunity(
    opp_id: UUID,
    payload: OpportunityUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    opp = await _get_opp_or_403(opp_id, db, current_user)
    data = payload.model_dump(exclude_none=True)
    for key, value in data.items():
        setattr(opp, key, value)
    await db.flush()
    await db.refresh(opp, ["owner"])
    return OpportunityOut.model_validate(opp)


@router.patch("/{opp_id}/stage", response_model=OpportunityOut, summary="看板拖拽更新阶段")
async def move_stage(
    opp_id: UUID,
    payload: StageMoveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    opp = await _get_opp_or_403(opp_id, db, current_user)
    now = datetime.now(timezone.utc)

    history = list(opp.stage_history or [])
    if history:
        last = history[-1]
        if "exited_at" not in last:
            entered = datetime.fromisoformat(last["entered_at"])
            last["exited_at"] = now.isoformat()
            last["days"] = max(0, (now - entered).days)

    history.append({"stage": payload.stage, "entered_at": now.isoformat()})
    opp.stage_history = history
    opp.stage = payload.stage
    opp.probability = STAGE_DEFAULT_PROB.get(payload.stage, opp.probability)

    if payload.stage in ("赢单", "输单"):
        opp.closed_at = now

    await db.flush()
    await db.refresh(opp, ["owner"])
    return OpportunityOut.model_validate(opp)


@router.delete("/{opp_id}", status_code=204, summary="删除商机")
async def delete_opportunity(
    opp_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_min_role("manager")),
):
    result = await db.execute(select(Opportunity).where(Opportunity.id == str(opp_id)))
    opp = result.scalar_one_or_none()
    if not opp:
        raise HTTPException(status_code=404, detail="商机不存在")
    await db.delete(opp)


async def _get_opp_or_403(opp_id: UUID, db: AsyncSession, current_user: User) -> Opportunity:
    result = await db.execute(
        select(Opportunity).where(Opportunity.id == str(opp_id)).options(selectinload(Opportunity.owner))
    )
    opp = result.scalar_one_or_none()
    if not opp:
        raise HTTPException(status_code=404, detail="商机不存在")
    if not can_edit_owned_resource(current_user, opp.owner_id):
        raise HTTPException(status_code=403, detail="无权操作他人商机")
    return opp
