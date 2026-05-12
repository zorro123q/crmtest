"""
Shared CRM workflow rules for statuses and opportunity stages.
CRM 流程规则：线索状态、商机阶段、状态推导逻辑。
"""

from __future__ import annotations


LEAD_STATUSES = ("new", "follow_up", "converted", "invalid", "archived")
OPPORTUNITY_STATUSES = ("new", "follow_up", "won", "lost", "archived")

# 商机阶段常量（使用可读中文，避免 Unicode 转义）
DEFAULT_OPPORTUNITY_STAGE = "初步接触"
QUOTE_STAGE = "方案报价"
NEGOTIATION_STAGE = "合同谈判"
WON_STAGE = "赢单"
LOST_STAGE = "输单"

STAGE_DEFAULT_PROBABILITY = {
    DEFAULT_OPPORTUNITY_STAGE: 20,
    QUOTE_STAGE: 40,
    NEGOTIATION_STAGE: 70,
    WON_STAGE: 100,
    LOST_STAGE: 0,
}

STAGE_ORDER = [
    DEFAULT_OPPORTUNITY_STAGE,
    QUOTE_STAGE,
    NEGOTIATION_STAGE,
    WON_STAGE,
    LOST_STAGE,
]


def normalize_lead_status(value: str | None) -> str:
    normalized = str(value or "").strip().lower() or "new"
    if normalized not in LEAD_STATUSES:
        raise ValueError(f"Invalid lead status: {value}")
    return normalized


def normalize_opportunity_stage(value: str | None) -> str:
    normalized = str(value or "").strip() or DEFAULT_OPPORTUNITY_STAGE
    if normalized not in STAGE_DEFAULT_PROBABILITY:
        raise ValueError(f"Invalid opportunity stage: {value}")
    return normalized


def derive_opportunity_status(stage: str, explicit_status: str | None = None) -> str:
    normalized_stage = normalize_opportunity_stage(stage)
    normalized_status = str(explicit_status or "").strip().lower()

    if normalized_stage == WON_STAGE:
        return "won"
    if normalized_stage == LOST_STAGE:
        return "lost"
    if normalized_status:
        if normalized_status not in OPPORTUNITY_STATUSES:
            raise ValueError(f"Invalid opportunity status: {explicit_status}")
        if normalized_status in {"won", "lost"}:
            return "follow_up"
        return normalized_status
    return "new"


def status_to_active(status: str) -> bool:
    return str(status or "").strip().lower() != "archived"
