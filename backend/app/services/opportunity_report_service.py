"""商机报表聚合辅助函数。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable


@dataclass(slots=True)
class OpportunityReportRow:
    owner_id: str | None
    owner_username: str
    total_count: int = 0
    following_count: int = 0
    won_count: int = 0
    high_priority_count: int = 0
    this_week_new: int = 0
    this_month_new: int = 0


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def build_report_rows(opportunities: Iterable) -> list[OpportunityReportRow]:
    now = _now_utc()
    week_start = now - timedelta(days=7)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    grouped: dict[str | None, OpportunityReportRow] = {}

    for item in opportunities:
        owner = getattr(item, "owner", None)
        owner_id = str(getattr(item, "owner_id", None) or "")
        if not owner_id:
            owner_id = None
        owner_username = getattr(owner, "username", None) or "未分配"

        row = grouped.get(owner_id)
        if row is None:
            row = OpportunityReportRow(owner_id=owner_id, owner_username=owner_username)
            grouped[owner_id] = row

        row.total_count += 1

        status = str(getattr(item, "status", "") or "").strip().lower()
        if status == "follow_up":
            row.following_count += 1
        if status == "won":
            row.won_count += 1

        opportunity_level = str(getattr(item, "opportunity_level", "") or "").strip().upper()
        card_level = str(getattr(item, "card_level", "") or "").strip().upper()
        if opportunity_level in {"A", "B"} or (not opportunity_level and card_level in {"A", "B"}):
            row.high_priority_count += 1

        created_at = getattr(item, "created_at", None)
        if created_at is not None:
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if created_at >= week_start:
                row.this_week_new += 1
            if created_at >= month_start:
                row.this_month_new += 1

    return sorted(grouped.values(), key=lambda row: (row.owner_username.lower(), row.owner_id or ""))


def summarize_report_rows(rows: Iterable[OpportunityReportRow], owner_label: str = "全部用户") -> OpportunityReportRow:
    summary = OpportunityReportRow(owner_id=None, owner_username=owner_label)
    for row in rows:
        summary.total_count += row.total_count
        summary.following_count += row.following_count
        summary.won_count += row.won_count
        summary.high_priority_count += row.high_priority_count
        summary.this_week_new += row.this_week_new
        summary.this_month_new += row.this_month_new
    return summary


TARGET_GROUP_KEYS = (
    "pioneer_leader",
    "pioneer_group",
    "charge_leader",
    "charge_group",
    "department",
)

TARGET_METRIC_KEYS = (
    "collected_info_count",
    "valid_contact_count",
    "approval_count",
    "budget_count",
    "solution_approved_count",
    "signed_count",
    "average_contract_amount",
    "recognized_revenue",
)


def _empty_target_metrics() -> dict[str, int | float]:
    return {key: 0 for key in TARGET_METRIC_KEYS}


def _has_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _first_value(item, field_name: str, *custom_keys: str):
    value = getattr(item, field_name, None)
    if _has_value(value):
        return value

    custom_fields = getattr(item, "custom_fields", None) or {}
    for key in custom_keys or (field_name,):
        value = custom_fields.get(key)
        if _has_value(value):
            return value
    return None


def _is_yes(value) -> bool:
    return str(value or "").strip().lower() in {"是", "yes", "y", "true", "1", "已签订", "won"}


def _amount_value(item) -> float:
    value = getattr(item, "amount", None)
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


def _owner_username(item) -> str:
    owner = getattr(item, "owner", None)
    return str(getattr(owner, "username", None) or getattr(item, "owner_username", None) or "未分配").strip()


def _customer_type(item) -> str:
    return str(_first_value(item, "customer_type", "customer_type") or "").strip()


def _is_old_customer_new_business(item) -> bool:
    return _customer_type(item) in {"老客户", "老客户新部门"}


def _is_new_customer_business(item) -> bool:
    return _customer_type(item) == "新客户"


def _is_valid_contact(item) -> bool:
    return any(
        _has_value(_first_value(item, field_name, field_name, alias))
        for field_name, alias in (
            ("solution_communication", "solution_communication"),
            ("poc_status", "poc_status"),
            ("key_person_approved", "approve"),
        )
    )


def _is_approved_by_key_person(item) -> bool:
    return _is_yes(_first_value(item, "key_person_approved", "key_person_approved", "approve"))


def _has_budget(item) -> bool:
    return _amount_value(item) > 0


def _is_solution_approved(item) -> bool:
    return _is_approved_by_key_person(item) or _has_value(_first_value(item, "poc_status", "poc_status"))


def _is_signed(item) -> bool:
    status = str(getattr(item, "status", "") or "").strip().lower()
    return status == "won" or _is_yes(_first_value(item, "contract_signed", "contract_signed", "signed"))


def _increment_metrics(metrics: dict[str, int | float], item) -> None:
    metrics["collected_info_count"] += 1
    if _is_valid_contact(item):
        metrics["valid_contact_count"] += 1
    if _is_approved_by_key_person(item):
        metrics["approval_count"] += 1
    if _has_budget(item):
        metrics["budget_count"] += 1
    if _is_solution_approved(item):
        metrics["solution_approved_count"] += 1
    if _is_signed(item):
        metrics["signed_count"] += 1
        metrics["recognized_revenue"] += _amount_value(item)


def _finalize_average(metrics: dict[str, int | float]) -> None:
    signed_count = int(metrics["signed_count"] or 0)
    metrics["average_contract_amount"] = (
        round(float(metrics["recognized_revenue"]) / signed_count, 2)
        if signed_count
        else 0
    )
    metrics["recognized_revenue"] = round(float(metrics["recognized_revenue"]), 2)


def _group_keys_for_item(
    item,
    *,
    pioneer_members: set[str],
    charge_members: set[str],
) -> list[str]:
    owner_username = _owner_username(item)
    group_keys = ["department"]
    if owner_username == "陈祺":
        group_keys.append("pioneer_leader")
    if owner_username == "余浩然":
        group_keys.append("charge_leader")
    if owner_username in pioneer_members:
        group_keys.append("pioneer_group")
    if owner_username in charge_members:
        group_keys.append("charge_group")
    return group_keys


def _build_module(
    opportunities: Iterable,
    *,
    customer_filter,
    pioneer_members: set[str],
    charge_members: set[str],
) -> dict[str, dict[str, int | float]]:
    groups = {group_key: _empty_target_metrics() for group_key in TARGET_GROUP_KEYS}

    for item in opportunities:
        if not customer_filter(item):
            continue
        for group_key in _group_keys_for_item(
            item,
            pioneer_members=pioneer_members,
            charge_members=charge_members,
        ):
            _increment_metrics(groups[group_key], item)

    for metrics in groups.values():
        _finalize_average(metrics)
    return groups


def build_target_report(
    opportunities: Iterable,
    *,
    pioneer_members: Iterable[str] | None = None,
    charge_members: Iterable[str] | None = None,
) -> dict[str, dict[str, dict[str, int | float]]]:
    opportunity_list = list(opportunities)
    pioneer_member_set = {str(item).strip() for item in (pioneer_members or []) if str(item).strip()}
    charge_member_set = {str(item).strip() for item in (charge_members or []) if str(item).strip()}

    return {
        "old_customer_new_business": _build_module(
            opportunity_list,
            customer_filter=_is_old_customer_new_business,
            pioneer_members=pioneer_member_set,
            charge_members=charge_member_set,
        ),
        "new_customer_business": _build_module(
            opportunity_list,
            customer_filter=_is_new_customer_business,
            pioneer_members=pioneer_member_set,
            charge_members=charge_member_set,
        ),
    }
