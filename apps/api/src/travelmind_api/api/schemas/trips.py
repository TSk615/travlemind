from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _coerce_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class ItineraryItem(BaseModel):
    id: str
    type: str
    name: str
    start_time: str
    end_time: str
    location: str
    score: float
    note: str

    @field_validator("score", mode="before")
    @classmethod
    def _normalize_score(cls, value: Any) -> float:
        return _coerce_float(value, default=0.8)


class ItineraryDay(BaseModel):
    day_index: int
    title: str
    summary: str
    total_cost: float
    items: list[ItineraryItem]

    @field_validator("total_cost", mode="before")
    @classmethod
    def _normalize_total_cost(cls, value: Any) -> float:
        return _coerce_float(value, default=0.0)


class AgentRunTrace(BaseModel):
    provider: str
    workflow_id: str
    notes: list[str]
    license_notice: str | None = None


class GeneratedItinerary(BaseModel):
    summary: str
    total_budget_estimate: float
    days: list[ItineraryDay]
    risks: list[str]

    @field_validator("total_budget_estimate", mode="before")
    @classmethod
    def _normalize_total_budget_estimate(cls, value: Any) -> float:
        return _coerce_float(value, default=0.0)


class TripCreateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    destination: str = Field(min_length=2, max_length=255)
    start_date: date
    end_date: date
    budget: float = Field(gt=0)
    travelers: int = Field(default=1, ge=1, le=12)
    interests: list[str] = Field(default_factory=list)
    accommodation_preference: str = Field(default="")
    pace: str = Field(default="balanced")
    transport_mode: str = Field(default="mixed")


class TripUpdateRequest(BaseModel):
    title: str | None = None
    destination: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    budget: float | None = Field(default=None, gt=0)
    travelers: int | None = Field(default=None, ge=1, le=12)
    interests: list[str] | None = None
    accommodation_preference: str | None = None
    pace: str | None = None
    transport_mode: str | None = None


class TripRefineRequest(BaseModel):
    instruction: str = Field(min_length=3, max_length=1000)
    scope: str = Field(min_length=2, max_length=64)
    day_index: int | None = Field(default=None, ge=1)

    @field_validator("instruction", "scope")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be empty")
        return normalized


class TripItinerarySaveRequest(BaseModel):
    itinerary: dict[str, Any]
    latest_agent_trace: dict[str, Any]


class TripResponse(BaseModel):
    id: str
    user_id: str
    title: str
    destination: str
    start_date: date
    end_date: date
    budget: float
    travelers: int
    interests: list[str]
    accommodation_preference: str
    pace: str
    transport_mode: str
    created_at: datetime
    updated_at: datetime
    itinerary: GeneratedItinerary | None = None
    latest_agent_trace: AgentRunTrace | None = None