"""Build and send weekly opportunity report emails."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import Opportunity
from app.services.opportunity_report_service import build_target_report
from app.services.report_email_config_service import (
    DEFAULT_REPORT_GROUP_LABELS,
    REPORT_GROUP_KEYS,
    get_report_email_config,
    normalize_email_list,
)

logger = logging.getLogger(__name__)


class ReportEmailSMTPNotConfigured(RuntimeError):
    """Raised when SMTP settings are missing."""


class ReportEmailSendError(RuntimeError):
    """Raised when SMTP delivery fails."""


EMAIL_METRICS = (
    ("collected_info_count", "收集信息数", "count"),
    ("valid_contact_count", "有效接触数", "count"),
    ("approval_count", "获得认可数", "count"),
    ("budget_count", "拿到预算数", "count"),
    ("solution_approved_count", "方案认可数", "count"),
    ("signed_count", "签约数", "count"),
    ("average_contract_amount", "合同均额", "amount"),
    ("recognized_revenue", "确收额", "amount"),
)


def _report_timezone():
    try:
        return ZoneInfo(settings.REPORT_EMAIL_TIMEZONE)
    except Exception:
        if settings.REPORT_EMAIL_TIMEZONE == "Asia/Shanghai":
            return timezone(timedelta(hours=8), "Asia/Shanghai")
        logger.warning("Invalid REPORT_EMAIL_TIMEZONE=%s, falling back to UTC", settings.REPORT_EMAIL_TIMEZONE)
        return timezone.utc


def _now_for_report() -> datetime:
    return datetime.now(_report_timezone())


async def _has_review_status_column(db: AsyncSession) -> bool:
    try:
        result = await db.execute(text("SHOW COLUMNS FROM opportunities LIKE 'review_status'"))
        return result.first() is not None
    except SQLAlchemyError:
        return False


async def build_weekly_report_payload(db: AsyncSession) -> dict[str, Any]:
    config = get_report_email_config()
    review_filter_applied = await _has_review_status_column(db)

    query = select(Opportunity).options(selectinload(Opportunity.owner)).order_by(Opportunity.created_at.desc())
    if review_filter_applied:
        query = query.where(Opportunity.review_status == "approved")

    result = await db.execute(query)
    report = build_target_report(
        result.scalars().all(),
        pioneer_members=config.get("pioneer_members") or [],
        charge_members=config.get("charge_members") or [],
    )
    now = _now_for_report()
    return {
        "scope": "all",
        "scope_label": "全部用户",
        "review_filter_applied": review_filter_applied,
        "send_time": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "report_date": now.strftime("%Y-%m-%d"),
        "subject_prefix": config.get("subject_prefix") or "SalesPilot CRM 商机通报",
        "pioneer_members": config.get("pioneer_members") or [],
        "charge_members": config.get("charge_members") or [],
        "group_labels": config.get("group_labels") or DEFAULT_REPORT_GROUP_LABELS,
        "old_customer_new_business": report["old_customer_new_business"],
        "new_customer_business": report["new_customer_business"],
    }


def _format_metric_value(value: Any, value_type: str) -> str:
    number = float(value or 0)
    if value_type == "amount":
        return f"￥{number:,.2f}".rstrip("0").rstrip(".")
    return f"{int(number):,}" if number.is_integer() else f"{number:,.2f}".rstrip("0").rstrip(".")


def _render_module_table(title: str, module_data: dict[str, Any], group_labels: dict[str, str]) -> str:
    header_cells = "".join(
        f"<th style='padding:8px;border:1px solid #cbd5e1;background:#e0f2fe;text-align:center'>{escape(label)}</th>"
        for label in (group_labels.get(group_key, group_key) for group_key in REPORT_GROUP_KEYS)
    )
    rows = []
    for metric_key, metric_label, value_type in EMAIL_METRICS:
        cells = []
        for group_key in REPORT_GROUP_KEYS:
            group_metrics = module_data.get(group_key) or {}
            cells.append(
                "<td style='padding:8px;border:1px solid #cbd5e1;text-align:right'>"
                f"{escape(_format_metric_value(group_metrics.get(metric_key, 0), value_type))}</td>"
            )
        rows.append(
            "<tr>"
            f"<td style='padding:8px;border:1px solid #cbd5e1;font-weight:700;background:#f8fafc'>{escape(metric_label)}</td>"
            + "".join(cells)
            + "</tr>"
        )

    return (
        f"<h3 style='margin:24px 0 10px;color:#0f172a'>{escape(title)}</h3>"
        "<table style='border-collapse:collapse;width:100%;font-size:14px;color:#0f172a'>"
        "<thead><tr>"
        "<th style='padding:8px;border:1px solid #cbd5e1;background:#bae6fd;text-align:left'>指标</th>"
        f"{header_cells}"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def render_report_email_html(payload: dict[str, Any]) -> str:
    send_time = escape(str(payload.get("send_time") or ""))
    scope_label = escape(str(payload.get("scope_label") or "全部用户"))
    group_labels = {
        **DEFAULT_REPORT_GROUP_LABELS,
        **(payload.get("group_labels") or {}),
    }
    old_table = _render_module_table("老客户新业务", payload.get("old_customer_new_business") or {}, group_labels)
    new_table = _render_module_table("新客户新老业务", payload.get("new_customer_business") or {}, group_labels)

    return (
        "<!doctype html><html><body style='margin:0;padding:24px;background:#f8fafc;"
        "font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Microsoft YaHei,sans-serif;color:#0f172a'>"
        "<div style='max-width:980px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;padding:24px'>"
        "<h2 style='margin:0 0 16px;color:#075985'>SalesPilot CRM 每周商机通报</h2>"
        f"<p style='margin:6px 0'>统计范围：{scope_label}</p>"
        "<p style='margin:6px 0'>统计口径：仅统计已审核通过商机</p>"
        f"<p style='margin:6px 0'>发送时间：{send_time}</p>"
        f"{old_table}{new_table}"
        "</div></body></html>"
    )


def _ensure_smtp_config() -> None:
    missing = [
        name
        for name, value in (
            ("SMTP_HOST", settings.SMTP_HOST),
            ("SMTP_USERNAME", settings.SMTP_USERNAME),
            ("SMTP_PASSWORD", settings.SMTP_PASSWORD),
            ("SMTP_FROM", settings.SMTP_FROM),
        )
        if not value
    ]
    if missing:
        raise ReportEmailSMTPNotConfigured(
            "SMTP 邮件服务未配置，请在 .env 中设置 " + "、".join(missing)
        )


def _send_html_email(recipients: list[str], subject: str, html: str) -> None:
    _ensure_smtp_config()

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.SMTP_FROM or ""
    message["To"] = ", ".join(recipients)
    message.set_content("请使用支持 HTML 的邮件客户端查看 SalesPilot CRM 商机通报。")
    message.add_alternative(html, subtype="html")

    try:
        if settings.SMTP_USE_SSL:
            smtp = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20)
        else:
            smtp = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20)
        with smtp:
            if not settings.SMTP_USE_SSL:
                smtp.starttls()
            smtp.login(settings.SMTP_USERNAME or "", settings.SMTP_PASSWORD or "")
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        logger.exception("Opportunity report email delivery failed")
        raise ReportEmailSendError(f"邮件发送失败：{exc}") from exc


async def send_weekly_opportunity_report(
    db: AsyncSession,
    recipients: list[str] | None = None,
) -> dict[str, Any]:
    _ensure_smtp_config()

    config = get_report_email_config()
    target_recipients = normalize_email_list(recipients if recipients is not None else config.get("recipients"))
    if not target_recipients:
        raise ValueError("请先配置收件邮箱")

    payload = await build_weekly_report_payload(db)
    subject_prefix = str(config.get("subject_prefix") or payload.get("subject_prefix") or "SalesPilot CRM 商机通报")
    subject = f"{subject_prefix} - {payload['report_date']}"
    html = render_report_email_html(payload)

    await asyncio.to_thread(_send_html_email, target_recipients, subject, html)
    return {
        "sent": True,
        "recipients": target_recipients,
        "message": "发送成功",
    }
