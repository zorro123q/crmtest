"""
Public card evaluation routes.
- POST /api/card-evaluations/evaluate
- POST /api/card-evaluations/transcribe
"""

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.schemas import CardEvaluateRequest, CardEvaluateResponse, CardTranscribeResponse
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


@router.post("/evaluate", response_model=CardEvaluateResponse, summary="Evaluate card value")
async def evaluate_card_view(payload: CardEvaluateRequest):
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
