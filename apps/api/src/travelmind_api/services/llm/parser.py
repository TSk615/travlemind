from __future__ import annotations
from travelmind_api.services.planning_details import BookingDetails, TransportLeg, TransportServiceCandidate, HotelEvidence, BudgetCompleteness

import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

_TIME_VALUE_RE = re.compile(r"^\s*(\d{1,2})\s*[:\uff1a]\s*(\d{1,2})\s*$")
_DURATION_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|~|\u2013|\u2014|\u81f3|\u5230)\s*(\d+(?:\.\d+)?)")
_DURATION_VALUE_RE = re.compile(r"(\d+(?:\.\d+)?)")
_DAY_START_MINUTES = 9 * 60
_DEFAULT_ITEM_DURATION_MINUTES = 90
_MIN_ITEM_DURATION_MINUTES = 30
_MAX_ITEM_DURATION_MINUTES = 6 * 60
_ITEM_GAP_MINUTES = 30
_LAST_MINUTE_OF_DAY = 23 * 60 + 59
_LATEST_FALLBACK_START_MINUTES = 22 * 60
_TIME_HINTS: tuple[tuple[tuple[str, ...], int], ...] = (
    (("check-in", "check in", "\u5165\u4f4f"), 15 * 60),
    (("check-out", "check out", "\u79bb\u5e97", "\u9000\u623f"), 11 * 60),
    (("\u665a\u4e0a", "\u591c", "night", "evening"), 19 * 60),
    (("\u508d\u665a", "\u9ec4\u660f", "dusk"), 17 * 60 + 30),
    (("\u4e0b\u5348", "afternoon"), 14 * 60),
    (("\u4e2d\u5348", "\u5348\u9910", "noon", "lunch"), 12 * 60),
    (("\u4e0a\u5348", "\u65e9\u4e0a", "\u65e9\u6668", "\u6e05\u6668", "morning", "breakfast"), 9 * 60),
)


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().casefold()
    if normalized in {"1", "true", "yes", "y", "required", "needed", "need", "must", "timed", "advance"}:
        return True
    if normalized in {
        "",
        "0",
        "false",
        "no",
        "n",
        "not_required",
        "not required",
        "not_needed",
        "not needed",
        "none",
        "null",
        "unknown",
        "unsure",
        "unclear",
        "n/a",
        "na",
    }:
        return False
    return default


