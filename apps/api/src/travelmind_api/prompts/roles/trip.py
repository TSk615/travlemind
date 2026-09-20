from __future__ import annotations

import json
from typing import Any

from travelmind_api.prompts.types import RolePromptSpec


BRIEF_PARSER_PROMPT_VERSION = "trip.brief_parser.v2"
BRIEF_OUTPUT_SCHEMA: dict[str, Any] = {
    "destination": "Kyoto",
    "trip_days": 2,
    "budget_band": "midrange",
    "budget_is_hard_constraint": True,
    "budget_priority": "balance tickets and transport before adding optional upgrades",
    "allow_budget_flex": False,
    "pace": "balanced",
    "must_have": ["temples", "coffee"],
    "avoid": ["overpacked long-distance transfers"],
    "transport": "rail",
    "accommodation": "quiet boutique hotel",
    "interests": ["temples", "coffee"],
    "planning_constraints": ["keep sequencing realistic", "respect budget and pace"],
}


def build_brief_parser_prompt() -> RolePromptSpec:
    system_prompt = (
        "你是 TravelMind 需求解析专家。只返回一个紧凑的 planning brief JSON 对象。"
        "不要输出 markdown，不要解释，不要开始编排行程。"
        "必须明确预算规则：预算是否是硬约束、主要成本优先级是什么、是否允许小幅超预算。"
        "字段名必须保持英文，字段值按目标语言输出。"
        f"Use this schema shape: {json.dumps(BRIEF_OUTPUT_SCHEMA, ensure_ascii=False)}"
    )
    return RolePromptSpec(version=BRIEF_PARSER_PROMPT_VERSION, system_prompt=system_prompt)

