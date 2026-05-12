"""
Check-in API routes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import get_current_user, is_admin_user
from app.db.session import get_db
from app.models import CheckIn, Opportunity, User
from app.schemas import PaginatedResponse

router = APIRouter(prefix="/api/checkins", tags=["checkins"])


class CheckInCreate(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    address: str | None = None
    location_name: str | None = None
    checkin_type: str = "visit"
    remark: str | None = None
    customer_name: str | None = None
    opportunity_id: UUID | None = None
    images: list[str] = Field(default_factory=list)


class CheckInUpdate(BaseModel):
    remark: str | None = None
    location_name: str | None = None


class CheckInResponse(BaseModel):
    id: str
    user_id: str
    username: str
    opportunity_id: str | None = None
    customer_name: str | None = None
    latitude: float
    longitude: float
    address: str | None = None
    location_name: str | None = None
    checkin_type: str
    remark: str | None = None
    images: list[str] = Field(default_factory=list)
    created_at: str

    class Config:
        from_attributes = True


def _format_checkin(checkin: CheckIn) -> dict:
    return {
        "id": checkin.id,
        "user_id": checkin.user_id,
        "username": checkin.user.username if checkin.user else "未知用户",
        "opportunity_id": checkin.opportunity_id,
        "customer_name": checkin.customer_name,
        "latitude": float(checkin.latitude),
        "longitude": float(checkin.longitude),
        "address": checkin.address,
        "location_name": checkin.location_name,
        "checkin_type": checkin.checkin_type,
        "remark": checkin.remark,
        "images": checkin.images or [],
        "created_at": checkin.created_at.isoformat() if checkin.created_at else None,
    }


@router.post("", response_model=CheckInResponse, status_code=201, summary="Create check-in")
async def create_checkin(
    payload: CheckInCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    checkin = CheckIn(
        user_id=current_user.id,
        latitude=payload.latitude,
        longitude=payload.longitude,
        address=payload.address,
        location_name=payload.location_name,
        checkin_type=payload.checkin_type,
        remark=payload.remark,
        customer_name=payload.customer_name,
        opportunity_id=str(payload.opportunity_id) if payload.opportunity_id else None,
        images=payload.images,
    )
    db.add(checkin)
    await db.commit()
    await db.refresh(checkin)
    await db.refresh(checkin, ["user"])
    return _format_checkin(checkin)


@router.get("", summary="List check-ins")
async def list_checkins(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: Optional[UUID] = None,
    opportunity_id: Optional[UUID] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    is_admin = is_admin_user(current_user)

    query = select(CheckIn).options(selectinload(CheckIn.user))

    # 非管理员只能查看自己的打卡记录
    if not is_admin:
        query = query.where(CheckIn.user_id == current_user.id)
    elif user_id:
        query = query.where(CheckIn.user_id == str(user_id))

    if opportunity_id:
        query = query.where(CheckIn.opportunity_id == str(opportunity_id))

    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
            query = query.where(CheckIn.created_at >= start_dt)
        except ValueError:
            pass

    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
            query = query.where(CheckIn.created_at <= end_dt)
        except ValueError:
            pass

    total_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(total_query)).scalar() or 0

    result = await db.execute(
        query.order_by(CheckIn.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    checkins = result.scalars().all()

    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        data=[_format_checkin(item) for item in checkins],
    )


@router.get("/my-today", summary="Get my today's check-ins")
async def my_today_checkins(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start.replace(hour=23, minute=59, second=59, microsecond=999999)

    query = (
        select(CheckIn)
        .options(selectinload(CheckIn.user))
        .where(CheckIn.user_id == current_user.id)
        .where(CheckIn.created_at >= today_start)
        .where(CheckIn.created_at <= today_end)
        .order_by(CheckIn.created_at.desc())
    )

    result = await db.execute(query)
    checkins = result.scalars().all()

    return {
        "date": today_start.strftime("%Y-%m-%d"),
        "count": len(checkins),
        "records": [_format_checkin(item) for item in checkins],
    }


@router.get("/stats", summary="Get check-in statistics")
async def checkin_stats(
    user_id: Optional[UUID] = None,
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    is_admin = is_admin_user(current_user)
    target_user_id = str(user_id) if user_id and is_admin else current_user.id

    start_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    from datetime import timedelta
    start_date = start_date - timedelta(days=days)

    query = (
        select(
            func.date(CheckIn.created_at).label("date"),
            func.count(CheckIn.id).label("count"),
        )
        .where(CheckIn.user_id == target_user_id)
        .where(CheckIn.created_at >= start_date)
        .group_by(func.date(CheckIn.created_at))
        .order_by(func.date(CheckIn.created_at))
    )

    result = await db.execute(query)
    rows = result.all()

    return {
        "user_id": target_user_id,
        "days": days,
        "stats": [{"date": str(row.date), "count": row.count} for row in rows],
    }


@router.get("/{checkin_id}", summary="Get check-in detail")
async def get_checkin(
    checkin_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        select(CheckIn)
        .options(selectinload(CheckIn.user))
        .where(CheckIn.id == str(checkin_id))
    )
    result = await db.execute(query)
    checkin = result.scalar_one_or_none()

    if not checkin:
        raise HTTPException(status_code=404, detail="Check-in not found")

    is_admin = is_admin_user(current_user)
    if not is_admin and checkin.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only view your own check-in")

    return _format_checkin(checkin)


@router.delete("/{checkin_id}", summary="Delete check-in")
async def delete_checkin(
    checkin_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(CheckIn).where(CheckIn.id == str(checkin_id))
    result = await db.execute(query)
    checkin = result.scalar_one_or_none()

    if not checkin:
        raise HTTPException(status_code=404, detail="Check-in not found")

    is_admin = is_admin_user(current_user)
    if not is_admin and checkin.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only delete your own check-in")

    await db.delete(checkin)
    await db.commit()
    return {"message": "打卡记录已删除"}