class LlmPlanItem(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    start_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    end_day_offset: int = Field(default=0, ge=0, le=7)
    end_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    location: str = Field(default="")
    score: float = 0.8
    note: str = Field(default="")
    booking_info: "LlmBookingInfo | None" = None
    visit_requirements: "LlmVisitRequirements | None" = None

    @model_validator(mode="before")
    @classmethod
    def infer_overnight_transport_offset(cls, value: Any):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        if int(value.get("end_day_offset") or 0) > 0:
            return value
        item_type = str(value.get("type") or "").strip().casefold()
        if item_type not in {"transport", "transit", "rail", "flight", "ferry"}:
            return value
        try:
            start = int(str(value.get("start_time")).split(":")[0]) * 60 + int(str(value.get("start_time")).split(":")[1])
            end = int(str(value.get("end_time")).split(":")[0]) * 60 + int(str(value.get("end_time")).split(":")[1])
        except (AttributeError, IndexError, TypeError, ValueError):
            return value
        booking = value.get("booking_info") if isinstance(value.get("booking_info"), dict) else {}
        duration = booking.get("duration_minutes_min")
        try:
            duration = int(float(duration)) if duration is not None else 0
        except (TypeError, ValueError):
            duration = 0
        name = str(value.get("name") or "").casefold()
        if end <= start and (duration >= 300 or any(token in name for token in ("跨夜", "次日", "overnight", "高铁", "航班"))):
            value["end_day_offset"] = 1
        return value

    @field_validator("score", mode="before")
    @classmethod
    def clamp_score(cls, value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 0.8
        return max(0.0, min(1.0, numeric))


class LlmBookingInfo(BookingDetails):
    price_label: str | None = None
    estimated_price: float | None = None
    booking_required: bool = False
    reservation_required: bool = False
    official_booking_url: str | None = None
    booking_window: str | None = None
    reminder: str | None = None
    notes: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    schedule_verified: bool = False
    service_number: str | None = None
    schedule_checked_at: str | None = None
    schedule_source_url: str | None = None

    @field_validator("estimated_price", mode="before")
    @classmethod
    def normalize_estimated_price(cls, value: Any) -> float | None:
        if value in {None, ""}:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @field_validator("booking_required", "reservation_required", "schedule_verified", mode="before")
    @classmethod
    def normalize_bool(cls, value: Any) -> bool:
        return _coerce_bool(value, default=False)


class LlmVisitRequirements(BaseModel):
    reservation_policy: str | None = None
    timed_entry: bool = False
    identity_required: bool = False
    advance_booking_note: str | None = None
    notes: list[str] = Field(default_factory=list)

    @field_validator("timed_entry", "identity_required", mode="before")
    @classmethod
    def normalize_bool(cls, value: Any) -> bool:
        return _coerce_bool(value, default=False)


class LlmTransportBookingSummary(BaseModel):
    legs: list[TransportLeg] = Field(default_factory=list)
    service_candidates: list[TransportServiceCandidate] = Field(default_factory=list)
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

    @field_validator("booking_required", mode="before")
    @classmethod
    def normalize_bool(cls, value: Any) -> bool:
        return _coerce_bool(value, default=False)


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
    raw_payload = _normalize_planning_payload_times(raw_payload)
    try:
        return LlmPlanningPayload.model_validate(raw_payload)
    except ValidationError as exc:
        from travelmind_api.services.planner_schema_diagnostics import schema_validation_issues
        error = PlanningResponseValidationError("Planner JSON did not match the required itinerary schema")
        error.issues = schema_validation_issues(exc)
        raise error from None


def _normalize_planning_payload_times(payload: dict[str, Any]) -> dict[str, Any]:
    days = payload.get("days")
    if not isinstance(days, list):
        return payload

    for day in days:
        if not isinstance(day, dict):
            continue
        _normalize_day_item_times(day.get("items"))
    return payload


def _normalize_day_item_times(items: Any) -> None:
    if not isinstance(items, list):
        return

    cursor = _DAY_START_MINUTES
    for item in items:
        if not isinstance(item, dict):
            continue

        raw_start = item.get("start_time")
        raw_end = item.get("end_time")
        start = _parse_time_minutes(raw_start)
        end = _parse_time_minutes(raw_end)
        start_is_explicit = _parse_explicit_time_minutes(raw_start) is not None
        end_is_explicit = _parse_explicit_time_minutes(raw_end) is not None

        # Explicit clocks must survive parsing, including cross-day intervals.
        if start_is_explicit and end_is_explicit:
            item["start_time"] = _format_time_minutes(start)
            item["end_time"] = _format_time_minutes(end)
            cursor = min(end + _ITEM_GAP_MINUTES, _LATEST_FALLBACK_START_MINUTES)
            continue

        if start is None:
            start = cursor
        elif not start_is_explicit and start < cursor:
            start = cursor

        if end is None:
            end = start + (_parse_duration_minutes(raw_end) or _DEFAULT_ITEM_DURATION_MINUTES)
        elif end <= start:
            end = start + (_parse_duration_minutes(raw_end) or _MIN_ITEM_DURATION_MINUTES)
        elif not end_is_explicit and end < cursor:
            end = start + (_parse_duration_minutes(raw_end) or _DEFAULT_ITEM_DURATION_MINUTES)

        start, end = _fit_time_window(start, end)
        item["start_time"] = _format_time_minutes(start)
        item["end_time"] = _format_time_minutes(end)
        if _should_preserve_original_timing(raw_start) or _should_preserve_original_timing(raw_end):
            _append_original_timing_note(item, raw_start, raw_end)

        cursor = min(end + _ITEM_GAP_MINUTES, _LATEST_FALLBACK_START_MINUTES)


def _parse_time_minutes(value: Any) -> int | None:
    explicit = _parse_explicit_time_minutes(value)
    if explicit is not None:
        return explicit
    if _is_empty_value(value):
        return None

    text = str(value).strip().casefold()
    if not text:
        return None
    for keywords, minutes in _TIME_HINTS:
        if any(keyword in text for keyword in keywords):
            return minutes
    return None


def _parse_explicit_time_minutes(value: Any) -> int | None:
    if _is_empty_value(value):
        return None
    match = _TIME_VALUE_RE.match(str(value))
    if match is None:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def _parse_duration_minutes(value: Any) -> int | None:
    if _is_empty_value(value):
        return None

    text = str(value).strip().casefold()
    if not text:
        return None

    has_duration_unit = any(marker in text for marker in ("min", "minute", "hour", "\u5206", "\u5c0f\u65f6"))
    range_match = _DURATION_RANGE_RE.search(text)
    if range_match is not None:
        amount = max(float(range_match.group(1)), float(range_match.group(2)))
    elif has_duration_unit:
        value_match = _DURATION_VALUE_RE.search(text)
        if value_match is None:
            return None
        amount = float(value_match.group(1))
    else:
        return None

    multiplier = 60 if any(marker in text for marker in ("hour", "\u5c0f\u65f6")) else 1
    minutes = int(round(amount * multiplier))
    return max(_MIN_ITEM_DURATION_MINUTES, min(_MAX_ITEM_DURATION_MINUTES, minutes))


def _fit_time_window(start: int, end: int) -> tuple[int, int]:
    start = max(0, min(_LAST_MINUTE_OF_DAY, int(start)))
    end = max(0, min(_LAST_MINUTE_OF_DAY, int(end)))
    if end > start:
        return start, end

    if start >= _LAST_MINUTE_OF_DAY:
        start = _LAST_MINUTE_OF_DAY - _MIN_ITEM_DURATION_MINUTES
    end = min(_LAST_MINUTE_OF_DAY, start + _MIN_ITEM_DURATION_MINUTES)
    if end <= start:
        start = max(0, end - _MIN_ITEM_DURATION_MINUTES)
    return start, end


def _format_time_minutes(minutes: int) -> str:
    minutes = max(0, min(_LAST_MINUTE_OF_DAY, int(minutes)))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _should_preserve_original_timing(value: Any) -> bool:
    if _is_empty_value(value):
        return False
    text = str(value).strip()
    return bool(text) and _parse_explicit_time_minutes(text) is None


def _is_empty_value(value: Any) -> bool:
    return value is None or value == ""


def _append_original_timing_note(item: dict[str, Any], raw_start: Any, raw_end: Any) -> None:
    hints = []
    if _should_preserve_original_timing(raw_start):
        hints.append(f"start_time={raw_start}")
    if _should_preserve_original_timing(raw_end):
        hints.append(f"end_time={raw_end}")
    if not hints:
        return

    note = item.get("note")
    note_text = note.strip() if isinstance(note, str) else str(note).strip() if note is not None else ""
    timing_note = f"Original timing hint: {'; '.join(hints)}."
    if timing_note not in note_text:
        item["note"] = f"{note_text} {timing_note}".strip()


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
