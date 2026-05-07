"""
Card evaluation routes.
- POST /api/card-evaluations/evaluate
- POST /api/card-evaluations/transcribe
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas import CardEvaluateRequest, CardEvaluateResponse, CardTranscribeResponse
from app.core.security import get_current_user, is_admin_user
from app.db.session import get_db
from app.models import Lead, User
from app.services.ai_service import extract_scoring_dimensions_from_text, transcribe_audio
from app.services.card_evaluation_service import evaluate_card

router = APIRouter(prefix="/api/card-evaluations", tags=["card_evaluations"])

ALLOWED_AUDIO = {"audio/webm", "audio/mpeg", "audio/mp4", "audio/wav", "audio/ogg", "audio/x-m4a"}
MAX_AUDIO_SIZE = 25 * 1024 * 1024


def _dump_dimensions(model) -> dict[str, str | None] | None:
    if model is None:
        return None
    if isinstance(model, dict):
        return model
    if hasattr(model, "to_dimensions_dict"):
        return model.to_dimensions_dict()
    return model.model_dump()


def _has_dimension_values(dimensions: dict[str, str | None] | None) -> bool:
    if not dimensions:
        return False
    return any(value not in (None, "") for value in dimensions.values())


def _build_score_detail(payload: CardEvaluateRequest, result: dict) -> dict:
    return {
        "total_score": result["normalized_score"],
        "raw_score": result["raw_score"],
        "raw_max_score": result["raw_max_score"],
        "grade": result["grade"],
        "grade_label": result["grade_label"],
        "rating_desc": result["rating_desc"],
        "suggestion": result["suggestion"],
        "ai_dimensions": result.get("ai_dimensions"),
        "manual_dimensions": result.get("manual_dimensions"),
        "merged_dimensions": result["merged_dimensions"],
        "dimensions": result["dimensions"],
        "raw_text": payload.text,
        "analysis_mode": payload.analysis_mode,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def _append_value_evaluation_history(custom_fields: dict | None, score_detail: dict) -> dict:
    next_custom_fields = dict(custom_fields) if isinstance(custom_fields, dict) else {}
    history = next_custom_fields.get("value_evaluation_history")
    history = list(history) if isinstance(history, list) else []
    history.append(score_detail)
    next_custom_fields["value_evaluation_history"] = history
    next_custom_fields["last_value_evaluation_at"] = score_detail["evaluated_at"]
    return next_custom_fields


async def _find_existing_lead(
    db: AsyncSession,
    *,
    company_name: str,
    current_user: User,
) -> Lead | None:
    query = select(Lead).where(or_(Lead.company == company_name, Lead.name == company_name))
    if not is_admin_user(current_user):
        query = query.where(Lead.owner_id == str(current_user.id))
    result = await db.execute(query.order_by(Lead.updated_at.desc()))
    return result.scalars().first()


@router.post("/evaluate", response_model=CardEvaluateResponse, summary="Evaluate card value")
async def evaluate_card_view(
    payload: CardEvaluateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        manual_dimensions = _dump_dimensions(payload.manual_dimensions)
        ai_dimensions = None

        if payload.analysis_mode in {"ai", "hybrid"}:
            ai_dimensions = _dump_dimensions(payload.ai_dimensions)
            if not _has_dimension_values(ai_dimensions):
                ai_dimensions = await extract_scoring_dimensions_from_text(payload.text, payload.card_type)

        if payload.analysis_mode == "manual":
            result = evaluate_card(
                card_type=payload.card_type,
                manual_dimensions=manual_dimensions,
            )
        elif payload.analysis_mode == "ai":
            result = evaluate_card(
                card_type=payload.card_type,
                ai_dimensions=ai_dimensions,
            )
        else:
            result = evaluate_card(
                card_type=payload.card_type,
                ai_dimensions=ai_dimensions,
                manual_dimensions=manual_dimensions,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"evaluation failed: {str(exc)}") from exc

    if payload.save_to_lead:
        if payload.card_type != "A":
            raise HTTPException(status_code=400, detail="save_to_lead only supports A card evaluations")

        customer_name = str(payload.company or "").strip()
        if not customer_name:
            raise HTTPException(status_code=400, detail="company is required when save_to_lead is true")

        score_detail = _build_score_detail(payload, result)
        score = int(round(float(result["normalized_score"] or 0)))
        existing_lead = await _find_existing_lead(
            db,
            company_name=customer_name,
            current_user=current_user,
        )

        if existing_lead:
            existing_lead.score = score
            existing_lead.card_score = score
            existing_lead.card_level = result["grade"]
            existing_lead.score_detail_json = score_detail
            existing_lead.custom_fields = _append_value_evaluation_history(existing_lead.custom_fields, score_detail)
            for field_name, value in result["merged_dimensions"].items():
                setattr(existing_lead, field_name, value)
            lead = existing_lead
            result["merged_existing_lead"] = True
        else:
            lead = Lead(
                name=customer_name,
                company=customer_name,
                source="价值评估",
                status="new",
                score=score,
                card_score=score,
                card_level=result["grade"],
                owner_id=current_user.id,
                is_active=False,
                review_status="pending",
                score_detail_json=score_detail,
                custom_fields=_append_value_evaluation_history(
                    {
                        "created_from": "card_evaluation",
                        "card_type": payload.card_type,
                        "analysis_mode": payload.analysis_mode,
                    },
                    score_detail,
                ),
                **result["merged_dimensions"],
            )
            db.add(lead)
            result["merged_existing_lead"] = False

        await db.commit()
        result["lead_id"] = lead.id

    return CardEvaluateResponse.model_validate(result)


@router.post("/transcribe", response_model=CardTranscribeResponse, summary="Transcribe card audio")
async def transcribe_card_audio(
    audio: UploadFile = File(..., description="Supports webm/mp3/mp4/wav/ogg/m4a up to 25MB"),
):
    content_type = audio.content_type or ""
    if content_type not in ALLOWED_AUDIO:
        ext = audio.filename.rsplit(".", 1)[-1].lower() if audio.filename else ""
        if ext not in ("webm", "mp3", "mp4", "wav", "ogg", "m4a"):
            raise HTTPException(
                status_code=400,
                detail=f"unsupported audio format: {content_type}",
            )

    audio_bytes = await audio.read()
    if len(audio_bytes) > MAX_AUDIO_SIZE:
        raise HTTPException(status_code=413, detail="audio file exceeds 25MB limit")
    if len(audio_bytes) < 100:
        raise HTTPException(status_code=400, detail="audio file is too small")

    try:
        text = await transcribe_audio(audio_bytes, filename=audio.filename or "audio.webm")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"audio transcription failed: {str(exc)}") from exc

    return CardTranscribeResponse(
        text=text,
        duration_hint=f"{len(audio_bytes) / 1024:.1f}KB",
    )
