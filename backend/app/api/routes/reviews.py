"""
Administrator review routes for leads and opportunities.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin
from app.db.session import get_db
from app.models import Lead, Opportunity, User
from app.schemas import BatchReviewRequest, BatchReviewResponse

router = APIRouter(prefix="/api/admin/reviews", tags=["admin-reviews"])

REVIEW_MODELS = {
    "lead": Lead,
    "opportunity": Opportunity,
}


@router.post("/batch", response_model=BatchReviewResponse, summary="Batch approve or reject CRM records")
async def batch_review(
    payload: BatchReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin()),
):
    model = REVIEW_MODELS[payload.object_type]
    ids = [str(item_id) for item_id in payload.ids]
    reviewed_at = datetime.now(timezone.utc)

    result = await db.execute(select(model).where(model.id.in_(ids)))
    records = result.scalars().all()
    if not records:
        raise HTTPException(status_code=404, detail="No matching records found")

    is_approved = payload.action == "approved"
    for record in records:
        record.review_status = payload.action
        record.review_by = str(current_user.id)
        record.review_at = reviewed_at
        record.review_remark = payload.remark
        record.is_active = is_approved

    await db.commit()

    return BatchReviewResponse(
        object_type=payload.object_type,
        action=payload.action,
        reviewed_count=len(records),
        review_by=current_user.id,
        review_at=reviewed_at,
    )
