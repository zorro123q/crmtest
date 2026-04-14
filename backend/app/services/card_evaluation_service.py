import re
from typing import Dict, List, Tuple


A_CARD_DIMS = [
    {"key": "industry", "name": "客户行业", "max_score": 5},
    {"key": "rank", "name": "行业排名", "max_score": 5},
    {"key": "scenario", "name": "客户场景", "max_score": 10},
    {"key": "budget", "name": "客户预算", "max_score": 5},
    {"key": "labor", "name": "人力成本", "max_score": 5},
    {"key": "leadership", "name": "项目推动领导分管", "max_score": 5},
    {"key": "bid", "name": "招标形式", "max_score": 5},
    {"key": "headcount", "name": "客服人数", "max_score": 5},
    {"key": "region", "name": "客户所在区域", "max_score": 10},
]

B_CARD_DIMS = [
    {"key": "match", "name": "客户需求匹配度", "max_score": 15},
    {"key": "budget_clear", "name": "预算明确度", "max_score": 10},
    {"key": "decision", "name": "决策链清晰度", "max_score": 10},
    {"key": "competition", "name": "竞争分析", "max_score": 10},
    {"key": "feasibility", "name": "方案可行性", "max_score": 10},
    {"key": "intent", "name": "客户合作意向", "max_score": 15},
    {"key": "timeline", "name": "项目时间紧迫性", "max_score": 10},
    {"key": "history", "name": "历史合作记录", "max_score": 10},
]

GRADES = [
    {"grade": "A", "min_score": 70, "label": "A级 - 重点跟进", "desc": "70 分以上，值得重点跟进，建议按周推进。"},
    {"grade": "B", "min_score": 60, "label": "B级 - 值得跟进", "desc": "60-69 分，建议保持稳定沟通，争取尽快进入下一阶段。"},
    {"grade": "C", "min_score": 40, "label": "C级 - 保持联系", "desc": "40-59 分，需要继续补充信息，观察客户变化。"},
    {"grade": "D", "min_score": 20, "label": "D级 - 谨慎投入", "desc": "20-39 分，可以保持联系，但不建议投入过多资源。"},
    {"grade": "E", "min_score": 0, "label": "E级 - 暂不优先", "desc": "20 分以下，暂不建议作为重点机会推进。"},
]

A_SUGGESTIONS = {
    "A": "重点客户。建议本周内安排负责人深入拜访，明确需求、预算和采购路径。",
    "B": "优质线索。建议一周内安排电话会议或线上演示，保持每周一次沟通节奏。",
    "C": "普通线索。建议持续跟进客户动态，补齐预算、场景和决策信息。",
    "D": "优先级较低。建议降低投入频次，等关键条件更明确后再推进。",
    "E": "暂时价值有限。保留基础联系即可，把精力优先投向更明确的客户。",
}

B_SUGGESTIONS = {
    "A": "高价值商机。建议立即推进方案、商务和决策链确认，尽快锁定下一步动作。",
    "B": "较好商机。建议一周内组织演示或POC，推动客户完成内部决策。",
    "C": "中等商机。建议继续澄清痛点、预算和时间表，避免过早投入大量资源。",
    "D": "较弱商机。建议控制投入，重点确认预算和真实采购意愿。",
    "E": "当前阶段不具备明显机会。建议先观察，不作为重点项目推进。",
}

INDUSTRY_SCORES = {
    "金融": 5,
    "保险": 5,
    "物流": 4,
    "通信": 5,
    "零售": 4,
    "制造": 4,
    "政务": 5,
    "其他": 3,
}


