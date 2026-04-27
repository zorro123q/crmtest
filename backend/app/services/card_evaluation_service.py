from __future__ import annotations

from typing import Any, Mapping

from app.services.scoring_service import (
    calculate_card_score,
    get_max_score,
    get_scoring_field_keys,
    get_scoring_fields,
    normalize_card_type,
    normalize_scoring_dimensions,
)


CARD_COPY: dict[str, dict[str, dict[str, str]]] = {
    "A": {
        "A": {
            "label": "A卡 · 高意向客户",
            "desc": "正式评分达到 A 级，客户意向和客户价值较高，建议立即安排关键人深度沟通。",
            "suggestion": "优先推进需求澄清、预算确认和采购路径确认，保持高频跟进。",
        },
        "B": {
            "label": "A卡 · 值得重点跟进",
            "desc": "正式评分达到 B 级，客户价值较好，建议尽快补齐剩余关键信息。",
            "suggestion": "围绕场景、预算、负责人和区域继续补充信息，维持稳定跟进节奏。",
        },
        "C": {
            "label": "A卡 · 持续观察",
            "desc": "正式评分达到 C 级，客户基础条件一般，需要继续判断真实意向和价值。",
            "suggestion": "先确认场景匹配度和预算区间，再决定是否投入更多资源。",
        },
        "D": {
            "label": "A卡 · 谨慎投入",
            "desc": "正式评分达到 D 级，当前客户价值偏弱，不宜过早投入过多精力。",
            "suggestion": "保持基础联系，等待预算、采购方式或需求成熟后再加大推进力度。",
        },
        "E": {
            "label": "A卡 · 暂不优先",
            "desc": "正式评分达到 E 级，当前客户价值有限，暂不建议作为重点对象推进。",
            "suggestion": "保留基础触达即可，将资源优先分配给更高确定性的客户。",
        },
    },
    "B": {
        "A": {
            "label": "B卡 · 高转合同商机",
            "desc": "评分达到 A 级，商机已具备较强的转合同确定性，适合集中资源推进签约。",
            "suggestion": "并行推进商务谈判、合同条款确认和决策链锁定，尽快收敛到签约动作。",
        },
        "B": {
            "label": "B卡 · 重点推进商机",
            "desc": "评分达到 B 级，商机基础较好，仍有明确成交机会，适合继续高频推进。",
            "suggestion": "补强预算确认、关键人认同和竞争策略，推动项目进入更明确的签约阶段。",
        },
        "C": {
            "label": "B卡 · 需继续验证",
            "desc": "评分达到 C 级，商机存在推进基础，但转合同关键条件还不够稳固。",
            "suggestion": "优先核实预算、POC结果和内部评审状态，避免过早投入过重交付资源。",
        },
        "D": {
            "label": "B卡 · 谨慎跟进",
            "desc": "评分达到 D 级，当前商机离合同转化仍有明显差距，需要谨慎评估投入产出。",
            "suggestion": "控制推进成本，重点确认需求清晰度、关键人支持度和内部可行性是否会改善。",
        },
    },
}

SOURCE_MANUAL = "manual"
SOURCE_AI = "ai"
SOURCE_NONE = "none"


def empty_dimensions(card_type: str = "A") -> dict[str, str | None]:
    return {field_name: None for field_name in get_scoring_field_keys(card_type)}


def normalize_dimensions(
    dimensions: Mapping[str, Any] | None,
    *,
    card_type: str = "A",
) -> dict[str, str | None]:
    if dimensions is None:
        return empty_dimensions(card_type)
    return normalize_scoring_dimensions(dimensions, card_type=card_type, allow_extra=False)


def merge_dimensions(
    ai_dimensions: Mapping[str, Any] | None,
    manual_dimensions: Mapping[str, Any] | None,
    *,
    card_type: str = "A",
) -> tuple[dict[str, str | None], dict[str, str]]:
    normalized_card_type = normalize_card_type(card_type)
    normalized_ai = normalize_dimensions(ai_dimensions, card_type=normalized_card_type)
    normalized_manual = normalize_dimensions(manual_dimensions, card_type=normalized_card_type)
    merged: dict[str, str | None] = {}
    sources: dict[str, str] = {}

    for field_name in get_scoring_field_keys(normalized_card_type):
        manual_value = normalized_manual.get(field_name)
        ai_value = normalized_ai.get(field_name)
        if manual_value is not None:
            merged[field_name] = manual_value
            sources[field_name] = SOURCE_MANUAL
        elif ai_value is not None:
            merged[field_name] = ai_value
            sources[field_name] = SOURCE_AI
        else:
            merged[field_name] = None
            sources[field_name] = SOURCE_NONE

    return merged, sources


def evaluate_card(
    card_type: str,
    *,
    ai_dimensions: Mapping[str, Any] | None = None,
    manual_dimensions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_card_type = normalize_card_type(card_type)
    if normalized_card_type not in CARD_COPY:
        raise ValueError("Unsupported card type")

    normalized_ai = (
        normalize_dimensions(ai_dimensions, card_type=normalized_card_type)
        if ai_dimensions is not None
        else None
    )
    normalized_manual = (
        normalize_dimensions(manual_dimensions, card_type=normalized_card_type)
        if manual_dimensions is not None
        else None
    )
    merged_dimensions, sources = merge_dimensions(
        normalized_ai,
        normalized_manual,
        card_type=normalized_card_type,
    )
    scoring = calculate_card_score(normalized_card_type, merged_dimensions)
    copy = CARD_COPY[normalized_card_type][scoring.card_level]
    field_map = get_scoring_fields(normalized_card_type)

    dimensions: list[dict[str, Any]] = []
    for field_name in get_scoring_field_keys(normalized_card_type):
        field_meta = field_map[field_name]
        detail = scoring.detail[field_name]
        max_score = max(option_meta["score"] for option_meta in field_meta["options"].values())
        dimensions.append(
            {
                "key": field_name,
                "name": field_meta["label"],
                "score": detail["score"],
                "max_score": max_score,
                "selected_value": detail["value"],
                "selected_label": detail["value_label"],
                "source": sources[field_name],
            }
        )

    return {
        "card_type": normalized_card_type,
        "normalized_score": scoring.total_score,
        "raw_score": scoring.total_score,
        "raw_max_score": get_max_score(normalized_card_type),
        "grade": scoring.card_level,
        "grade_label": copy["label"],
        "rating_desc": copy["desc"],
        "suggestion": copy["suggestion"],
        "ai_dimensions": normalized_ai,
        "manual_dimensions": normalized_manual,
        "merged_dimensions": merged_dimensions,
        "dimensions": dimensions,
    }
