"""
AI service layer.
- /api/ai/parse -> LLM extracts CRM fields from free text
- /api/ai/transcribe -> DashScope paraformer-v2 transcribes audio
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from openai import AsyncOpenAI

from app.core.config import settings
from app.services.scoring_service import (
    get_scoring_field_keys,
    get_scoring_fields,
    normalize_card_type,
    normalize_scoring_dimensions,
)


CRM_SYSTEM_PROMPT = """
Role: You are a CRM extraction assistant.
Task: Convert the raw transcript or note into one JSON object for both CRM lead tracking and opportunity management.
Output: Return JSON only, without markdown or explanation.

Schema:
{
  "lead": {
    "business_owner": "",
    "unit_name": "",
    "industry_category": "",
    "customer_type": "",
    "opportunity_level": "",
    "requirement_desc": "",
    "budget_amount": "",
    "lead_source": "",
    "purchased_related_products": "",
    "visit_key_time": "",
    "decision_chain_info": "",
    "cooperation_intent": "",
    "next_visit_plan": "",
    "cooperation_scheme_status": "",
    "key_person_approved": "",
    "next_step_plan": ""
  },
  "opportunity": {
    "owner_name_display": "",
    "customer_name": "",
    "customer_type": "",
    "requirement_desc": "",
    "product_name": "",
    "amount": 0,
    "estimated_cycle": "",
    "opportunity_level": "",
    "project_date": "",
    "project_members": "",
    "solution_communication": "",
    "poc_status": "",
    "key_person_approved": "",
    "bid_probability": "",
    "contract_negotiation": "",
    "project_type": "",
    "contract_signed": "",
    "handoff_completed": ""
  },
  "confidence_score": 0.0,
  "missing_fields": [],
  "suggestion": ""
}

