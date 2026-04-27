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
Task: Convert the raw transcript or note into a JSON object for CRM opportunity creation.
Output: Return JSON only, without markdown or explanation.

Schema:
{
  "customer_name": "string",
  "deal_value": 0,
  "stage": "初步接触 | 方案报价 | 合同谈判 | 赢单 | 输单",
  "key_needs": ["string"],
  "next_step": "string",
  "confidence_score": 0.0
}

Rules:
1. Use "Unknown" for missing strings, 0 for missing deal_value.
2. stage must be one of the five allowed Chinese values.
3. key_needs must be an array with at least one item.
4. confidence_score must be between 0 and 1.
5. Do not invent facts that are not supported by the text.
""".strip()


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
            max_tokens=800,
        )
    except Exception as exc:
        raise RuntimeError(
            f"failed to parse CRM text: model={settings.OPENAI_MODEL}, "
            f"base_url={_get_openai_base_url()}, error={exc}"
        ) from exc

    content = response.choices[0].message.content or ""
    json_text = _extract_json_text(content)
    result = json.loads(json_text)

    result.setdefault("customer_name", "Unknown")
    result.setdefault("deal_value", 0)
    result.setdefault("stage", "初步接触")
    result.setdefault("key_needs", [])
    result.setdefault("next_step", "Unknown")
    result.setdefault("confidence_score", 0.5)

    if not isinstance(result.get("key_needs"), list):
        result["key_needs"] = [str(result["key_needs"])] if result.get("key_needs") else []
    if not result["key_needs"]:
        result["key_needs"] = ["Unknown"]

    try:
        result["deal_value"] = int(float(result.get("deal_value", 0) or 0))
    except Exception:
        result["deal_value"] = 0

    try:
        result["confidence_score"] = float(result.get("confidence_score", 0.5))
    except Exception:
        result["confidence_score"] = 0.5
    result["confidence_score"] = max(0.0, min(1.0, result["confidence_score"]))

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
