from __future__ import annotations

import json
import logging
from typing import Any, TypeVar

from pydantic import BaseModel, Field, ValidationError, field_validator


_LOGGER = logging.getLogger(__name__)
ModelT = TypeVar("ModelT", bound=BaseModel)


class PlanningBrief(BaseModel):
    destination: str = Field(min_length=1)
    trip_days: int = Field(ge=1)
    budget_band: str = Field(default="")
    budget_is_hard_constraint: bool = True
    budget_priority: str = Field(default="")
    allow_budget_flex: bool = False
    pace: str = Field(default="")
    must_have: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    transport: str = Field(default="")
    accommodation: str = Field(default="")
    interests: list[str] = Field(default_factory=list)
    planning_constraints: list[str] = Field(default_factory=list)

    @field_validator("budget_is_hard_constraint", "allow_budget_flex", mode="before")
    @classmethod
    def _coerce_bool(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        normalized = str(value or "").strip().lower()
        if normalized in {"1", "true", "yes", "y", "required"}:
            return True
        if normalized in {"0", "false", "no", "n", "not_required"}:
            return False
        return False


# Compatibility name for callers that still import the old implementation's
# schema. New workflow code uses the framework-neutral name above.
HelloAgentsBrief = PlanningBrief


def extract_json_payloads(content: str) -> list[dict[str, Any]]:
    candidate = str(content).strip()
    if not candidate:
        raise ValueError("Role response was empty")

    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()

    decoder = json.JSONDecoder()
    payloads: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(candidate):
        start = candidate.find("{", cursor)
        if start == -1:
            break
        try:
            payload, end = decoder.raw_decode(candidate[start:])
        except json.JSONDecodeError:
            cursor = start + 1
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
        cursor = start + end

    if not payloads:
        raise ValueError("Role response did not contain a valid JSON object")
    return payloads


def parse_structured_response(content: str, model_cls: type[ModelT]) -> ModelT:
    valid_payloads: list[ModelT] = []
    validation_errors: list[str] = []
    for payload in extract_json_payloads(content):
        try:
            valid_payloads.append(model_cls.model_validate(payload))
        except ValidationError as exc:
            validation_errors.append(str(exc))

    if not valid_payloads:
        detail = validation_errors[-1] if validation_errors else "no valid JSON object"
        raise ValueError(detail)

    if len(valid_payloads) > 1:
        signatures = {
            json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            for item in valid_payloads
        }
        qualifier = "conflicting" if len(signatures) > 1 else "duplicate"
        _LOGGER.warning(
            "Role response contained %d %s valid JSON objects for %s; using the last object.",
            len(valid_payloads),
            qualifier,
            model_cls.__name__,
        )
    return valid_payloads[-1]

