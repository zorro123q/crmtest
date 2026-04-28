"""
数据库驱动的分析接口，服务于仪表盘和漏斗页面。

性能优化说明：
- 原版对所有商机/线索全量加载至 Python 内存后再做 Python 层统计，随数据量增大会严重拖慢接口。
- 重写后所有"计数 / 求和 / 分组"均用 SQL 聚合完成，Python 只做最终格式化拼装。
- 对于确实需要遍历明细的小结果集（如本月 owner 排行、近期动态），
  仍保留少量 Python 处理，但通过 WHERE 条件限制了数据库返回行数。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, case, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import get_current_user
from app.db.session import get_db
from app.models import Lead, Opportunity, User
from app.services.crm_rules_service import (
    DEFAULT_OPPORTUNITY_STAGE,
    LOST_STAGE,
    NEGOTIATION_STAGE,
    QUOTE_STAGE,
    WON_STAGE,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# 活跃阶段（不含赢单/输单）
ACTIVE_OPPORTUNITY_STAGES = (DEFAULT_OPPORTUNITY_STAGE, QUOTE_STAGE, NEGOTIATION_STAGE)
# 仪表盘漏斗阶段（全量）
DASHBOARD_FUNNEL_STAGES = (DEFAULT_OPPORTUNITY_STAGE, QUOTE_STAGE, NEGOTIATION_STAGE, WON_STAGE, LOST_STAGE)
# 客户漏斗阶段
CUSTOMER_FUNNEL_STAGES = (DEFAULT_OPPORTUNITY_STAGE, QUOTE_STAGE, NEGOTIATION_STAGE, WON_STAGE)

# 老客户/新客户标识（custom_fields.customer_type 的合法值）
OLD_CUSTOMER_VALUES = {"老客户", "老客户新部门", "old"}
NEW_CUSTOMER_VALUES = {"新客户", "new"}
OLD_CUSTOMER_VALUES_NORMALIZED = {v.lower() for v in OLD_CUSTOMER_VALUES}
NEW_CUSTOMER_VALUES_NORMALIZED = {v.lower() for v in NEW_CUSTOMER_VALUES}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def start_of_month(day: date) -> date:
    """返回指定日期所在月份的第一天。"""
    return day.replace(day=1)


def end_of_month(day: date) -> date:
    """返回指定日期所在月份的最后一天。"""
    if day.month == 12:
        return date(day.year + 1, 1, 1) - timedelta(days=1)
    return date(day.year, day.month + 1, 1) - timedelta(days=1)


def start_of_quarter(day: date) -> date:
    """返回指定日期所在季度的第一天。"""
    month = ((day.month - 1) // 3) * 3 + 1
    return date(day.year, month, 1)


def start_of_week(day: date) -> date:
    """返回指定日期所在周的第一天（周一，ISO 惯例）。"""
    return day - timedelta(days=day.weekday())


def end_of_quarter(day: date) -> date:
    """返回指定日期所在季度的最后一天。"""
    start = start_of_quarter(day)
    if start.month == 10:
        return date(start.year + 1, 1, 1) - timedelta(days=1)
    return date(start.year, start.month + 3, 1) - timedelta(days=1)


def month_bucket_start(day: date, offset: int) -> date:
    """返回以 day 为基准、偏移 offset 个月的月份第一天。"""
    month = day.month + offset
    year = day.year
    while month <= 0:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return date(year, month, 1)


def normalize_customer_type(value: str | None) -> str | None:
    """将 customer_type 字段值标准化为 'old' | 'new' | None。"""
    raw = str(value or "").strip().lower()
    if raw in OLD_CUSTOMER_VALUES_NORMALIZED:
        return "old"
    if raw in NEW_CUSTOMER_VALUES_NORMALIZED:
        return "new"
    return None


# ---------------------------------------------------------------------------
# 主接口
# ---------------------------------------------------------------------------

@router.get("/overview", summary="仪表盘与漏斗分析（SQL 聚合版）")
async def analytics_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    一次性返回仪表盘所需的全部分析数据，包括：
    - KPI 汇总（本周赢单数、活跃商机数、本季度管道金额、平均赢率）
    - 漏斗各阶段统计
    - 近 3 个月月度业绩
    - 本周 owner 排行
    - 近期动态（最新 5 条）
    - 客户漏斗（老客户 / 新客户）
    """
    today = date.today()
    month_start = start_of_month(today)
    month_end = end_of_month(today)
    quarter_start = start_of_quarter(today)
    quarter_end = end_of_quarter(today)
    week_start = start_of_week(today)
    week_end = today  # 本周统计截止到今天

    # ------------------------------------------------------------------
    # 1. 仪表盘漏斗：各阶段 count / total_amount / avg_probability（SQL 聚合）
    # ------------------------------------------------------------------
    funnel_rows = (
        await db.execute(
            select(
                Opportunity.stage,
                func.count(Opportunity.id).label("cnt"),
                func.coalesce(func.sum(Opportunity.amount), 0).label("total_amount"),
                func.avg(Opportunity.probability).label("avg_prob"),
            ).group_by(Opportunity.stage)
        )
    ).all()
    funnel_map: dict[str, dict] = {
        row.stage: {
            "count": row.cnt,
            "total_amount": float(row.total_amount),
            "avg_probability": round(float(row.avg_prob or 0), 2),
        }
        for row in funnel_rows
    }
    dashboard_funnel = [
        {
            "stage": stage_name,
            "count": funnel_map.get(stage_name, {}).get("count", 0),
            "total_amount": funnel_map.get(stage_name, {}).get("total_amount", 0),
            "avg_probability": funnel_map.get(stage_name, {}).get("avg_probability", 0),
        }
        for stage_name in DASHBOARD_FUNNEL_STAGES
    ]

    # ------------------------------------------------------------------
    # 2. 活跃商机 KPI（SQL 聚合）
    # ------------------------------------------------------------------
    active_kpi = (
        await db.execute(
            select(
                func.count(Opportunity.id).label("active_count"),
                func.avg(Opportunity.probability).label("avg_prob"),
            ).where(Opportunity.stage.in_(ACTIVE_OPPORTUNITY_STAGES))
        )
    ).one()
    active_opportunities_count = active_kpi.active_count or 0
    average_win_rate = round(float(active_kpi.avg_prob or 0), 2)

    # ------------------------------------------------------------------
    # 3. 本周赢单数（SQL 聚合）
    # ------------------------------------------------------------------
    won_this_week_count = (
        await db.execute(
            select(func.count(Opportunity.id)).where(
                and_(
                    Opportunity.stage == WON_STAGE,
                    or_(
                        func.date(Opportunity.closed_at).between(week_start, week_end),
                        and_(
                            Opportunity.closed_at.is_(None),
                            func.date(Opportunity.close_date).between(week_start, week_end),
                        ),
                    ),
                )
            )
        )
    ).scalar() or 0

    # ------------------------------------------------------------------
    # 4. 本季度管道金额（SQL 聚合）
    # ------------------------------------------------------------------
    quarter_pipeline_amount = float(
        (
            await db.execute(
                select(func.coalesce(func.sum(Opportunity.amount), 0)).where(
                    and_(
                        Opportunity.stage.in_(ACTIVE_OPPORTUNITY_STAGES),
                        or_(
                            func.date(Opportunity.close_date).between(quarter_start, quarter_end),
                            and_(
                                Opportunity.close_date.is_(None),
                                func.date(Opportunity.created_at).between(quarter_start, quarter_end),
                            ),
                        ),
                    )
                )
            )
        ).scalar()
        or 0
    )

    # ------------------------------------------------------------------
    # 5. 全量与导入可见性 KPI（SQL 聚合）
    # ------------------------------------------------------------------
    total_leads_count = (await db.execute(select(func.count(Lead.id)))).scalar() or 0
    total_opportunities_count = (await db.execute(select(func.count(Opportunity.id)))).scalar() or 0
    quarter_leads_created_count = (
        await db.execute(
            select(func.count(Lead.id)).where(
                func.date(Lead.created_at).between(quarter_start, quarter_end)
            )
        )
    ).scalar() or 0
    quarter_opportunities_created_count = (
        await db.execute(
            select(func.count(Opportunity.id)).where(
                func.date(Opportunity.created_at).between(quarter_start, quarter_end)
            )
        )
    ).scalar() or 0
    imported_opportunities_count = (
        await db.execute(
            select(func.count(Opportunity.id)).where(Opportunity.source == "import")
        )
    ).scalar() or 0

    # ------------------------------------------------------------------
    # 6. 近 3 个月月度业绩（SQL 聚合）
    # ------------------------------------------------------------------
    monthly_performance = []
    for offset in (-2, -1, 0):
        bucket_start = month_bucket_start(today, offset)
        bucket_end = end_of_month(bucket_start)

        won_amount = float(
            (
                await db.execute(
                    select(func.coalesce(func.sum(Opportunity.amount), 0)).where(
                        and_(
                            Opportunity.stage == WON_STAGE,
                            or_(
                                func.date(Opportunity.closed_at).between(bucket_start, bucket_end),
                                and_(
                                    Opportunity.closed_at.is_(None),
                                    func.date(Opportunity.close_date).between(bucket_start, bucket_end),
                                ),
                            ),
                        )
                    )
                )
            ).scalar()
            or 0
        )
        pipeline_amount = float(
            (
                await db.execute(
                    select(func.coalesce(func.sum(Opportunity.amount), 0)).where(
                        and_(
                            Opportunity.stage.in_(ACTIVE_OPPORTUNITY_STAGES),
                            func.date(Opportunity.created_at).between(bucket_start, bucket_end),
                        )
                    )
                )
            ).scalar()
            or 0
        )
        monthly_performance.append(
            {
                "label": f"{bucket_start.year}-{bucket_start.month:02d}",
                "won_amount": round(won_amount, 2),
                "pipeline_amount": round(pipeline_amount, 2),
            }
        )

    # ------------------------------------------------------------------
    # 7. 本周 owner 排行（Python 分组，支持 custom_fields.owner_name_display）
    # ------------------------------------------------------------------
    # 先取出本周赢单数据，然后 Python 分组（数据量小）
    owner_ranking_source_rows = (
        await db.execute(
            select(
                Opportunity.amount,
                Opportunity.custom_fields,
                User.username,
            )
            .join(User, User.id == Opportunity.owner_id, isouter=True)
            .where(
                and_(
                    Opportunity.stage == WON_STAGE,
                    or_(
                        func.date(Opportunity.closed_at).between(week_start, week_end),
                        and_(
                            Opportunity.closed_at.is_(None),
                            func.date(Opportunity.close_date).between(week_start, week_end),
                        ),
                    ),
                )
            )
        )
    ).all()

    # Python 分组，优先使用 custom_fields.owner_name_display
    ranking_map: dict[str, float] = {}
    for row in owner_ranking_source_rows:
        custom = row.custom_fields or {}
        # 优先使用 Excel 导入的负责人原名，其次使用系统用户名
        owner_name = str(custom.get("owner_name_display") or row.username or "未分配").strip()
        if not owner_name:
            owner_name = "未分配"
        ranking_map[owner_name] = ranking_map.get(owner_name, 0) + float(row.amount or 0)

    owner_ranking = [
        {"owner": owner, "won_amount": round(amount, 2)}
        for owner, amount in sorted(ranking_map.items(), key=lambda item: item[1], reverse=True)
    ]

    # ------------------------------------------------------------------
    # 8. 近期动态（最新 5 条线索 + 5 条商机，限制结果集大小）
    # ------------------------------------------------------------------
    recent_leads = (
        await db.execute(
            select(Lead.name, Lead.status, Lead.updated_at)
            .order_by(Lead.updated_at.desc())
            .limit(5)
        )
    ).all()
    recent_opps = (
        await db.execute(
            select(Opportunity.name, Opportunity.stage, Opportunity.updated_at)
            .order_by(Opportunity.updated_at.desc())
            .limit(5)
        )
    ).all()

    recent_items = [
        {
            "type": "lead",
            "title": row.name,
            "subtitle": f"状态: {row.status}",
            "timestamp": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in recent_leads
    ] + [
        {
            "type": "opportunity",
            "title": row.name,
            "subtitle": f"阶段: {row.stage}",
            "timestamp": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in recent_opps
    ]
    recent_activity = sorted(
        recent_items,
        key=lambda item: item["timestamp"] or "",
        reverse=True,
    )[:5]

    # ------------------------------------------------------------------
    # 9. 客户漏斗（老/新客户，按季度，SQL 聚合）
    # ------------------------------------------------------------------
    # 线索维度统计（本季度）
    quarter_leads_count = (
        await db.execute(
            select(func.count(Lead.id)).where(
                func.date(Lead.created_at).between(quarter_start, quarter_end)
            )
        )
    ).scalar() or 0

    # 注意：customer_type 存储在 custom_fields JSON 中，MySQL 用 JSON_UNQUOTE(JSON_EXTRACT(...)) 提取
    # 这里先 Python 端做分类（数据量受季度范围限制，可接受），避免跨数据库 JSON 函数兼容性问题
    quarter_leads_rows = (
        await db.execute(
            select(Lead.custom_fields)
            .where(func.date(Lead.created_at).between(quarter_start, quarter_end))
        )
    ).all()
    old_leads_count = sum(
        1 for r in quarter_leads_rows
        if normalize_customer_type((r.custom_fields or {}).get("customer_type")) == "old"
    )
    new_leads_count = sum(
        1 for r in quarter_leads_rows
        if normalize_customer_type((r.custom_fields or {}).get("customer_type")) == "new"
    )

    # 本季度赢单商机统计
    quarter_won_rows = (
        await db.execute(
            select(Opportunity.amount, Opportunity.custom_fields, Opportunity.stage, Opportunity.closed_at, Opportunity.close_date)
            .where(
                and_(
                    Opportunity.stage == WON_STAGE,
                    or_(
                        func.date(Opportunity.closed_at).between(quarter_start, quarter_end),
                        and_(
                            Opportunity.closed_at.is_(None),
                            func.date(Opportunity.close_date).between(quarter_start, quarter_end),
                        ),
                    ),
                )
            )
        )
    ).all()
    old_signed_amount = sum(
        float(r.amount or 0) for r in quarter_won_rows
        if normalize_customer_type((r.custom_fields or {}).get("customer_type")) == "old"
    )
    new_signed_amount = sum(
        float(r.amount or 0) for r in quarter_won_rows
        if normalize_customer_type((r.custom_fields or {}).get("customer_type")) == "new"
    )

    # 本季度漏斗（按客户类型细分各阶段）
    quarter_opp_rows = (
        await db.execute(
            select(Opportunity.stage, Opportunity.amount, Opportunity.custom_fields)
            .where(func.date(Opportunity.created_at).between(quarter_start, quarter_end))
        )
    ).all()

    def build_customer_funnel_from_rows(rows, customer_type_filter: str):
        """从已取出的商机明细中，按客户类型过滤并构建各阶段漏斗。"""
        filtered = [
            r for r in rows
            if normalize_customer_type((r.custom_fields or {}).get("customer_type")) == customer_type_filter
        ]
        result = []
        for stage_name in CUSTOMER_FUNNEL_STAGES:
            stage_items = [r for r in filtered if r.stage == stage_name]
            total_amount = sum(float(r.amount or 0) for r in stage_items)
            result.append(
                {
                    "stage": stage_name,
                    "count": len(stage_items),
                    "amount": round(total_amount, 2),
                    "avg_amount": round(total_amount / len(stage_items), 2) if stage_items else 0,
                }
            )
        return result

    old_customer_funnel = build_customer_funnel_from_rows(quarter_opp_rows, "old")
    new_customer_funnel = build_customer_funnel_from_rows(quarter_opp_rows, "new")

    # ------------------------------------------------------------------
    # 组装返回值
    # ------------------------------------------------------------------
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "periods": {
            "today": today.isoformat(),
            "month_start": month_start.isoformat(),
            "month_end": month_end.isoformat(),
            "quarter_start": quarter_start.isoformat(),
            "quarter_end": quarter_end.isoformat(),
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
        },
        "dashboard": {
            "total_pipeline_amount_this_quarter": round(quarter_pipeline_amount, 2),
            "total_won_deals_this_week": won_this_week_count,
            "active_opportunities_count": active_opportunities_count,
            "average_win_rate": average_win_rate,
            "total_leads_count": total_leads_count,
            "total_opportunities_count": total_opportunities_count,
            "quarter_leads_created_count": quarter_leads_created_count,
            "quarter_opportunities_created_count": quarter_opportunities_created_count,
            "imported_opportunities_count": imported_opportunities_count,
            "funnel_stages": dashboard_funnel,
            "monthly_performance": monthly_performance,
            "owner_ranking_this_week": owner_ranking,
            "recent_activity": recent_activity,
        },
        "customer_funnel": {
            "customer_information_collected_count": quarter_leads_count,
            "old_customer_information_collected_count": old_leads_count,
            "old_customer_signed_payment_amount": round(old_signed_amount, 2),
            "new_customer_information_collected_count": new_leads_count,
            "new_customer_signed_payment_amount": round(new_signed_amount, 2),
            "unclassified_information_count": quarter_leads_count - old_leads_count - new_leads_count,
            "unclassified_signed_payment_amount": round(
                sum(float(r.amount or 0) for r in quarter_won_rows) - old_signed_amount - new_signed_amount,
                2,
            ),
            "old_customer_stages": old_customer_funnel,
            "new_customer_stages": new_customer_funnel,
        },
    }
