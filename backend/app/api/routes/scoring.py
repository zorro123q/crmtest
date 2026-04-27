"""
Scoring metadata routes.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user
from app.models import User
from app.services.scoring_service import scoring_options_payload

router = APIRouter(prefix="/api/scoring", tags=["scoring"])


@router.get("/options", summary="Scoring field options")
async def scoring_options(
    card_type: Literal["A", "B"] = Query("A"),
    _: User = Depends(get_current_user),
):
    return {
        "card_type": card_type,
        "fields": scoring_options_payload(card_type),
    }
