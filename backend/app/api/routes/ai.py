"""
API 路由：AI 模块
POST /api/ai/parse       →文本结构化解析
POST /api/ai/transcribe  → DashScope paraformer-v2 音频转写
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models import User, Opportunity
from app.schemas import AIParseRequest, AIParseResponse, OpportunityCreate
from app.services.ai_service import parse_crm_text, transcribe_audio

router = APIRouter(prefix="/api/ai", tags=["AI 能力"])

# 允许上传的音频格式
ALLOWED_AUDIO = {"audio/webm", "audio/mpeg", "audio/mp4", "audio/wav", "audio/ogg", "audio/x-m4a"}
MAX_AUDIO_SIZE = 25 * 1024 * 1024  # 25MB（当前应用侧限制）


@router.post("/parse", response_model=AIParseResponse, summary="GPT-4o 文本结构化解析")
async def parse_text(
    payload: AIParseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    核心 AI 录入接口：
    1. 接收原始语音转写文本
    2. 调用 GPT-4o，按 CRM Schema 结构化
    3. 可选：直接保存为商机（save_to_opportunity=true）
    """
    try:
        result = await parse_crm_text(payload.text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI 解析失败：{str(e)}")

    usage = result.pop("_usage", None)
    opp_id = None

    if payload.save_to_opportunity:
        # 自动创建商机
        create_data = OpportunityCreate(
            name=f"{result['customer_name']} - AI录入",
            stage=result.get("stage", "初步接洽"),
            amount=result.get("deal_value") or None,
            ai_confidence=result.get("confidence_score"),
            ai_raw_text=payload.text,
            ai_extracted=result,
        )
        opp = Opportunity(
            **create_data.model_dump(exclude_none=True),
            owner_id=current_user.id,
        )
        db.add(opp)
        await db.flush()
        opp_id = opp.id

    return AIParseResponse(
        customer_name=result.get("customer_name", "Unknown"),
        deal_value=float(result.get("deal_value") or 0),
        stage=result.get("stage", "初步接洽"),
        key_needs=result.get("key_needs", []),
        next_step=result.get("next_step", "Unknown"),
        confidence_score=float(result.get("confidence_score", 0.5)),
        usage=usage,
        opportunity_id=opp_id,
    )


@router.post("/transcribe", summary="DashScope paraformer-v2 音频转写")
async def transcribe(
    audio: UploadFile = File(..., description="支持 webm/mp3/mp4/wav/ogg/m4a，最大 25MB"),
    current_user: User = Depends(get_current_user),
):
    """
    DashScope paraformer-v2 转写接口
    前端：MediaRecorder 录音 → 发送 multipart/form-data → 返回文字
    """
    # 校验文件类型
    content_type = audio.content_type or ""
    if content_type not in ALLOWED_AUDIO:
        # 部分浏览器 content_type 不准确，改用扩展名二次判断
        ext = audio.filename.rsplit(".", 1)[-1].lower() if audio.filename else ""
        if ext not in ("webm", "mp3", "mp4", "wav", "ogg", "m4a"):
            raise HTTPException(
                status_code=400,
                detail=f"不支持的音频格式：{content_type}，请使用 webm/mp3/wav"
            )

    # 校验文件大小
    audio_bytes = await audio.read()
    if len(audio_bytes) > MAX_AUDIO_SIZE:
        raise HTTPException(status_code=413, detail="音频文件超过 25MB 限制")

    if len(audio_bytes) < 100:
        raise HTTPException(status_code=400, detail="音频文件过小，请重新录制")

    try:
        text = await transcribe_audio(audio_bytes, filename=audio.filename or "audio.webm")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"paraformer-v2 转写失败：{str(e)}")

    return {
        "text": text,
        "duration_hint": f"{len(audio_bytes) / 1024:.1f}KB",
    }
