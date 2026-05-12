"""
AI routes.
"""

import base64
import hashlib
import hmac
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_user
from app.db.session import get_db
from app.models import Lead, Opportunity, User
from app.schemas import AIParseRequest, AIParseResponse
from app.services.ai_service import parse_crm_text, transcribe_audio
from app.services.crm_rules_service import (
    DEFAULT_OPPORTUNITY_STAGE,
    NEGOTIATION_STAGE,
    QUOTE_STAGE,
    WON_STAGE,
    derive_opportunity_status,
)
from app.services.scoring_service import calculate_card_score

router = APIRouter(prefix="/api/ai", tags=["AI"])

ALLOWED_AUDIO = {"audio/webm", "audio/mpeg", "audio/mp4", "audio/wav", "audio/ogg", "audio/x-m4a"}
MAX_AUDIO_SIZE = 25 * 1024 * 1024
REALTIME_SAMPLE_RATE = 16000
REALTIME_AUDIO_CHUNK_SIZE = 1280
REALTIME_AUDIO_CHUNK_INTERVAL_MS = 40
REALTIME_SIGNED_URL_TTL_SECONDS = 60


def _normalize_realtime_ws_url(ws_url: str) -> str:
    url = str(ws_url or "").strip()
    if url in {"wss://multirobot-test.kxjlcc.com", "wss://multirobot-test.kxjlcc.com/"}:
        return "wss://multirobot-test.kxjlcc.com:18888/"
    if url in {"wss://multirobot-test.kxjlcc.com:18888", "wss://multirobot-test.kxjlcc.com:18888/"}:
        return "wss://multirobot-test.kxjlcc.com:18888/"
    return url.split("?", 1)[0].rstrip("/") + "/"


def _build_xfyun_realtime_url() -> tuple[str, int]:
    app_id = str(settings.XFYUN_REALTIME_APP_ID or "").strip()
    api_key = str(settings.XFYUN_REALTIME_API_KEY or "").strip()
    token = str(settings.XFYUN_REALTIME_TOKEN or "").strip()
    ws_url = _normalize_realtime_ws_url(settings.XFYUN_REALTIME_WS_URL)

    if not app_id or not api_key or not ws_url:
        raise HTTPException(
            status_code=503,
            detail="讯飞实时转写未配置，请设置 XFYUN_REALTIME_APP_ID / XFYUN_REALTIME_API_KEY / XFYUN_REALTIME_WS_URL",
        )
    if not ws_url.startswith(("ws://", "wss://")):
        raise HTTPException(status_code=503, detail="XFYUN_REALTIME_WS_URL 必须以 ws:// 或 wss:// 开头")

    ts = str(int(time.time()))
    md5_text = hashlib.md5((app_id + ts).encode("utf-8")).hexdigest()
    signa = base64.b64encode(
        hmac.new(api_key.encode("utf-8"), md5_text.encode("utf-8"), hashlib.sha1).digest()
    ).decode("utf-8")

    params = {
        "appid": app_id,
        "ts": ts,
        "signa": signa,
        "token": token,
    }
    base_url = ws_url.split("?", 1)[0].rstrip("/") + "/"
    return f"{base_url}?{urlencode(params)}", int(ts) + REALTIME_SIGNED_URL_TTL_SECONDS


def _clean_string(value) -> str:
    return str(value or "").strip()


def _none_if_blank(value):
    text = _clean_string(value)
    return text or None


def _has_meaningful_text(value) -> bool:
    return bool(_clean_string(value))


def _is_negative_progress(value) -> bool:
    return _clean_string(value) in {"未启动", "暂无", "无", "否", "没有"}


def _derive_stage_from_ai_opportunity(data: dict) -> str:
    if _clean_string(data.get("contract_signed")) == "是":
        return WON_STAGE
    if _has_meaningful_text(data.get("contract_negotiation")) and not _is_negative_progress(data.get("contract_negotiation")):
        return NEGOTIATION_STAGE
    if (
        _has_meaningful_text(data.get("solution_communication"))
        or _has_meaningful_text(data.get("poc_status"))
        or _clean_string(data.get("key_person_approved")) == "是"
    ):
        return QUOTE_STAGE
    return DEFAULT_OPPORTUNITY_STAGE


def _build_lead_custom_fields(lead_data: dict, parsed_result: dict) -> dict:
    custom_fields = dict(lead_data)
    custom_fields.update(
        {
            "created_from": "ai_input",
            "ai_confidence_score": parsed_result.get("confidence_score"),
            "ai_missing_fields": parsed_result.get("missing_fields") or [],
            "ai_suggestion": parsed_result.get("suggestion") or "",
        }
    )
    return custom_fields


def _build_opportunity_custom_fields(opportunity_data: dict, parsed_result: dict) -> dict:
    customer_name = _clean_string(opportunity_data.get("customer_name"))
    product_name = _clean_string(opportunity_data.get("product_name"))
    requirement_desc = _clean_string(opportunity_data.get("requirement_desc"))
    opportunity_level = _clean_string(opportunity_data.get("opportunity_level"))
    bid_probability = _clean_string(opportunity_data.get("bid_probability"))
    key_person_approved = _clean_string(opportunity_data.get("key_person_approved"))
    contract_signed = _clean_string(opportunity_data.get("contract_signed"))

    custom_fields = dict(opportunity_data)
    custom_fields.update(
        {
            "created_from": "ai_input",
            "company": customer_name,
            "product": product_name,
            "level": opportunity_level,
            "bcard": bid_probability,
            "demand": requirement_desc,
            "approve": key_person_approved,
            "signed": contract_signed,
            "next_step": parsed_result.get("suggestion") or "",
            "ai_confidence_score": parsed_result.get("confidence_score"),
            "ai_missing_fields": parsed_result.get("missing_fields") or [],
        }
    )
    return custom_fields


