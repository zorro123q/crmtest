"""
公开卡片评估接口
- POST /api/card-evaluations/evaluate   -> 客户意向 / 商机价值评分
- POST /api/card-evaluations/transcribe -> paraformer-v2 语音转文字
"""
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.schemas import CardEvaluateRequest, CardEvaluateResponse, CardTranscribeResponse
from app.services.ai_service import transcribe_audio
from app.services.card_evaluation_service import evaluate_card

router = APIRouter(prefix="/api/card-evaluations", tags=["卡片评估"])

ALLOWED_AUDIO = {"audio/webm", "audio/mpeg", "audio/mp4", "audio/wav", "audio/ogg", "audio/x-m4a"}
MAX_AUDIO_SIZE = 25 * 1024 * 1024


@router.post("/evaluate", response_model=CardEvaluateResponse, summary="评估客户意向或商机价值")
async def evaluate_card_view(payload: CardEvaluateRequest):
    try:
        result = evaluate_card(
            card_type=payload.card_type,
            text=payload.text,
            industry=payload.industry,
            amount=payload.amount,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"评分失败：{str(e)}")

    return CardEvaluateResponse.model_validate(result)


@router.post("/transcribe", response_model=CardTranscribeResponse, summary="使用 paraformer-v2 转写卡片录音")
async def transcribe_card_audio(
    audio: UploadFile = File(..., description="支持 webm/mp3/mp4/wav/ogg/m4a，最大 25MB"),
):
    content_type = audio.content_type or ""
    if content_type not in ALLOWED_AUDIO:
        ext = audio.filename.rsplit(".", 1)[-1].lower() if audio.filename else ""
        if ext not in ("webm", "mp3", "mp4", "wav", "ogg", "m4a"):
            raise HTTPException(
                status_code=400,
                detail=f"不支持的音频格式：{content_type}，请使用 webm/mp3/wav/ogg/m4a",
            )

    audio_bytes = await audio.read()
    if len(audio_bytes) > MAX_AUDIO_SIZE:
        raise HTTPException(status_code=413, detail="音频文件超过 25MB 限制")
    if len(audio_bytes) < 100:
        raise HTTPException(status_code=400, detail="音频文件过小，请重新录制")

    try:
        text = await transcribe_audio(audio_bytes, filename=audio.filename or "audio.webm")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"paraformer-v2 转写失败：{str(e)}")

    return CardTranscribeResponse(
        text=text,
        duration_hint=f"{len(audio_bytes) / 1024:.1f}KB",
    )
