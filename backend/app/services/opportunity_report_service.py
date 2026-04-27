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