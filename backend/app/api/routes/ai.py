"""
AI routes.
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models import Opportunity, User
from app.schemas import AIParseRequest, AIParseResponse, OpportunityCreate
from app.services.ai_service import parse_crm_text, transcribe_audio
from app.services.crm_rules_service import DEFAULT_OPPORTUNITY_STAGE, derive_opportunity_status, status_to_active
from app.services.scoring_service import calculate_card_score

router = APIRouter(prefix="/api/ai", tags=["AI"])

ALLOWED_AUDIO = {"audio/webm", "audio/mpeg", "audio/mp4", "audio/wav", "audio/ogg", "audio/x-m4a"}
MAX_AUDIO_SIZE = 25 * 1024 * 1024


@router.post("/parse", response_model=AIParseResponse, summary="Parse free text into CRM fields")
async def parse_text(
    payload: AIParseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        result = await parse_crm_text(payload.text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI parsing failed: {str(exc)}") from exc

    usage = result.pop("_usage", None)
    opportunity_id = None

    if payload.save_to_opportunity:
        create_data = OpportunityCreate(
            name=f"{result.get('customer_name', 'AI customer')} - AI import",
            stage=result.get("stage", DEFAULT_OPPORTUNITY_STAGE),
            amount=result.get("deal_value") or None,
            ai_confidence=result.get("confidence_score"),
            ai_raw_text=payload.text,
            ai_extracted=result,
        )
        data = create_data.model_dump(exclude_unset=True)
        scoring = calculate_card_score(data)
        status = derive_opportunity_status(data.get("stage", DEFAULT_OPPORTUNITY_STAGE), data.get("status"))

        opportunity = Opportunity(
            name=data["name"],
            stage=data.get("stage", DEFAULT_OPPORTUNITY_STAGE),
            status=status,
            is_active=status_to_active(status),
            amount=data.get("amount"),
            card_score=scoring.total_score,
            card_level=scoring.card_level,
            score_detail_json=scoring.detail,
            ai_confidence=data.get("ai_confidence"),
            ai_raw_text=data.get("ai_raw_text"),
            ai_extracted=data.get("ai_extracted") or {},
            owner_id=current_user.id,
            **scoring.dimensions,
        )
        db.add(opportunity)
        await db.commit()
        opportunity_id = opportunity.id

    return AIParseResponse(
        customer_name=result.get("customer_name", "Unknown"),
        deal_value=float(result.get("deal_value") or 0),
        stage=result.get("stage", DEFAULT_OPPORTUNITY_STAGE),
        key_needs=result.get("key_needs", []),
        next_step=result.get("next_step", "Unknown"),
        confidence_score=float(result.get("confidence_score", 0.5)),
        usage=usage,
        opportunity_id=opportunity_id,
    )


@router.post("/transcribe", summary="Transcribe audio")
async def transcribe(
    audio: UploadFile = File(..., description="Supports webm/mp3/mp4/wav/ogg/m4a up to 25MB"),
    _: User = Depends(get_current_user),
):
    content_type = audio.content_type or ""
    if content_type not in ALLOWED_AUDIO:
        ext = audio.filename.rsplit(".", 1)[-1].lower() if audio.filename else ""
        if ext not in ("webm", "mp3", "mp4", "wav", "ogg", "m4a"):
            raise HTTPException(status_code=400, detail=f"Unsupported audio format: {content_type}")

    audio_bytes = await audio.read()
    if len(audio_bytes) > MAX_AUDIO_SIZE:
        raise HTTPException(status_code=413, detail="Audio file exceeds the 25MB limit")
    if len(audio_bytes) < 100:
        raise HTTPException(status_code=400, detail="Audio file is too small")

    try:
        text = await transcribe_audio(audio_bytes, filename=audio.filename or "audio.webm")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Audio transcription failed: {str(exc)}") from exc

    return {
        "text": text,
        "duration_hint": f"{len(audio_bytes) / 1024:.1f}KB",
    }
