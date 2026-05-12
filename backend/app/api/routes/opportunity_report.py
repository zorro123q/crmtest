"""
Opportunity report API routes.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import get_current_user, is_admin_user, require_admin
from app.db.session import get_db
from app.models import Opportunity, User
from app.schemas import OpportunityReportResponse, OpportunityReportSummary
from app.services.opportunity_report_service import build_report_rows, build_target_report, build_trend_report, summarize_report_rows
from app.services.report_email_config_service import (
    get_report_email_config,
    update_report_email_config,
)
from app.services.report_email_service import (
    ReportEmailSMTPNotConfigured,
    ReportEmailSendError,
    send_weekly_opportunity_report,
)
from app.services.report_scheduler_service import sync_report_scheduler

router = APIRouter(prefix="/api/opportunity-report", tags=["opportunity-report"])


class ReportEmailConfigPayload(BaseModel):
    enabled: bool = False
    recipients: list[str] | str | None = Field(default_factory=list)
    subject_prefix: str | None = "SalesPilot CRM 商机通报"
    pioneer_members: list[str] | str | None = Field(default_factory=list)
    charge_members: list[str] | str | None = Field(default_factory=list)
    schedule_weekday: str | None = "fri"
    schedule_hour: int | None = 18
    schedule_minute: int | None = 0
    schedule_timezone: str | None = "Asia/Shanghai"


def _row_to_schema(row) -> OpportunityReportSummary:
    return OpportunityReportSummary.model_validate(
        {
            "owner_id": row.owner_id,
            "owner_username": row.owner_username,
            "total_count": row.total_count,
            "following_count": row.following_count,
            "won_count": row.won_count,
            "high_priority_count": row.high_priority_count,
            "this_week_new": row.this_week_new,
            "this_month_new": row.this_month_new,
        }
    )


def _empty_user_summary(owner_id: str | None, owner_username: str) -> OpportunityReportSummary:
    return OpportunityReportSummary(
        owner_id=owner_id,
        owner_username=owner_username,
        total_count=0,
        following_count=0,
        won_count=0,
        high_priority_count=0,
        this_week_new=0,
        this_month_new=0,
    )


def _normalize_optional_uuid(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)

    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


async def _has_review_status_column(db: AsyncSession) -> bool:
    try:
        result = await db.execute(text("SHOW COLUMNS FROM opportunities LIKE 'review_status'"))
        return result.first() is not None
    except SQLAlchemyError:
        return False


async def _base_report_query(db: AsyncSession):
    query = select(Opportunity).options(selectinload(Opportunity.owner)).order_by(Opportunity.created_at.desc())
    if await _has_review_status_column(db):
        query = query.where(Opportunity.review_status == "approved")
    return query


@router.get("/email-config", summary="Get opportunity report email config")
async def report_email_config(_: User = Depends(require_admin())):
    try:
        return get_report_email_config()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/email-config", summary="Update opportunity report email config")
async def update_email_config(
    payload: ReportEmailConfigPayload,
    _: User = Depends(require_admin()),
):
    try:
        config = update_report_email_config(payload)
        sync_report_scheduler()
        return config
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _send_report_email(db: AsyncSession) -> dict:
    try:
        return await send_weekly_opportunity_report(db)
    except ReportEmailSMTPNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ReportEmailSendError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/send-email", summary="Send opportunity report email now")
async def send_report_email(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin()),
):
    return await _send_report_email(db)


@router.post("/send-email-test", summary="Send opportunity report test email now")
async def send_report_email_test(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin()),
):
    return await _send_report_email(db)


@router.get("/me", response_model=OpportunityReportResponse, summary="Current user's opportunity report")
async def my_opportunity_report(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = await _base_report_query(db)
    result = await db.execute(query.where(Opportunity.owner_id == str(current_user.id)))
    opportunities = result.scalars().all()
    rows = build_report_rows(opportunities)
    summary = _row_to_schema(rows[0]) if rows else _empty_user_summary(str(current_user.id), current_user.username)
    return OpportunityReportResponse(scope="me", summary=summary, reports=[summary])


@router.get("/target-table", summary="Opportunity target vs actual report")
async def opportunity_target_table(
    user_id: UUID | None = Query(None),
    pioneer_leader_names: list[str] | None = Query(None),
    charge_leader_names: list[str] | None = Query(None),
    pioneer_members: list[str] | None = Query(None),
    charge_members: list[str] | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    is_admin = is_admin_user(current_user)
    target_user_id = _normalize_optional_uuid(user_id)

    if target_user_id and not is_admin and target_user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="You can only view your own opportunity report")

    review_filter_applied = await _has_review_status_column(db)
    query = select(Opportunity).options(selectinload(Opportunity.owner)).order_by(Opportunity.created_at.desc())
    if review_filter_applied:
        query = query.where(Opportunity.review_status == "approved")

    if target_user_id:
        query = query.where(Opportunity.owner_id == target_user_id)
        scope = "user"
    else:
        scope = "all"

    result = await db.execute(query)
    report = build_target_report(
        result.scalars().all(),
        pioneer_leader_names=pioneer_leader_names or [],
        charge_leader_names=charge_leader_names or [],
        pioneer_members=pioneer_members or [],
        charge_members=charge_members or [],
    )
    return {
        "scope": scope,
        "user_id": target_user_id,
        "review_filter_applied": review_filter_applied,
        "old_customer_new_business": report["old_customer_new_business"],
        "new_customer_business": report["new_customer_business"],
    }


@router.get("/trend", summary="Opportunity trend report for charts")
async def opportunity_trend(
    weeks: int = Query(12, ge=4, le=52),
    user_id: UUID | None = Query(None),
    pioneer_leader_names: list[str] | None = Query(None),
    charge_leader_names: list[str] | None = Query(None),
    pioneer_members: list[str] | None = Query(None),
    charge_members: list[str] | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    is_admin = is_admin_user(current_user)
    target_user_id = _normalize_optional_uuid(user_id)

    if target_user_id and not is_admin and target_user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="You can only view your own opportunity report")

    review_filter_applied = await _has_review_status_column(db)
    query = select(Opportunity).options(selectinload(Opportunity.owner)).order_by(Opportunity.created_at.asc())
    if review_filter_applied:
        query = query.where(Opportunity.review_status == "approved")

    if target_user_id:
        query = query.where(Opportunity.owner_id == target_user_id)

    result = await db.execute(query)
    trend = build_trend_report(
        result.scalars().all(),
        weeks=weeks,
        pioneer_leader_names=pioneer_leader_names or [],
        charge_leader_names=charge_leader_names or [],
        pioneer_members=pioneer_members or [],
        charge_members=charge_members or [],
    )
    return trend


@router.get("", response_model=OpportunityReportResponse, summary="Opportunity report by user or all users")
async def opportunity_report(
    user_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    is_admin = is_admin_user(current_user)
    target_user_id = _normalize_optional_uuid(user_id)

    if target_user_id and not is_admin and target_user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="You can only view your own opportunity report")

    query = await _base_report_query(db)
    if target_user_id:
        query = query.where(Opportunity.owner_id == target_user_id)

    result = await db.execute(query)
    opportunities = result.scalars().all()
    rows = build_report_rows(opportunities)

    if target_user_id:
        if rows:
            summary = _row_to_schema(rows[0])
        else:
            user_result = await db.execute(select(User).where(User.id == target_user_id))
            target_user = user_result.scalar_one_or_none()
            owner_username = target_user.username if target_user else "Unknown user"
            summary = _empty_user_summary(target_user_id or str(current_user.id), owner_username)
        return OpportunityReportResponse(scope="user", summary=summary, reports=[summary])

    summary_row = summarize_report_rows(rows, owner_label="All Users")
    return OpportunityReportResponse(
        scope="all",
        summary=_row_to_schema(summary_row),
        reports=[_row_to_schema(row) for row in rows],
    )
