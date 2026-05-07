"""
Opportunity report API routes.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import get_current_user, is_admin_user
from app.db.session import get_db
from app.models import Opportunity, User
from app.schemas import OpportunityReportResponse, OpportunityReportSummary
from app.services.opportunity_report_service import build_report_rows, build_target_report, summarize_report_rows

router = APIRouter(prefix="/api/opportunity-report", tags=["opportunity-report"])


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
    elif is_admin:
        scope = "all"
    else:
        query = query.where(Opportunity.owner_id == str(current_user.id))
        scope = "me"

    result = await db.execute(query)
    report = build_target_report(
        result.scalars().all(),
        pioneer_members=pioneer_members or [],
        charge_members=charge_members or [],
    )
    return {
        "scope": scope,
        "user_id": target_user_id or (None if is_admin and scope == "all" else str(current_user.id)),
        "review_filter_applied": review_filter_applied,
        "old_customer_new_business": report["old_customer_new_business"],
        "new_customer_business": report["new_customer_business"],
    }


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
    elif not is_admin:
        query = query.where(Opportunity.owner_id == str(current_user.id))

    result = await db.execute(query)
    opportunities = result.scalars().all()
    rows = build_report_rows(opportunities)

    if target_user_id or not is_admin:
        if rows:
            summary = _row_to_schema(rows[0])
        else:
            owner_username = current_user.username
            if is_admin and target_user_id and target_user_id != str(current_user.id):
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