def evaluate_card(card_type: str, text: str = "", industry: str | None = None, amount: float | None = None) -> Dict:
    normalized_text = (text or "").lower()

    if card_type == "A":
        scores = _evaluate_a_card(normalized_text, industry)
        dims = A_CARD_DIMS
        suggestions = A_SUGGESTIONS
    elif card_type == "B":
        scores = _evaluate_b_card(normalized_text, amount)
        dims = B_CARD_DIMS
        suggestions = B_SUGGESTIONS
    else:
        raise ValueError("不支持的卡片类型")

    raw_score = sum(scores[item["key"]] for item in dims)
    raw_max_score = sum(item["max_score"] for item in dims)
    normalized_score = round(raw_score / raw_max_score * 100) if raw_max_score else 0
    grade_info = _resolve_grade(normalized_score)

    return {
        "card_type": card_type,
        "normalized_score": normalized_score,
        "raw_score": raw_score,
        "raw_max_score": raw_max_score,
        "grade": grade_info["grade"],
        "grade_label": grade_info["label"],
        "rating_desc": grade_info["desc"],
        "suggestion": suggestions[grade_info["grade"]],
        "dimensions": [
            {
                "key": item["key"],
                "name": item["name"],
                "score": scores[item["key"]],
                "max_score": item["max_score"],
            }
            for item in dims
        ],
    }


def _evaluate_a_card(text: str, industry: str | None) -> Dict[str, int]:
    industry_value = (industry or "").strip()
    scores = {
        "industry": _score_industry(text, industry_value),
        "rank": _score_rank(text),
        "scenario": _score_scenario(text),
        "budget": _score_a_budget(text),
        "labor": _score_labor(text),
        "leadership": _score_leadership(text),
        "bid": _score_bid(text),
        "headcount": _score_headcount(text),
        "region": _score_region(text),
    }
    return scores


def _evaluate_b_card(text: str, amount: float | None) -> Dict[str, int]:
    scores = {
        "match": _score_match(text),
        "budget_clear": _score_b_budget(text, amount),
        "decision": _score_decision(text),
        "competition": _score_competition(text),
        "feasibility": _score_feasibility(text),
        "intent": _score_intent(text),
        "timeline": _score_timeline(text),
        "history": _score_history(text),
    }
    return scores


def _resolve_grade(normalized_score: int) -> Dict[str, str | int]:
    for item in GRADES:
        if normalized_score >= item["min_score"]:
            return item
    return GRADES[-1]


def _score_industry(text: str, industry: str) -> int:
    if industry:
        return INDUSTRY_SCORES.get(industry, 3)
    if _contains_any(text, ["金融", "银行", "证券"]):
        return 5
    if "保险" in text:
        return 5
    if _contains_any(text, ["物流", "快递", "供应链"]):
        return 4
    if _contains_any(text, ["通信", "运营商", "电信", "移动", "联通"]):
        return 5
    if _contains_any(text, ["零售", "电商", "门店", "商超"]):
        return 4
    if _contains_any(text, ["制造", "工厂", "产线"]):
        return 4
    if _contains_any(text, ["政务", "政府", "公共服务"]):
        return 5
    return 3


def _score_rank(text: str) -> int:
    if _contains_any(text, ["top3", "top 3", "前三"]):
        return 5
    if "前十" in text or "top10" in text or "top 10" in text:
        return 4
    if re.search(r"\b11\s*-\s*20\b", text):
        return 3
    if re.search(r"\b20\s*-\s*30\b", text):
        return 2
    if "30后" in text or "三十名后" in text:
        return 1
    return 3


def _score_scenario(text: str) -> int:
    if _contains_any(text, ["智能回访", "回访", "金融催收", "催收", "智能质检", "质检"]):
        return 10
    if _contains_any(text, ["语音客服", "客服", "外呼", "营销", "人机协同"]):
        return 8
    return 6


def _score_a_budget(text: str) -> int:
    budget_value = _extract_wan_budget(text)
    if budget_value >= 300:
        return 5
    if budget_value >= 200:
        return 4
    if budget_value >= 100:
        return 3
    if budget_value >= 50:
        return 2
    if budget_value > 0:
        return 1
    return 2


def _score_labor(text: str) -> int:
    number = _extract_people_number(text)
    if number >= 6000:
        return 5
    if number >= 5000:
        return 4
    if number >= 4000:
        return 3
    return 3


def _score_leadership(text: str) -> int:
    has_business = _contains_any(text, ["业务", "运营", "客服负责人"])
    has_tech = _contains_any(text, ["技术", "cto", "cio", "it", "信息化"])
    if has_business and has_tech:
        return 5
    if has_business:
        return 3
    if has_tech:
        return 1
    return 3