@router.get("/realtime-transcribe-url", summary="Create signed Xfyun realtime ASR WebSocket URL")
async def realtime_transcribe_url(_: User = Depends(get_current_user)):
    signed_url, expires_at = _build_xfyun_realtime_url()
    return {
        "url": signed_url,
        "expires_at": expires_at,
        "sample_rate": REALTIME_SAMPLE_RATE,
        "chunk_size": REALTIME_AUDIO_CHUNK_SIZE,
        "chunk_interval_ms": REALTIME_AUDIO_CHUNK_INTERVAL_MS,
        "max_duration_ms": 60000,
    }


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

    result.pop("_usage", None)
    lead_data = result.get("lead") or {}
    opportunity_data = result.get("opportunity") or {}
    lead_id = None
    opportunity_id = None
    saved_to_lead = False
    saved_to_opportunity = False

    if payload.save_to_lead:
        unit_name = _clean_string(lead_data.get("unit_name")) or _clean_string(opportunity_data.get("customer_name"))
        if not unit_name:
            raise HTTPException(status_code=400, detail="Cannot save lead without unit_name")

        lead_data = {**lead_data, "unit_name": unit_name}
        lead_scoring = calculate_card_score({})
        lead = Lead(
            name=unit_name,
            company=unit_name,
            source=_clean_string(lead_data.get("lead_source")) or "AI录入",
            status="new",
            score=lead_scoring.total_score,
            card_score=lead_scoring.total_score,
            card_level=lead_scoring.card_level,
            owner_id=current_user.id,
            is_active=False,
            review_status="pending",
            score_detail_json=lead_scoring.detail,
            custom_fields=_build_lead_custom_fields(lead_data, result),
            ai_extracted=result,
            **lead_scoring.dimensions,
        )
        db.add(lead)
        saved_to_lead = True

    if payload.save_to_opportunity:
        customer_name = _clean_string(opportunity_data.get("customer_name")) or _clean_string(lead_data.get("unit_name"))
        if not customer_name:
            raise HTTPException(status_code=400, detail="Cannot save opportunity without customer_name")

        product_name = _clean_string(opportunity_data.get("product_name"))
        opportunity_data = {
            **opportunity_data,
            "customer_name": customer_name,
            "owner_name_display": _clean_string(opportunity_data.get("owner_name_display")) or current_user.username,
        }
        stage = _derive_stage_from_ai_opportunity(opportunity_data)
        status = derive_opportunity_status(stage)
        scoring = calculate_card_score({})
        name = f"{customer_name} - {product_name}" if product_name else f"{customer_name} - AI录入"

        opportunity = Opportunity(
            name=name,
            stage=stage,
            status=status,
            is_active=False,
            review_status="pending",
            amount=opportunity_data.get("amount") or None,
            card_score=scoring.total_score,
            card_level=scoring.card_level,
            score_detail_json=scoring.detail,
            ai_confidence=result.get("confidence_score"),
            ai_raw_text=payload.text,
            ai_extracted=result,
            owner_id=current_user.id,
            source="AI录入",
            customer_name=customer_name,
            customer_type=_none_if_blank(opportunity_data.get("customer_type")),
            requirement_desc=_none_if_blank(opportunity_data.get("requirement_desc")),
            product_name=_none_if_blank(product_name),
            estimated_cycle=_none_if_blank(opportunity_data.get("estimated_cycle")),
            opportunity_level=_none_if_blank(opportunity_data.get("opportunity_level")),
            project_date=_none_if_blank(opportunity_data.get("project_date")),
            project_members=_none_if_blank(opportunity_data.get("project_members")),
            solution_communication=_none_if_blank(opportunity_data.get("solution_communication")),
            poc_status=_none_if_blank(opportunity_data.get("poc_status")),
            key_person_approved=_none_if_blank(opportunity_data.get("key_person_approved")),
            bid_probability=_none_if_blank(opportunity_data.get("bid_probability")),
            contract_negotiation=_none_if_blank(opportunity_data.get("contract_negotiation")),
            project_type=_none_if_blank(opportunity_data.get("project_type")),
            contract_signed=_none_if_blank(opportunity_data.get("contract_signed")),
            handoff_completed=_none_if_blank(opportunity_data.get("handoff_completed")),
            custom_fields=_build_opportunity_custom_fields(opportunity_data, result),
            **scoring.dimensions,
        )
        db.add(opportunity)
        saved_to_opportunity = True

    if saved_to_lead or saved_to_opportunity:
        await db.flush()
        if saved_to_lead:
            lead_id = lead.id
        if saved_to_opportunity:
            opportunity_id = opportunity.id
        await db.commit()

    return AIParseResponse(
        lead=lead_data,
        opportunity=opportunity_data,
        confidence_score=float(result.get("confidence_score", 0.5)),
        missing_fields=result.get("missing_fields") or [],
        suggestion=result.get("suggestion") or "",
        lead_id=lead_id,
        opportunity_id=opportunity_id,
        saved_to_lead=saved_to_lead,
        saved_to_opportunity=saved_to_opportunity,
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
