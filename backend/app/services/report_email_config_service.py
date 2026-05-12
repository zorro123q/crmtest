"""JSON-backed settings for scheduled opportunity report emails."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.core.config import BACKEND_DIR, settings


REPORT_EMAIL_CONFIG_PATH = BACKEND_DIR / "storage" / "report_email_config.json"
DEFAULT_REPORT_EMAIL_RECIPIENTS = ["qichen8@iflytek.com", "hryu3@iflytek.com"]
REPORT_GROUP_KEYS = (
    "pioneer_leader",
    "pioneer_group",
    "charge_leader",
    "charge_group",
    "department",
)
DEFAULT_REPORT_GROUP_LABELS = {
    "pioneer_leader": "先锋组组长：陈祺",
    "pioneer_group": "先锋组：小组人员（组长自行分配）",
    "charge_leader": "冲锋组组长：余浩然",
    "charge_group": "冲锋组：小组人员（组长自行分配）",
    "department": "部门（鑫健70%、春梅30%）",
}
WEEKDAY_ALIASES = {
    "mon": "mon",
    "monday": "mon",
    "周一": "mon",
    "星期一": "mon",
    "tue": "tue",
    "tuesday": "tue",
    "周二": "tue",
    "星期二": "tue",
    "wed": "wed",
    "wednesday": "wed",
    "周三": "wed",
    "星期三": "wed",
    "thu": "thu",
    "thursday": "thu",
    "周四": "thu",
    "星期四": "thu",
    "fri": "fri",
    "friday": "fri",
    "周五": "fri",
    "星期五": "fri",
    "sat": "sat",
    "saturday": "sat",
    "周六": "sat",
    "星期六": "sat",
    "sun": "sun",
    "sunday": "sun",
    "周日": "sun",
    "周天": "sun",
    "星期日": "sun",
    "星期天": "sun",
}

DEFAULT_REPORT_EMAIL_CONFIG: dict[str, Any] = {
    "enabled": False,
    "recipients": DEFAULT_REPORT_EMAIL_RECIPIENTS,
    "subject_prefix": "SalesPilot CRM 商机通报",
    "pioneer_members": ["李鑫健"],
    "charge_members": ["杨序冬", "杨序东"],
    "group_labels": DEFAULT_REPORT_GROUP_LABELS,
    "schedule_weekday": settings.REPORT_EMAIL_WEEKDAY,
    "schedule_hour": settings.REPORT_EMAIL_HOUR,
    "schedule_minute": settings.REPORT_EMAIL_MINUTE,
    "schedule_timezone": settings.REPORT_EMAIL_TIMEZONE,
}


def _ensure_storage_dir() -> Path:
    REPORT_EMAIL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    return REPORT_EMAIL_CONFIG_PATH.parent


def _payload_to_dict(payload: Any) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(exclude_unset=True)
    if isinstance(payload, dict):
        return dict(payload)
    raise ValueError("邮件配置格式无效")


def _split_raw_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [item.strip() for item in re.split(r"[,，;\n\r；]+", raw) if item.strip()]
    if isinstance(raw, (list, tuple, set)):
        items: list[str] = []
        for item in raw:
            items.extend(_split_raw_list(item))
        return items
    text = str(raw).strip()
    return [text] if text else []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def normalize_email_list(raw: Any) -> list[str]:
    """Normalize comma/newline separated email input and validate basic format."""

    emails = _dedupe(_split_raw_list(raw))
    invalid = [email for email in emails if "@" not in email or email.startswith("@") or email.endswith("@")]
    if invalid:
        raise ValueError(f"邮箱格式无效：{', '.join(invalid)}")
    return emails


def _normalize_string_list(raw: Any) -> list[str]:
    return _dedupe(_split_raw_list(raw))


def _normalize_weekday(raw: Any) -> str:
    value = str(raw or DEFAULT_REPORT_EMAIL_CONFIG["schedule_weekday"]).strip().lower()
    weekday = WEEKDAY_ALIASES.get(value)
    if not weekday:
        raise ValueError("定时发送星期无效，请使用 mon/tue/wed/thu/fri/sat/sun")
    return weekday


def _normalize_int_range(raw: Any, *, default: int, minimum: int, maximum: int, label: str) -> int:
    try:
        value = int(raw if raw not in (None, "") else default)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须是数字") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{label}必须在 {minimum}-{maximum} 之间")
    return value


def _normalize_timezone(raw: Any) -> str:
    value = str(raw or DEFAULT_REPORT_EMAIL_CONFIG["schedule_timezone"]).strip()
    return value or str(DEFAULT_REPORT_EMAIL_CONFIG["schedule_timezone"])


def _normalize_group_labels(raw: Any) -> dict[str, str]:
    labels = dict(DEFAULT_REPORT_GROUP_LABELS)
    if not isinstance(raw, dict):
        return labels

    for group_key in REPORT_GROUP_KEYS:
        value = raw.get(group_key)
        if isinstance(value, dict):
            value = value.get("label") or value.get("old") or value.get("oldLabel") or value.get("newLabel")
        text = str(value or "").strip()
        if text:
            labels[group_key] = text
    return labels


def get_report_email_config() -> dict[str, Any]:
    _ensure_storage_dir()
    if not REPORT_EMAIL_CONFIG_PATH.exists():
        return dict(DEFAULT_REPORT_EMAIL_CONFIG)

    try:
        raw = json.loads(REPORT_EMAIL_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("邮件配置文件读取失败，请检查 backend/storage/report_email_config.json") from exc

    config = {**DEFAULT_REPORT_EMAIL_CONFIG, **(raw if isinstance(raw, dict) else {})}
    return {
        "enabled": bool(config.get("enabled")),
        "recipients": normalize_email_list(config.get("recipients")),
        "subject_prefix": str(config.get("subject_prefix") or DEFAULT_REPORT_EMAIL_CONFIG["subject_prefix"]).strip(),
        "pioneer_members": _normalize_string_list(config.get("pioneer_members")),
        "charge_members": _normalize_string_list(config.get("charge_members")),
        "group_labels": _normalize_group_labels(config.get("group_labels")),
        "schedule_weekday": _normalize_weekday(config.get("schedule_weekday")),
        "schedule_hour": _normalize_int_range(
            config.get("schedule_hour"),
            default=int(DEFAULT_REPORT_EMAIL_CONFIG["schedule_hour"]),
            minimum=0,
            maximum=23,
            label="定时发送小时",
        ),
        "schedule_minute": _normalize_int_range(
            config.get("schedule_minute"),
            default=int(DEFAULT_REPORT_EMAIL_CONFIG["schedule_minute"]),
            minimum=0,
            maximum=59,
            label="定时发送分钟",
        ),
        "schedule_timezone": _normalize_timezone(config.get("schedule_timezone")),
    }


def update_report_email_config(payload: Any) -> dict[str, Any]:
    data = {**get_report_email_config(), **_payload_to_dict(payload)}
    config = {
        "enabled": bool(data.get("enabled")),
        "recipients": normalize_email_list(data.get("recipients")),
        "subject_prefix": str(data.get("subject_prefix") or DEFAULT_REPORT_EMAIL_CONFIG["subject_prefix"]).strip(),
        "pioneer_members": _normalize_string_list(data.get("pioneer_members")),
        "charge_members": _normalize_string_list(data.get("charge_members")),
        "group_labels": _normalize_group_labels(data.get("group_labels")),
        "schedule_weekday": _normalize_weekday(data.get("schedule_weekday")),
        "schedule_hour": _normalize_int_range(
            data.get("schedule_hour"),
            default=int(DEFAULT_REPORT_EMAIL_CONFIG["schedule_hour"]),
            minimum=0,
            maximum=23,
            label="定时发送小时",
        ),
        "schedule_minute": _normalize_int_range(
            data.get("schedule_minute"),
            default=int(DEFAULT_REPORT_EMAIL_CONFIG["schedule_minute"]),
            minimum=0,
            maximum=59,
            label="定时发送分钟",
        ),
        "schedule_timezone": _normalize_timezone(data.get("schedule_timezone")),
    }

    _ensure_storage_dir()
    REPORT_EMAIL_CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return config
