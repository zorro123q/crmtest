"""
AI service layer.
- /api/ai/parse -> GPT extracts CRM fields from free text
- /api/ai/transcribe -> DashScope paraformer-v2 transcribes audio
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from openai import AsyncOpenAI

from app.core.config import settings


CRM_SYSTEM_PROMPT = """
Role: 你是一个资深的销售运营专家，擅长从非结构化的语音对话中提取核心销售信息。

Task: 请将以下非结构化文本（语音转文字结果）解析为结构化的 CRM 数据对象。

Output Schema (严格返回 JSON，不要有任何额外文字):
{
  "customer_name": "公司或个人名称（字符串）",
  "deal_value": 预估合同金额（纯数字，单位：元。如提到50万则填500000）,
  "stage": "商机阶段（必须从以下取值：初步接洽、方案报价、合同谈判、赢单、输单）",
  "key_needs": ["客户核心痛点或需求1", "需求2"],
  "next_step": "下一步跟进动作及时间点",
  "confidence_score": 0到1之间的置信度（浮点数，综合考虑信息完整度）
}

Constraints:
1. 如果文本中未提到某项信息，填入字符串 "Unknown"（deal_value 未知时填 0）
2. 严禁编造数据，基于原文推理
3. stage 只能取定义的五个枚举值之一，根据语义判断最接近的阶段
4. confidence_score 综合考虑：关键字段完整度、信息明确程度、上下文清晰度
5. key_needs 至少包含1个元素，最多5个
""".strip()


_openai_client: AsyncOpenAI | None = None

_DASHSCOPE_UPLOAD_PATH = "/api/v1/uploads"
_DASHSCOPE_TRANSCRIBE_PATH = "/api/v1/services/audio/asr/transcription"
_DASHSCOPE_TASK_PATH = "/api/v1/tasks/{task_id}"
_DASHSCOPE_REQUEST_TIMEOUT = httpx.Timeout(120.0, connect=20.0)
_DASHSCOPE_POLL_INTERVAL_SECONDS = 1.0
_DASHSCOPE_POLL_TIMEOUT_SECONDS = 180.0


def _get_openai_client() -> AsyncOpenAI:
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY 未配置，无法调用文本解析模型")

    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=60.0,
        )
    return _openai_client


def _get_dashscope_api_key() -> str:
    api_key = settings.DASHSCOPE_API_KEY
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY 未配置，无法调用 paraformer-v2 转写")
    return api_key


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

    detail_parts = [f"HTTP {response.status_code}"]
    if code:
        detail_parts.append(str(code))
    if message:
        detail_parts.append(str(message))
    if request_id:
        detail_parts.append(f"request_id={request_id}")

    if len(detail_parts) == 1 and response.text:
        detail_parts.append(response.text.strip())

    return f"{action}失败：" + " | ".join(detail_parts)


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
        raise RuntimeError(_build_dashscope_error_message("获取 DashScope 临时上传凭证", response))

    data = response.json().get("data")
    if not isinstance(data, dict):
        raise RuntimeError("获取 DashScope 临时上传凭证失败：返回数据缺少 data 字段")
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
        raise RuntimeError("获取 DashScope 临时上传凭证失败：缺少 upload_host 或 upload_dir")

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
        raise RuntimeError(_build_dashscope_error_message("上传音频到 DashScope 临时存储", upload_response))

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
        raise RuntimeError(_build_dashscope_error_message("提交 paraformer-v2 转写任务", response))

    task_id = response.json().get("output", {}).get("task_id")
    if not task_id:
        raise RuntimeError("提交 paraformer-v2 转写任务失败：返回结果缺少 task_id")
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
        return "；".join(result_errors)

    top_level_parts = []
    for key in ("task_status", "code", "message"):
        if output.get(key):
            top_level_parts.append(str(output[key]))
    return " | ".join(top_level_parts) or "任务未返回可用结果"


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
            raise RuntimeError(_build_dashscope_error_message("查询 paraformer-v2 转写任务", response))

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
            raise RuntimeError(f"paraformer-v2 转写任务成功但未返回结果：{_collect_task_error(output)}")

        if task_status in {"FAILED", "CANCELED"}:
            raise RuntimeError(f"paraformer-v2 转写任务失败：{_collect_task_error(output)}")

        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("等待 paraformer-v2 转写结果超时，请稍后重试")

        await asyncio.sleep(_DASHSCOPE_POLL_INTERVAL_SECONDS)


async def _download_transcription_text(client: httpx.AsyncClient, result_urls: list[str]) -> str:
    fragments: list[str] = []

    for result_url in result_urls:
        response = await client.get(result_url)
        if response.status_code != 200:
            raise RuntimeError(_build_dashscope_error_message("下载 paraformer-v2 转写结果", response))

        payload = response.json()
        current_fragments: list[str] = []

        transcripts = payload.get("transcripts") or []
        for item in transcripts:
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
        raise RuntimeError("paraformer-v2 未返回可用文本内容")
    return merged


async def parse_crm_text(raw_text: str) -> dict[str, Any]:
    """
    调用 GPT 模型，将转写文本解析为结构化 CRM 数据。
    """
    client = _get_openai_client()

    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": CRM_SYSTEM_PROMPT},
            {"role": "user", "content": f"请解析以下文本：\n\n{raw_text}"},
        ],
        temperature=0.1,
        max_tokens=800,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    result = json.loads(content)

    result.setdefault("customer_name", "Unknown")
    result.setdefault("deal_value", 0)
    result.setdefault("stage", "初步接洽")
    result.setdefault("key_needs", [])
    result.setdefault("next_step", "Unknown")
    result.setdefault("confidence_score", 0.5)

    result["confidence_score"] = max(0.0, min(1.0, float(result["confidence_score"])))
    result["_usage"] = {
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
        "model": settings.OPENAI_MODEL,
    }
    return result


async def transcribe_audio(audio_file_bytes: bytes, filename: str = "audio.webm") -> str:
    """
    使用阿里云 DashScope paraformer-v2 进行录音文件转写。
    流程：
    1. 申请临时上传凭证
    2. 上传音频到 DashScope 临时 OSS
    3. 提交异步转写任务
    4. 轮询任务状态并下载结果
    """
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