Rules:
1. Return every key exactly as shown. Use "" for missing strings, 0 for missing amount.
2. Do not invent facts that are not supported by the text. If uncertain, leave the field blank.
3. customer_type must be one of: 新客户, 老客户, 老客户新部门, or "".
4. lead.opportunity_level must be one of: A, B, C, D, or "".
5. opportunity.opportunity_level and bid_probability must be one of: A, B, C, D, E, or "".
6. Yes/no fields must use 是, 否, 待确认 only when allowed. contract_signed, handoff_completed, purchased_related_products use only 是 or 否.
7. opportunity.amount must be a number. Convert units such as 万 and 元 when explicit. For example 200万 -> 2000000.
8. missing_fields is a list of field paths that cannot be determined, such as lead.unit_name or opportunity.product_name.
9. confidence_score must be between 0 and 1.
""".strip()


LEAD_PARSE_FIELDS = (
    "business_owner",
    "unit_name",
    "industry_category",
    "customer_type",
    "opportunity_level",
    "requirement_desc",
    "budget_amount",
    "lead_source",
    "purchased_related_products",
    "visit_key_time",
    "decision_chain_info",
    "cooperation_intent",
    "next_visit_plan",
    "cooperation_scheme_status",
    "key_person_approved",
    "next_step_plan",
)

OPPORTUNITY_PARSE_FIELDS = (
    "owner_name_display",
    "customer_name",
    "customer_type",
    "requirement_desc",
    "product_name",
    "amount",
    "estimated_cycle",
    "opportunity_level",
    "project_date",
    "project_members",
    "solution_communication",
    "poc_status",
    "key_person_approved",
    "bid_probability",
    "contract_negotiation",
    "project_type",
    "contract_signed",
    "handoff_completed",
)

CUSTOMER_TYPE_ALIASES = {
    "新客户": "新客户",
    "新客": "新客户",
    "老客户": "老客户",
    "老客": "老客户",
    "老客户新部门": "老客户新部门",
    "老客新部门": "老客户新部门",
}

YES_NO_ALIASES = {
    "是": "是",
    "有": "是",
    "已": "是",
    "已采购": "是",
    "已签订": "是",
    "已完成": "是",
    "认可": "是",
    "通过": "是",
    "yes": "是",
    "y": "是",
    "true": "是",
    "1": "是",
    "否": "否",
    "无": "否",
    "没有": "否",
    "未": "否",
    "未采购": "否",
    "未签订": "否",
    "未完成": "否",
    "不认可": "否",
    "不通过": "否",
    "no": "否",
    "n": "否",
    "false": "否",
    "0": "否",
}

YES_NO_PENDING_ALIASES = {
    **YES_NO_ALIASES,
    "待确认": "待确认",
    "待定": "待确认",
    "不确定": "待确认",
    "确认中": "待确认",
}

PROJECT_TYPE_ALIASES = {
    "saas": "SaaS",
    "SaaS": "SaaS",
    "定制化": "定制化项目",
    "定制化项目": "定制化项目",
    "集成": "集成项目",
    "集成项目": "集成项目",
    "运维": "运维服务",
    "运维服务": "运维服务",
    "其他": "其他",
}


_openai_client: AsyncOpenAI | None = None

_DASHSCOPE_UPLOAD_PATH = "/api/v1/uploads"
_DASHSCOPE_TRANSCRIBE_PATH = "/api/v1/services/audio/asr/transcription"
_DASHSCOPE_TASK_PATH = "/api/v1/tasks/{task_id}"
_DASHSCOPE_REQUEST_TIMEOUT = httpx.Timeout(120.0, connect=20.0)
_DASHSCOPE_POLL_INTERVAL_SECONDS = 1.0
_DASHSCOPE_POLL_TIMEOUT_SECONDS = 180.0


def _get_openai_base_url() -> str:
    return getattr(
        settings,
        "OPENAI_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ).rstrip("/")


def _get_openai_client() -> AsyncOpenAI:
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=_get_openai_base_url(),
            timeout=60.0,
        )
    return _openai_client


def _get_dashscope_api_key() -> str:
    if not settings.DASHSCOPE_API_KEY:
        raise RuntimeError("DASHSCOPE_API_KEY is not configured")
    return settings.DASHSCOPE_API_KEY


def _dashscope_headers(
    *,
    include_content_type: bool = False,
    async_mode: bool = False,
    resolve_oss: bool = False,
) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {_get_dashscope_api_key()}",
    }
    if include_content_type:
        headers["Content-Type"] = "application/json"
    if async_mode:
        headers["X-DashScope-Async"] = "enable"
    if resolve_oss:
        headers["X-DashScope-OssResourceResolve"] = "enable"
    return headers


def _build_dashscope_error_message(action: str, response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = {}

    code = payload.get("code")
    message = payload.get("message") or payload.get("msg")
    request_id = payload.get("request_id")

    parts = [f"HTTP {response.status_code}"]
    if code:
        parts.append(str(code))
    if message:
        parts.append(str(message))
    if request_id:
        parts.append(f"request_id={request_id}")
    if len(parts) == 1 and response.text:
        parts.append(response.text.strip())

    return f"{action} failed: " + " | ".join(parts)


def _normalize_upload_filename(filename: str) -> str:
    suffix = Path(filename or "audio.webm").suffix.lower()
    if not suffix:
        suffix = ".webm"
    return f"{uuid4().hex}{suffix}"


async def _fetch_upload_policy(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.get(
        _DASHSCOPE_UPLOAD_PATH,
        headers=_dashscope_headers(),
        params={
            "action": "getPolicy",
            "model": settings.PARAFORMER_MODEL,
        },
    )
    if response.status_code != 200:
        raise RuntimeError(_build_dashscope_error_message("fetch upload policy", response))

    data = response.json().get("data")
    if not isinstance(data, dict):
        raise RuntimeError("fetch upload policy failed: missing data payload")
    return data


async def _upload_audio_to_dashscope(
    client: httpx.AsyncClient,
    *,
    audio_file_bytes: bytes,
    filename: str,
) -> str:
    policy = await _fetch_upload_policy(client)

    upload_host = policy.get("upload_host")
    upload_dir = policy.get("upload_dir")
    if not upload_host or not upload_dir:
        raise RuntimeError("fetch upload policy failed: missing upload_host or upload_dir")

    object_key = f"{str(upload_dir).rstrip('/')}/{_normalize_upload_filename(filename)}"
    form_data = {
        "OSSAccessKeyId": policy.get("oss_access_key_id", ""),
        "Signature": policy.get("signature", ""),
        "policy": policy.get("policy", ""),
        "key": object_key,
        "success_action_status": "200",
        "x-oss-object-acl": policy.get("x_oss_object_acl", "private"),
        "x-oss-forbid-overwrite": policy.get("x_oss_forbid_overwrite", "true"),
    }

    security_token = policy.get("security_token") or policy.get("x_oss_security_token")
    if security_token:
        form_data["x-oss-security-token"] = security_token

    upload_response = await client.post(
        str(upload_host),
        data=form_data,
        files={
            "file": (
                Path(filename or "audio.webm").name or "audio.webm",
                audio_file_bytes,
                "application/octet-stream",
            )
        },
    )
    if upload_response.status_code != 200:
        raise RuntimeError(_build_dashscope_error_message("upload audio", upload_response))

    return f"oss://{object_key}"


def _build_transcription_payload(file_url: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": settings.PARAFORMER_MODEL,
        "input": {
            "file_urls": [file_url],
        },
    }

    language_hints = settings.paraformer_language_hints_list
    if language_hints:
        payload["parameters"] = {
            "language_hints": language_hints,
        }

    return payload


async def _submit_transcription_task(client: httpx.AsyncClient, file_url: str) -> str:
    response = await client.post(
        _DASHSCOPE_TRANSCRIBE_PATH,
        headers=_dashscope_headers(
            include_content_type=True,
            async_mode=True,
            resolve_oss=file_url.startswith("oss://"),
        ),
        json=_build_transcription_payload(file_url),
    )
    if response.status_code != 200:
        raise RuntimeError(_build_dashscope_error_message("submit transcription task", response))

    task_id = response.json().get("output", {}).get("task_id")
    if not task_id:
        raise RuntimeError("submit transcription task failed: missing task_id")
    return str(task_id)


def _collect_task_error(output: dict[str, Any]) -> str:
    result_errors: list[str] = []
    for item in output.get("results", []) or []:
        status = item.get("subtask_status")
        if status == "SUCCEEDED":
            continue
        error_parts = [str(status or "UNKNOWN")]
        if item.get("code"):
            error_parts.append(str(item["code"]))
        if item.get("message"):
            error_parts.append(str(item["message"]))
        if item.get("file_url"):
            error_parts.append(str(item["file_url"]))
        result_errors.append(" | ".join(error_parts))

    if result_errors:
        return "; ".join(result_errors)

    top_level_parts = []
    for key in ("task_status", "code", "message"):
        if output.get(key):
            top_level_parts.append(str(output[key]))
    return " | ".join(top_level_parts) or "task did not return usable details"


async def _wait_for_transcription_result(
    client: httpx.AsyncClient,
    *,
    task_id: str,
) -> list[str]:
    deadline = asyncio.get_running_loop().time() + _DASHSCOPE_POLL_TIMEOUT_SECONDS

    while True:
        response = await client.post(
            _DASHSCOPE_TASK_PATH.format(task_id=task_id),
            headers=_dashscope_headers(),
        )
        if response.status_code != 200:
            raise RuntimeError(_build_dashscope_error_message("query transcription task", response))

        output = response.json().get("output", {})
        task_status = output.get("task_status")

        if task_status == "SUCCEEDED":
            result_urls = [
                str(item["transcription_url"])
                for item in (output.get("results") or [])
                if item.get("subtask_status") == "SUCCEEDED" and item.get("transcription_url")
            ]
            if result_urls:
                return result_urls
            raise RuntimeError(f"transcription task succeeded but no result url returned: {_collect_task_error(output)}")

        if task_status in {"FAILED", "CANCELED"}:
            raise RuntimeError(f"transcription task failed: {_collect_task_error(output)}")

        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("waiting for transcription result timed out")

        await asyncio.sleep(_DASHSCOPE_POLL_INTERVAL_SECONDS)


async def _download_transcription_text(client: httpx.AsyncClient, result_urls: list[str]) -> str:
    fragments: list[str] = []

    for result_url in result_urls:
        response = await client.get(result_url)
        if response.status_code != 200:
            raise RuntimeError(_build_dashscope_error_message("download transcription result", response))

        payload = response.json()
        current_fragments: list[str] = []

        for item in payload.get("transcripts") or []:
            text = item.get("text")
            if text:
                current_fragments.append(str(text).strip())

        if not current_fragments:
            for item in payload.get("sentences") or []:
                text = item.get("text")
                if text:
                    current_fragments.append(str(text).strip())

        if not current_fragments:
            for fallback_key in ("transcript", "text"):
                value = payload.get(fallback_key)
                if value:
                    current_fragments.append(str(value).strip())

        fragments.extend(part for part in current_fragments if part)

    merged = "\n".join(part for part in fragments if part).strip()
    if not merged:
        raise RuntimeError("transcription result is empty")
    return merged


def _extract_json_text(content: str) -> str:
    if not content:
        raise RuntimeError("model returned empty content")

    content = content.strip()

    if content.startswith("```"):
        content = re.sub(r"^```json\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"^```\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

    try:
        json.loads(content)
        return content
    except Exception:
        pass

    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if match:
        candidate = match.group(0)
        json.loads(candidate)
        return candidate

    raise RuntimeError(f"model output is not valid JSON: {content[:300]}")


def parse_amount_value(value: Any) -> float:
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return 0

    normalized = re.sub(r"[,，￥¥元\s]", "", text)
    if not normalized:
        return 0

    multiplier = 1.0
    if normalized.endswith("万"):
        multiplier = 10000.0
        normalized = normalized[:-1]
    elif normalized.endswith("亿"):
        multiplier = 100000000.0
        normalized = normalized[:-1]
    elif normalized.endswith("千"):
        multiplier = 1000.0
        normalized = normalized[:-1]

    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not match:
        return 0
    try:
        return float(match.group(0)) * multiplier
    except ValueError:
        return 0


def _empty_lead_payload() -> dict[str, str]:
    return {field_name: "" for field_name in LEAD_PARSE_FIELDS}


def _empty_opportunity_payload() -> dict[str, str | float]:
    payload: dict[str, str | float] = {field_name: "" for field_name in OPPORTUNITY_PARSE_FIELDS}
    payload["amount"] = 0
    return payload


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "；".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value).strip()


def _normalize_enum(value: Any, aliases: dict[str, str], allowed: set[str]) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if text in aliases:
        return aliases[text]
    lower = text.lower()
    if lower in aliases:
        return aliases[lower]
    upper = text.upper()
    if upper in allowed:
        return upper
    return text if text in allowed else ""


def _normalize_level(value: Any, allowed: set[str]) -> str:
    text = _clean_text(value).upper()
    return text if text in allowed else ""


def _normalize_project_type(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if text in PROJECT_TYPE_ALIASES:
        return PROJECT_TYPE_ALIASES[text]
    lower = text.lower()
    if lower in PROJECT_TYPE_ALIASES:
        return PROJECT_TYPE_ALIASES[lower]
    return text if text in set(PROJECT_TYPE_ALIASES.values()) else ""


def _legacy_parse_result(payload: dict[str, Any]) -> dict[str, Any]:
    key_needs = payload.get("key_needs")
    if isinstance(key_needs, list):
        requirement_desc = "；".join(_clean_text(item) for item in key_needs if _clean_text(item))
    else:
        requirement_desc = _clean_text(key_needs)

    customer_name = _clean_text(payload.get("customer_name"))
    amount = parse_amount_value(payload.get("deal_value"))
    next_step = _clean_text(payload.get("next_step"))
    return {
        "lead": {
            "unit_name": customer_name,
            "requirement_desc": requirement_desc,
            "budget_amount": str(int(amount)) if amount else "",
            "next_step_plan": next_step,
        },
        "opportunity": {
            "customer_name": customer_name,
            "requirement_desc": requirement_desc,
            "amount": amount,
            "contract_negotiation": next_step,
        },
        "confidence_score": payload.get("confidence_score", 0.5),
        "missing_fields": [],
        "suggestion": next_step,
    }


def normalize_crm_parse_result(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError("AI parse result is not a JSON object")

    raw = payload if ("lead" in payload or "opportunity" in payload) else _legacy_parse_result(payload)
    raw_lead = raw.get("lead") if isinstance(raw.get("lead"), dict) else {}
    raw_opportunity = raw.get("opportunity") if isinstance(raw.get("opportunity"), dict) else {}

    lead = _empty_lead_payload()
    for field_name in LEAD_PARSE_FIELDS:
        lead[field_name] = _clean_text(raw_lead.get(field_name))

    opportunity = _empty_opportunity_payload()
    for field_name in OPPORTUNITY_PARSE_FIELDS:
        if field_name == "amount":
            opportunity[field_name] = parse_amount_value(raw_opportunity.get(field_name))
        else:
            opportunity[field_name] = _clean_text(raw_opportunity.get(field_name))

    lead["customer_type"] = _normalize_enum(lead["customer_type"], CUSTOMER_TYPE_ALIASES, {"新客户", "老客户", "老客户新部门"})
    opportunity["customer_type"] = _normalize_enum(
        opportunity["customer_type"],
        CUSTOMER_TYPE_ALIASES,
        {"新客户", "老客户", "老客户新部门"},
    )
    lead["opportunity_level"] = _normalize_level(lead["opportunity_level"], {"A", "B", "C", "D"})
    opportunity["opportunity_level"] = _normalize_level(opportunity["opportunity_level"], {"A", "B", "C", "D", "E"})
    opportunity["bid_probability"] = _normalize_level(opportunity["bid_probability"], {"A", "B", "C", "D", "E"})
    lead["purchased_related_products"] = _normalize_enum(
        lead["purchased_related_products"],
        YES_NO_ALIASES,
        {"是", "否"},
    )
    lead["key_person_approved"] = _normalize_enum(
        lead["key_person_approved"],
        YES_NO_PENDING_ALIASES,
        {"是", "否", "待确认"},
    )
    opportunity["key_person_approved"] = _normalize_enum(
        opportunity["key_person_approved"],
        YES_NO_PENDING_ALIASES,
        {"是", "否", "待确认"},
    )
    opportunity["contract_signed"] = _normalize_enum(opportunity["contract_signed"], YES_NO_ALIASES, {"是", "否"})
    opportunity["handoff_completed"] = _normalize_enum(opportunity["handoff_completed"], YES_NO_ALIASES, {"是", "否"})
    opportunity["project_type"] = _normalize_project_type(opportunity["project_type"])

    try:
        confidence_score = float(raw.get("confidence_score", 0.5))
    except (TypeError, ValueError):
        confidence_score = 0.5
    confidence_score = max(0.0, min(1.0, confidence_score))

    missing_fields = raw.get("missing_fields")
    if not isinstance(missing_fields, list):
        missing_fields = []
    normalized_missing = [_clean_text(item) for item in missing_fields if _clean_text(item)]

    for prefix, data in (("lead", lead), ("opportunity", opportunity)):
        for field_name, value in data.items():
            if value in ("", 0) and f"{prefix}.{field_name}" not in normalized_missing:
                normalized_missing.append(f"{prefix}.{field_name}")

    return {
        "lead": lead,
        "opportunity": opportunity,
        "confidence_score": confidence_score,
        "missing_fields": normalized_missing,
        "suggestion": _clean_text(raw.get("suggestion")),
    }


def _build_scoring_dimensions_system_prompt(card_type: str) -> str:
    normalized_card_type = normalize_card_type(card_type)
    field_keys = get_scoring_field_keys(normalized_card_type)
    field_map = get_scoring_fields(normalized_card_type)
    field_rules = []
    for field_name in field_keys:
        field_meta = field_map[field_name]
        option_rules = ", ".join(
            f"{option_value}={option_meta['label']}"
            for option_value, option_meta in field_meta["options"].items()
        )
        field_rules.append(f"- {field_name} ({field_meta['label']}): {option_rules}")

    card_label = (
        "A card (lead intent model)"
        if normalized_card_type == "A"
        else "B card (opportunity-to-contract model)"
    )
    return f"""
