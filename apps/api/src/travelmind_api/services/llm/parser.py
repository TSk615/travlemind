from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator


class LlmPlanItem(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    start_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    location: str = Field(default="")
    score: float = 0.8
    note: str = Field(default="")

    @field_validator("score", mode="before")
    @classmethod
    def clamp_score(cls, value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 0.8
        return max(0.0, min(1.0, numeric))


class LlmPlanDay(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    summary: str = Field(default="")
    total_cost: float = 0.0
    items: list[LlmPlanItem] = Field(min_length=1)


class LlmPlanningPayload(BaseModel):
    summary: str = Field(min_length=1)
    total_budget_estimate: float | None = None
    days: list[LlmPlanDay] = Field(min_length=1)
    risks: list[str] = Field(default_factory=list)


class PlanningResponseParseError(ValueError):
    pass


class PlanningResponseValidationError(ValueError):
    pass


def parse_planning_response(content: str) -> LlmPlanningPayload:
    raw_payload = _extract_json_payload(content)
    try:
        return LlmPlanningPayload.model_validate(raw_payload)
    except ValidationError as exc:
        raise PlanningResponseValidationError(str(exc)) from exc



def _extract_json_payload(content: str) -> dict[str, Any]:
    candidate = content.strip()
    if not candidate:
        raise PlanningResponseParseError("LLM response was empty")

    if candidate.startswith("```"):
        candidate = _strip_code_fences(candidate)

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise PlanningResponseParseError("LLM response did not contain a valid JSON object")
        try:
            payload = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise PlanningResponseParseError(str(exc)) from exc

    if not isinstance(payload, dict):
        raise PlanningResponseParseError("LLM response root must be a JSON object")
    return payload



def _strip_code_fences(content: str) -> str:
    lines = content.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()