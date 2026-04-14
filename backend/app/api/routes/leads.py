"""
Lead API routes.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import can_edit_owned_resource, get_current_user
from app.db.session import get_db
from app.models import Lead, User
from app.schemas import LeadCreate, LeadOut, LeadUpdate

router = APIRouter(prefix="/api/leads", tags=["线索"])


@router.get("", response_model=list[LeadOut], summary="线索列表")
async def list_leads(
    status: Optional[str] = Query(None),
    owner_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = select(Lead).options(selectinload(Lead.owner)).order_by(Lead.created_at.desc())

    if status:
        query = query.where(Lead.status == status)
    if owner_id:
        query = query.where(Lead.owner_id == str(owner_id))

    result = await db.execute(query)
    leads = result.scalars().all()
    return [LeadOut.model_validate(lead) for lead in leads]


@router.post("", response_model=LeadOut, status_code=201, summary="创建线索")
async def create_lead(
    payload: LeadCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    lead = Lead(
        **payload.model_dump(exclude_none=True),
        owner_id=current_user.id,
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead, ["owner"])
    return LeadOut.model_validate(lead)


@router.patch("/{lead_id}", response_model=LeadOut, summary="更新线索")
async def update_lead(
    lead_id: UUID,
    payload: LeadUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    lead = await _get_lead_or_403(lead_id, db, current_user)
    data = payload.model_dump(exclude_none=True)
    for key, value in data.items():
        setattr(lead, key, value)
    await db.flush()
    await db.refresh(lead, ["owner"])
    return LeadOut.model_validate(lead)


async def _get_lead_or_403(lead_id: UUID, db: AsyncSession, current_user: User) -> Lead:
    result = await db.execute(select(Lead).where(Lead.id == str(lead_id)).options(selectinload(Lead.owner)))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在")
    if not can_edit_owned_resource(current_user, lead.owner_id):
        raise HTTPException(status_code=403, detail="无权操作他人线索")
    return lead
