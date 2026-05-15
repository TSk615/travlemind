from __future__ import annotations

import json
from typing import Any

TRIP_INTAKE_PROMPT_VERSION = "trip_intake.v2"


# 中文注释：这是对话式 intake 的输出结构。
INTAKE_OUTPUT_SCHEMA: dict[str, Any] = {
    "assistant_message": "Please tell me your destination.",
    "draft": {
        "title": "",
        "origin": "",
        "destination": "",
        "start_date": "",
        "end_date": "",
        "budget": 0,
        "travelers": 0,
        "interests": [],
        "accommodation_preference": "",
        "pace": "",
        "transport_mode": "",
    },
}


# 中文注释：这是在用户还没开始输入时，系统主动给出的第一句引导。
def build_trip_intake_initial_prompt(locale: str, missing_fields: list[str]) -> str:
    if locale == "zh-CN":
        if missing_fields:
            field = missing_fields[0]
            return f"我们先补充 {field}。请直接告诉我相关信息。"
        return "信息已经齐了。你可以继续补充细节，或者直接创建行程。"
    if missing_fields:
        return f"Let's start with {missing_fields[0]}. Tell me the relevant detail directly."
    return "The brief is complete. You can add more details or create the trip now."


# 中文注释：
# - 角色：Trip Intake Assistant
# - 目标：通过对话不断更新完整 draft。
# - 输出：只能返回 JSON，不允许自由文本。
# - 约束：pace / transport_mode 必须收敛到允许枚举，interest 要归一化成短语列表。
def build_trip_intake_system_prompt() -> str:
    return (
        "You are TravelMind Trip Intake Assistant. Your job is to collect a structured trip brief through conversation. "
        "Return one valid JSON object only. No markdown, no prose outside JSON. "
        "Update the full draft based on the latest user message and the existing draft. "
        "If title is still empty and origin/destination are available, generate a practical title. "
        "Keep pace limited to slow, balanced, or packed. Keep transport_mode limited to rail, car, walking, or mixed. "
        "Normalize interests into a list of short phrases. "
        f"Use this output schema shape: {json.dumps(INTAKE_OUTPUT_SCHEMA, ensure_ascii=True)}"
    )