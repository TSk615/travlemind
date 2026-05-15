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
    booking_info: "LlmBookingInfo | None" = None
    visit_requirements: "LlmVisitRequirements | None" = None

    @field_validator("score", mode="before")
    @classmethod
    def clamp_score(cls, value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 0.8
        return max(0.0, min(1.0, numeric))


class LlmBookingInfo(BaseModel):
    price_label: str | None = None
    estimated_price: float | None = None
    booking_required: bool = False
    reservation_required: bool = False
    official_booking_url: str | None = None
    booking_window: str | None = None
    reminder: str | None = None
    notes: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)

    @field_validator("estimated_price", mode="before")
    @classmethod
    def normalize_estimated_price(cls, value: Any) -> float | None:
        if value in {None, ""}:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


class LlmVisitRequirements(BaseModel):
    reservation_policy: str | None = None
    timed_entry: bool = False
    identity_required: bool = False
    advance_booking_note: str | None = None
    notes: list[str] = Field(default_factory=list)


class LlmTransportBookingSummary(BaseModel):
    summary: str | None = None
    recommended_option: str | None = None
    estimated_intercity_cost: float = 0.0
    estimated_local_transport_cost: float = 0.0
    booking_required: bool = False
    official_booking_url: str | None = None
    booking_window: str | None = None
    pass_or_ticket_notes: list[str] = Field(default_factory=list)
    reminders: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)

    @field_validator("estimated_intercity_cost", "estimated_local_transport_cost", mode="before")
    @classmethod
    def normalize_estimated_cost(cls, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0


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
    transport_booking_summary: LlmTransportBookingSummary | None = None


LlmPlanItem.model_rebuild()


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
    return _unwrap_nested_itinerary_payload(payload)


def _unwrap_nested_itinerary_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if "summary" in payload and "days" in payload:
        return payload

    itinerary = payload.get("itinerary")
    if isinstance(itinerary, dict) and ("summary" in itinerary or "days" in itinerary):
        return itinerary

    nested_payload = payload.get("payload")
    if isinstance(nested_payload, dict):
        nested_itinerary = nested_payload.get("itinerary")
        if isinstance(nested_itinerary, dict) and ("summary" in nested_itinerary or "days" in nested_itinerary):
            return nested_itinerary

    return payload



def _strip_code_fences(content: str) -> str:
    lines = content.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()
