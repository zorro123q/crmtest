"""
Scoring rules for leads and card evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


LEGACY_SCORING_FIELDS: dict[str, dict[str, Any]] = {
    "industry": {
        "label": "行业",
        "options": {
            "finance": {"label": "金融", "score": 5},
            "insurance": {"label": "保险", "score": 5},
            "logistics": {"label": "物流", "score": 4},
            "manufacturing": {"label": "制造业", "score": 4},
            "retail": {"label": "零售", "score": 4},
            "other_large_customer_service": {"label": "其他大客服规模行业", "score": 3},
            "other": {"label": "其他", "score": 0},
        },
    },
    "industry_rank": {
        "label": "行业排名",
        "options": {
            "top_1_10": {"label": "1 到 10 名", "score": 5},
            "top_11_20": {"label": "11 到 20 名", "score": 3},
            "top_21_30": {"label": "21 到 30 名", "score": 2},
            "above_30": {"label": "30 名以后", "score": 1},
        },
    },
    "scene": {
        "label": "场景",
        "options": {
            "logistics_outbound_calls": {"label": "物流外呼", "score": 5},
            "financial_marketing": {"label": "金融营销", "score": 5},
            "intelligent_callback": {"label": "智能回呼", "score": 10},
            "financial_collection": {"label": "金融催收", "score": 10},
            "insurance_marketing": {"label": "保险营销", "score": 10},
            "voice_portal": {"label": "语音门户", "score": 10},
            "appliance_installation_repair_scheduling": {"label": "家电安装维修预约", "score": 10},
            "insurance_claim_reporting": {"label": "保险报案", "score": 10},
            "large_model_application": {"label": "大模型应用", "score": 5},
            "capacity_expansion": {"label": "扩容", "score": 5},
            "similar_cross_industry": {"label": "异行业相似场景", "score": 5},
            "other": {"label": "其他", "score": 1},
        },
    },
    "budget": {
        "label": "预算",
        "options": {
            "above_3_million": {"label": "300 万以上", "score": 5},
            "between_2_and_3_million": {"label": "200 到 300 万", "score": 3},
            "around_1_million": {"label": "100 万左右", "score": 2},
            "between_0_5_and_1_million": {"label": "50 到 100 万", "score": 1},
            "below_0_5_million": {"label": "50 万以下", "score": 0},
        },
    },
    "labor_cost": {
        "label": "人力成本",
        "options": {
            "above_6000": {"label": "6000 以上", "score": 5},
            "between_5000_and_6000": {"label": "5000 到 6000", "score": 4},
            "between_4000_and_5000": {"label": "4000 到 5000", "score": 3},
            "between_3000_and_4000": {"label": "3000 到 4000", "score": 2},
            "between_2000_and_3000": {"label": "2000 到 3000", "score": 1},
            "below_2000": {"label": "2000 以下", "score": 0},
        },
    },
    "daily_calls": {
        "label": "人均日呼量",
        "options": {
            "below_60": {"label": "60 通以下每天", "score": 4},
            "between_60_and_80": {"label": "60 到 80 通每天", "score": 3},
            "between_80_and_100": {"label": "80 到 100 通每天", "score": 2},
            "above_100": {"label": "100 通以上每天", "score": 1},
        },
    },
    "leader_owner": {
        "label": "负责人分管",
        "options": {
            "business_and_technology": {"label": "同时分管业务和技术", "score": 5},
            "business": {"label": "分管业务", "score": 3},
            "technology": {"label": "分管技术", "score": 1},
        },
    },
    "lowest_price": {
        "label": "是否最低价",
        "options": {
            "no": {"label": "否", "score": 3},
            "yes": {"label": "是", "score": 1},
        },
    },
    "initiator_department": {
        "label": "发起部门",
        "options": {
            "business": {"label": "业务部门", "score": 5},
            "technology": {"label": "技术部门", "score": 2},
        },
    },
    "competitor": {
        "label": "竞争情况",
        "options": {
            "no_competitor": {"label": "无竞争对手", "score": 4},
            "competitor_without_bat": {"label": "有竞争对手，不含 BAT", "score": 2},
            "competitor_with_bat": {"label": "有竞争对手，含 BAT", "score": 1},
            "more_than_5_competitors": {"label": "竞争对手超过 5 家", "score": 0},
        },
    },
    "bidding_type": {
        "label": "招采方式",
        "options": {
            "single_source_procurement": {"label": "单一来源采购", "score": 30},
            "invitational_controllable": {"label": "邀标，可控", "score": 20},
            "invitational_uncontrollable": {"label": "邀标，不可控", "score": 5},
            "public_bidding": {"label": "公开招标", "score": 0},
        },
    },
    "has_ai_project": {
        "label": "是否有 AI 项目",
        "options": {
            "yes": {"label": "是", "score": 4},
            "no": {"label": "否", "score": 1},
        },
    },
    "customer_service_size": {
        "label": "客服规模",
        "options": {
            "above_500": {"label": "500 席以上", "score": 5},
            "between_300_and_500": {"label": "300 到 500 席", "score": 3},
            "between_100_and_300": {"label": "100 到 300 席", "score": 2},
            "below_100": {"label": "100 席以下", "score": 1},
        },
    },
    "region": {
        "label": "区域",
        "options": {
            "bj_sh_gz_sz": {"label": "北上广深", "score": 10},
            "tier_1": {"label": "新一线城市", "score": 8},
            "tier_2": {"label": "二线城市", "score": 5},
            "tier_3": {"label": "三线城市", "score": 3},
            "tier_4": {"label": "四线城市", "score": 1},
        },
    },
}

B_CARD_SCORING_FIELDS: dict[str, dict[str, Any]] = {
    "customer_relationship": {
        "label": "客户关系",
        "options": {
            "old_customer": {"label": "老客户", "score": 10},
            "new_customer_middle_or_above": {"label": "新客户（接触中层及以上）", "score": 6},
            "new_customer_other": {"label": "新客户（其他）", "score": 2},
        },
    },
    "requirement_clarity": {
        "label": "需求清晰度",
        "options": {
            "clear": {"label": "清晰", "score": 10},
            "medium": {"label": "一般", "score": 6},
            "unclear": {"label": "不清晰", "score": 2},
        },
    },
    "budget_level": {
        "label": "客户预算",
        "options": {
            "enough": {"label": "预算充足", "score": 5},
            "medium": {"label": "预算适中", "score": 3},
            "low": {"label": "预算不足", "score": 1},
        },
    },
    "deal_cycle": {
        "label": "预估成交周期",
        "options": {
            "short": {"label": "1-3个月", "score": 3},
            "medium": {"label": "3-6个月", "score": 1},
            "long": {"label": "6个月以上", "score": 0},
        },
    },
    "opportunity_level": {
        "label": "商机等级",
        "options": {
            "A": {"label": "A级", "score": 2},
            "B": {"label": "B级", "score": 1.5},
            "C": {"label": "C级", "score": 1},
            "D": {"label": "D级", "score": 0.5},
        },
    },
    "internal_review_status": {
        "label": "内部立项评审",
        "options": {
            "passed": {"label": "已通过", "score": 15},
            "not_passed": {"label": "未通过", "score": 5},
        },
    },
    "poc_result": {
        "label": "POC情况",
        "options": {
            "success": {"label": "POC成功", "score": 15},
            "partial_success": {"label": "POC部分成功", "score": 8},
            "failed": {"label": "POC失败", "score": 2},
        },
    },
    "key_person_acceptance": {
        "label": "关键人认同度",
        "options": {
            "full": {"label": "完全认同", "score": 10},
            "partial": {"label": "部分认同", "score": 6},
            "none": {"label": "不认同", "score": 2},
        },
    },
    "initiator_department": {
        "label": "项目发起部门",
        "options": {
            "core_business": {"label": "核心业务部门", "score": 10},
            "support": {"label": "支持部门", "score": 6},
            "edge": {"label": "边缘部门", "score": 2},
        },
    },
    "competition_status": {
        "label": "竞争状态",
        "options": {
            "no_competitor": {"label": "无竞品", "score": 10},
            "has_competitor_but_advantage": {"label": "有竞品但优势明显", "score": 6},
            "strong_competition": {"label": "有竞品且竞争激烈", "score": 2},
        },
    },
    "service_team_size": {
        "label": "客服人数",
        "options": {
            "large": {"label": "百人以上", "score": 10},
            "medium": {"label": "50-100人", "score": 6},
            "small": {"label": "50人以下", "score": 2},
        },
    },
}

SCORING_MODELS: dict[str, dict[str, Any]] = {
    "A": {"fields": LEGACY_SCORING_FIELDS},
    "B": {"fields": B_CARD_SCORING_FIELDS},
}

# Backward-compatible aliases for legacy lead/opportunity code.
SCORING_FIELDS = LEGACY_SCORING_FIELDS
SCORING_FIELD_KEYS = tuple(LEGACY_SCORING_FIELDS.keys())


@dataclass(slots=True)
class ScoreResult:
    dimensions: dict[str, str | None]
    detail: dict[str, dict[str, Any]]
    total_score: int | float
    card_level: str


def normalize_card_type(card_type: str | None) -> str:
    normalized = str(card_type or "A").strip().upper() or "A"
    if normalized not in SCORING_MODELS:
        raise ValueError(f"Unsupported card type: {card_type}")
    return normalized


def get_scoring_fields(card_type: str | None = "A") -> dict[str, dict[str, Any]]:
    return SCORING_MODELS[normalize_card_type(card_type)]["fields"]


def get_scoring_field_keys(card_type: str | None = "A") -> tuple[str, ...]:
    return tuple(get_scoring_fields(card_type).keys())


def get_max_score(card_type: str | None = "A") -> int | float:
    total = 0
    for field_meta in get_scoring_fields(card_type).values():
        total += max(option_meta["score"] for option_meta in field_meta["options"].values())
    return _normalize_numeric(total)


def is_valid_option(field_name: str, value: str | None, card_type: str | None = "A") -> bool:
    if value in (None, ""):
        return True
    field = get_scoring_fields(card_type).get(field_name)
    return bool(field and value in field["options"])


def normalize_scoring_dimensions(
    payload: Mapping[str, Any] | dict[str, Any],
    card_type: str | None = "A",
    *,
    allow_extra: bool = True,
) -> dict[str, str | None]:
    fields = get_scoring_fields(card_type)
    field_keys = tuple(fields.keys())
    payload_dict = dict(payload or {})

    if not allow_extra:
        extra_fields = sorted(set(payload_dict.keys()) - set(field_keys))
        if extra_fields:
            raise ValueError(f"Invalid scoring fields: {', '.join(extra_fields)}")

    dimensions: dict[str, str | None] = {}
    for field_name in field_keys:
        value = payload_dict.get(field_name)
        normalized = str(value).strip() if value is not None else None
        if normalized == "":
            normalized = None
        if not is_valid_option(field_name, normalized, card_type=card_type):
            raise ValueError(f"Invalid scoring option for {field_name}: {value}")
        dimensions[field_name] = normalized
    return dimensions


def calculate_card_level(score: int | float, card_type: str | None = "A") -> str:
    normalized_card_type = normalize_card_type(card_type)
    numeric_score = float(score)

    if normalized_card_type == "B":
        if numeric_score >= 85:
            return "A"
        if numeric_score >= 70:
            return "B"
        if numeric_score >= 55:
            return "C"
        return "D"

    if numeric_score < 20:
        return "E"
    if numeric_score < 40:
        return "D"
    if numeric_score < 60:
        return "C"
    if numeric_score < 70:
        return "B"
    return "A"


def calculate_card_score(
    card_type_or_payload: str | Mapping[str, Any] | dict[str, Any],
    payload: Mapping[str, Any] | dict[str, Any] | None = None,
) -> ScoreResult:
    if payload is None and isinstance(card_type_or_payload, Mapping):
        card_type = "A"
        payload_dict = dict(card_type_or_payload)
    else:
        card_type = normalize_card_type(str(card_type_or_payload))
        if payload is None:
            raise TypeError("calculate_card_score requires a payload")
        payload_dict = dict(payload)

    dimensions = normalize_scoring_dimensions(payload_dict, card_type=card_type)
    fields = get_scoring_fields(card_type)
    detail: dict[str, dict[str, Any]] = {}
    total_score: int | float = 0

    for field_name in get_scoring_field_keys(card_type):
        selected_value = dimensions.get(field_name)
        field_meta = fields[field_name]
        option_meta = field_meta["options"].get(selected_value)
        score = _normalize_numeric(option_meta["score"] if option_meta else 0)
        total_score = _normalize_numeric(total_score + score)
        detail[field_name] = {
            "label": field_meta["label"],
            "value": selected_value,
            "value_label": option_meta["label"] if option_meta else None,
            "score": score,
        }

    total_score = _normalize_numeric(total_score)
    return ScoreResult(
        dimensions=dimensions,
        detail=detail,
        total_score=total_score,
        card_level=calculate_card_level(total_score, card_type=card_type),
    )


def scoring_options_payload(card_type: str | None = "A") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field_name, field_meta in get_scoring_fields(card_type).items():
        rows.append(
            {
                "field": field_name,
                "label": field_meta["label"],
                "options": [
                    {
                        "value": option_value,
                        "label": option_meta["label"],
                        "score": option_meta["score"],
                    }
                    for option_value, option_meta in field_meta["options"].items()
                ],
            }
        )
    return rows


def _normalize_numeric(value: int | float) -> int | float:
    if isinstance(value, bool):
        return int(value)
    numeric = float(value)
    if numeric.is_integer():
        return int(numeric)
    return numeric
