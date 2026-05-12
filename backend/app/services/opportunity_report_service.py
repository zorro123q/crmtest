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
    custom_fields = getattr(item, "custom_fields", None) or {}
    owner = getattr(item, "owner", None)

    return str(
        custom_fields.get("owner_name_display")
        or custom_fields.get("business_owner")
        or custom_fields.get("owner_name")
        or getattr(owner, "username", None)
        or getattr(item, "owner_username", None)
        or "未分配"
    ).strip()


def _customer_type(item) -> str:
    return str(_first_value(item, "customer_type", "customer_type") or "").strip()


def _is_old_customer_new_business(item) -> bool:
    return _customer_type(item) in {"老客户", "老客户新部门", "老客户老部门"}


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
    pioneer_leader_names: set[str],
    charge_leader_names: set[str],
    pioneer_members: set[str],
    charge_members: set[str],
) -> list[str]:
    owner_username = _owner_username(item)
    group_keys = ["department"]
    if owner_username in pioneer_leader_names:
        group_keys.append("pioneer_leader")
    if owner_username in charge_leader_names:
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
    pioneer_leader_names: set[str],
    charge_leader_names: set[str],
    pioneer_members: set[str],
    charge_members: set[str],
) -> dict[str, dict[str, int | float]]:
    groups = {group_key: _empty_target_metrics() for group_key in TARGET_GROUP_KEYS}

    for item in opportunities:
        if not customer_filter(item):
            continue
        for group_key in _group_keys_for_item(
            item,
            pioneer_leader_names=pioneer_leader_names,
            charge_leader_names=charge_leader_names,
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
    pioneer_leader_names: Iterable[str] | None = None,
    charge_leader_names: Iterable[str] | None = None,
    pioneer_members: Iterable[str] | None = None,
    charge_members: Iterable[str] | None = None,
) -> dict[str, dict[str, dict[str, int | float]]]:
    opportunity_list = list(opportunities)
    pioneer_leader_set = {str(item).strip() for item in (pioneer_leader_names or []) if str(item).strip()}
    charge_leader_set = {str(item).strip() for item in (charge_leader_names or []) if str(item).strip()}
    pioneer_member_set = {str(item).strip() for item in (pioneer_members or []) if str(item).strip()}
    charge_member_set = {str(item).strip() for item in (charge_members or []) if str(item).strip()}

    if not pioneer_leader_set:
        pioneer_leader_set = {"陈祺", "陈棋"}
    if not charge_leader_set:
        charge_leader_set = {"余浩然"}

    return {
        "old_customer_new_business": _build_module(
            opportunity_list,
            customer_filter=_is_old_customer_new_business,
            pioneer_leader_names=pioneer_leader_set,
            charge_leader_names=charge_leader_set,
            pioneer_members=pioneer_member_set,
            charge_members=charge_member_set,
        ),
        "new_customer_business": _build_module(
            opportunity_list,
            customer_filter=_is_new_customer_business,
            pioneer_leader_names=pioneer_leader_set,
            charge_leader_names=charge_leader_set,
            pioneer_members=pioneer_member_set,
            charge_members=charge_member_set,
        ),
    }


def _get_week_label(dt: datetime) -> str:
    """返回 ISO 周标签，例如 '2026-W18'"""
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def build_trend_report(
    opportunities: Iterable,
    *,
    weeks: int = 12,
    pioneer_leader_names: Iterable[str] | None = None,
    charge_leader_names: Iterable[str] | None = None,
    pioneer_members: Iterable[str] | None = None,
    charge_members: Iterable[str] | None = None,
) -> dict:
    """构建按周统计的趋势数据，用于折线图展示。"""
    now = _now_utc()
    start = now - timedelta(weeks=weeks)

    def _ensure_aware(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    opportunity_list = [
        item for item in opportunities
        if getattr(item, "created_at", None) and _ensure_aware(item.created_at) >= start
    ]

    pioneer_leader_set = {str(item).strip() for item in (pioneer_leader_names or []) if str(item).strip()}
    charge_leader_set = {str(item).strip() for item in (charge_leader_names or []) if str(item).strip()}
    pioneer_member_set = {str(item).strip() for item in (pioneer_members or []) if str(item).strip()}
    charge_member_set = {str(item).strip() for item in (charge_members or []) if str(item).strip()}

    if not pioneer_leader_set:
        pioneer_leader_set = {"陈祺", "陈棋"}
    if not charge_leader_set:
        charge_leader_set = {"余浩然"}

    # 生成周标签列表
    week_labels = []
    current = start
    while current <= now:
        week_labels.append(_get_week_label(current))
        current += timedelta(weeks=1)
    if not week_labels or week_labels[-1] != _get_week_label(now):
        week_labels.append(_get_week_label(now))

    # 按周分组统计
    def _empty_week_data() -> dict[str, int]:
        return {"collected_info_count": 0, "signed_count": 0, "recognized_revenue": 0}

    old_weekly: dict[str, dict] = {w: _empty_week_data() for w in week_labels}
    new_weekly: dict[str, dict] = {w: _empty_week_data() for w in week_labels}

    for item in opportunity_list:
        created_at = getattr(item, "created_at", None)
        if not created_at:
            continue
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        week_key = _get_week_label(created_at)
        if week_key not in old_weekly:
            continue

        is_old = _is_old_customer_new_business(item)
        is_new = _is_new_customer_business(item)
        if not is_old and not is_new:
            continue

        target = old_weekly if is_old else new_weekly
        target[week_key]["collected_info_count"] += 1
        if _is_signed(item):
            target[week_key]["signed_count"] += 1
            target[week_key]["recognized_revenue"] += _amount_value(item)

    return {
        "weeks": week_labels,
        "old_customer_new_business": old_weekly,
        "new_customer_business": new_weekly,
    }