Role: You extract formal scoring dimensions only.
Task: Read the {card_label} text and map it to the official scoring field values.
Output: Return a single JSON object only. No markdown, no explanation, no extra text.

Rules:
1. The JSON object may only contain these keys: {", ".join(field_keys)}
2. Every key must be present. Use null when the value cannot be determined.
3. Every non-null value must be one of the allowed option values for that field.
4. Never output labels, free-form text, new values, arrays, objects, numbers, or booleans as field values.
5. If the text is insufficient, use null instead of guessing.

Allowed values:
{chr(10).join(field_rules)}
    """.strip()


def _normalize_extracted_scoring_dimensions(payload: Any, card_type: str) -> dict[str, str | None]:
    if not isinstance(payload, dict):
        raise RuntimeError("AI extraction result is not a valid JSON object")

    normalized_card_type = normalize_card_type(card_type)
    field_keys = get_scoring_field_keys(normalized_card_type)
    extra_fields = sorted(set(payload.keys()) - set(field_keys))
    if extra_fields:
        raise RuntimeError(f"AI extraction returned invalid fields: {', '.join(extra_fields)}")

    normalized_payload: dict[str, str | None] = {}
    for field_name in field_keys:
        value = payload.get(field_name)
        if value is None:
            normalized_payload[field_name] = None
            continue
        if not isinstance(value, str):
            raise RuntimeError(f"AI extraction returned a non-string value for {field_name}")
        stripped = value.strip()
        normalized_payload[field_name] = stripped or None

    try:
        return normalize_scoring_dimensions(
            normalized_payload,
            card_type=normalized_card_type,
            allow_extra=False,
        )
    except ValueError as exc:
        raise RuntimeError(f"AI extraction returned invalid enum values: {exc}") from exc


async def parse_crm_text(raw_text: str) -> dict[str, Any]:
    if not raw_text or not raw_text.strip():
        raise RuntimeError("input text is empty")

    client = _get_openai_client()

    try:
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": CRM_SYSTEM_PROMPT},
                {"role": "user", "content": raw_text.strip()},
            ],
            temperature=0.1,
            max_tokens=1800,
        )
    except Exception as exc:
        raise RuntimeError(
            f"failed to parse CRM text: model={settings.OPENAI_MODEL}, "
            f"base_url={_get_openai_base_url()}, error={exc}"
        ) from exc

    content = response.choices[0].message.content or ""
    json_text = _extract_json_text(content)
    result = normalize_crm_parse_result(json.loads(json_text))

    usage = getattr(response, "usage", None)
    result["_usage"] = {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
        "completion_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
        "model": settings.OPENAI_MODEL,
        "base_url": _get_openai_base_url(),
    }
    return result


async def extract_scoring_dimensions_from_text(raw_text: str, card_type: str) -> dict[str, str | None]:
    normalized_card_type = normalize_card_type(card_type)
    if not raw_text or not raw_text.strip():
        raise RuntimeError("AI extraction requires non-empty text")

    client = _get_openai_client()

    try:
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _build_scoring_dimensions_system_prompt(normalized_card_type)},
                {"role": "user", "content": raw_text.strip()},
            ],
            temperature=0.0,
            max_tokens=900,
        )
    except Exception as exc:
        raise RuntimeError(
            f"failed to extract scoring dimensions: model={settings.OPENAI_MODEL}, "
            f"base_url={_get_openai_base_url()}, error={exc}"
        ) from exc

    content = response.choices[0].message.content or ""
    json_text = _extract_json_text(content)
    parsed = json.loads(json_text)
    return _normalize_extracted_scoring_dimensions(parsed, normalized_card_type)


async def transcribe_audio(audio_file_bytes: bytes, filename: str = "audio.webm") -> str:
    async with httpx.AsyncClient(
        base_url=settings.DASHSCOPE_BASE_URL.rstrip("/"),
        timeout=_DASHSCOPE_REQUEST_TIMEOUT,
        follow_redirects=True,
    ) as client:
        file_url = await _upload_audio_to_dashscope(
            client,
            audio_file_bytes=audio_file_bytes,
            filename=filename,
        )
        task_id = await _submit_transcription_task(client, file_url)
        result_urls = await _wait_for_transcription_result(client, task_id=task_id)
        return await _download_transcription_text(client, result_urls)