def _score_bid(text: str) -> int:
    if _contains_any(text, ["单一来源", "单一采购"]):
        return 5
    if _contains_any(text, ["邀标", "邀请招标"]):
        return 4
    if "公开招标" in text:
        return 2
    if _contains_any(text, ["竞标", "比选", "招投标"]):
        return 3
    return 3


def _score_headcount(text: str) -> int:
    number = _extract_people_number(text)
    if number >= 500:
        return 5
    if number >= 300:
        return 4
    if number >= 100:
        return 3
    return 3


def _score_region(text: str) -> int:
    if _contains_any(text, ["北京", "上海", "广州", "深圳", "一线城市"]):
        return 10
    if _contains_any(text, ["省会", "杭州", "南京", "武汉", "成都", "西安", "长沙", "苏州"]):
        return 6
    return 4


def _score_match(text: str) -> int:
    if _contains_any(text, ["高度匹配", "完全匹配"]):
        return 15
    if "匹配" in text:
        return 12
    if _contains_any(text, ["一般", "还行", "可尝试"]):
        return 8
    if _contains_any(text, ["不匹配", "偏弱", "较差"]):
        return 4
    return 8


def _score_b_budget(text: str, amount: float | None) -> int:
    if amount is not None:
        if amount >= 100:
            return 10
        if amount >= 50:
            return 7
        return 5
    if _contains_any(text, ["预算明确", "预算已批", "资金落实"]):
        return 10
    if "预算" in text:
        return 7
    return 5


def _score_decision(text: str) -> int:
    if _contains_any(text, ["决策链清晰", "决策人明确", "拍板人明确"]):
        return 10
    if _contains_any(text, ["老板", "总经理", "总监", "cto", "cio"]):
        return 8
    return 6


def _score_competition(text: str) -> int:
    if _contains_any(text, ["优势明显", "竞争力强"]):
        return 10
    if "略有优势" in text:
        return 7
    if _contains_any(text, ["均势", "势均力敌", "竞品"]):
        return 5
    if _contains_any(text, ["劣势", "处于下风"]):
        return 2
    return 7


def _score_feasibility(text: str) -> int:
    if _contains_any(text, ["可行", "可以做", "落地没问题"]):
        return 10
    if "较可行" in text:
        return 7
    if _contains_any(text, ["有难度", "实施难"]):
        return 4
    if _contains_any(text, ["很难", "不可行"]):
        return 2
    return 7


def _score_intent(text: str) -> int:
    if "强烈" in text:
        return 15
    if _contains_any(text, ["较强", "意向明确", "积极推进"]):
        return 12
    if _contains_any(text, ["一般", "考虑中", "还在看"]):
        return 6
    if _contains_any(text, ["较弱", "兴趣不大"]):
        return 3
    if _contains_any(text, ["无意向", "没有意向"]):
        return 1
    return 8


def _score_timeline(text: str) -> int:
    if _contains_any(text, ["紧急", "尽快", "加急", "本月上线"]):
        return 10
    if _contains_any(text, ["较急", "季度内上线"]):
        return 7
    if _contains_any(text, ["不急", "慢慢来"]):
        return 3
    if "一般" in text:
        return 5
    return 6


def _score_history(text: str) -> int:
    if _contains_any(text, ["多次合作", "老客户", "续约"]):
        return 10
    if _contains_any(text, ["一次合作", "合作过一次"]):
        return 7
    if _contains_any(text, ["接触过", "有过沟通"]):
        return 4
    if _contains_any(text, ["全新客户", "首次接触"]):
        return 5
    return 5


def _contains_any(text: str, keywords: List[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _extract_wan_budget(text: str) -> float:
    patterns: List[Tuple[str, float]] = [
        (r"(\d+(?:\.\d+)?)\s*万", 1),
        (r"(\d+(?:\.\d+)?)\s*w\b", 1),
        (r"(\d+(?:\.\d+)?)\s*万元", 1),
        (r"(\d+(?:\.\d+)?)\s*元", 0.0001),
    ]
    for pattern, multiplier in patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1)) * multiplier
    return 0


def _extract_people_number(text: str) -> int:
    patterns = [
        r"(\d+)\s*人",
        r"(\d+)\s*席",
        r"(\d+)\s*名",
        r"(\d+)\s*坐席",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return 0
