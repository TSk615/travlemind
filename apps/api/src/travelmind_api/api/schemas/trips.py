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


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "required"}:
        return True
    if normalized in {"0", "false", "no", "n", "not_required"}:
        return False
    return default


class BudgetBreakdown(BaseModel):
    tickets: float = 0.0
    dining: float = 0.0
    accommodation: float = 0.0
    transport: float = 0.0
    other: float = 0.0
    total: float = 0.0

    @field_validator("tickets", "dining", "accommodation", "transport", "other", "total", mode="before")
    @classmethod
    def _normalize_amount(cls, value: Any) -> float:
        return _coerce_float(value, default=0.0)


class BudgetLineItem(BaseModel):
    key: str
    title: str
    category: str
    amount: float
    day_index: int | None = None
    note: str | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _normalize_amount(cls, value: Any) -> float:
        return _coerce_float(value, default=0.0)


class BudgetSummary(BaseModel):
    requested_budget: float
    estimated_total: float
    remaining_budget: float
    over_budget: float
    utilization_ratio: float
    status: str
    breakdown: BudgetBreakdown
    line_items: list[BudgetLineItem] = Field(default_factory=list)

    @field_validator("requested_budget", "estimated_total", "remaining_budget", "over_budget", "utilization_ratio", mode="before")
    @classmethod
    def _normalize_amount(cls, value: Any) -> float:
        return _coerce_float(value, default=0.0)


class BookingInfo(BaseModel):
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
    def _normalize_estimated_price(cls, value: Any) -> float | None:
        if value in {None, ""}:
            return None
        return _coerce_float(value, default=0.0)

    @field_validator("booking_required", "reservation_required", "schedule_verified", mode="before")
    @classmethod
    def _normalize_bool(cls, value: Any) -> bool:
        return _coerce_bool(value, default=False)


class VisitRequirements(BaseModel):
    reservation_policy: str | None = None
    timed_entry: bool = False
    identity_required: bool = False
    advance_booking_note: str | None = None
    notes: list[str] = Field(default_factory=list)

    @field_validator("timed_entry", "identity_required", mode="before")
    @classmethod
    def _normalize_bool(cls, value: Any) -> bool:
        return _coerce_bool(value, default=False)


class TransportBookingSummary(BaseModel):
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
    def _normalize_amount(cls, value: Any) -> float:
        return _coerce_float(value, default=0.0)

    @field_validator("booking_required", mode="before")
    @classmethod
    def _normalize_bool(cls, value: Any) -> bool:
        return _coerce_bool(value, default=False)


class StayHotelCandidate(BaseModel):
    name: str
    area: str | None = None
    hotel_type: str | None = None
    reason: str | None = None
    price_hint: str | None = None
    price_checked_at: str | None = None
    price_valid_for: str | None = None
    review_score: str | None = None
    review_count: str | None = None
    review_summary: str | None = None
    preference_match: str | None = None
    booking_confidence: str | None = None
    caveats: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)


class StayRecommendation(BaseModel):
    recommended_areas: list[str] = Field(default_factory=list)
    final_recommended_hotel: StayHotelCandidate | None = None
    hotel_candidates: list[StayHotelCandidate] = Field(default_factory=list)
    stay_strategy: list[str] = Field(default_factory=list)
    budget_notes: list[str] = Field(default_factory=list)
    price_timeliness_notes: list[str] = Field(default_factory=list)
    review_notes: list[str] = Field(default_factory=list)
    preference_match_notes: list[str] = Field(default_factory=list)
    hotel_risks: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)


class ItineraryItem(BaseModel):
    id: str
    type: str
    name: str
    start_time: str
    end_time: str
    location: str
    score: float
    note: str
    booking_info: BookingInfo | None = None
    visit_requirements: VisitRequirements | None = None
    image_urls: list[str] = Field(default_factory=list)
    image_source_urls: list[str] = Field(default_factory=list)
    image_status: str | None = None
    image_priority_tier: str | None = None
    image_priority_reason: str | None = None
    image_failure_reason: str | None = None

    @field_validator("score", mode="before")
    @classmethod
    def _normalize_score(cls, value: Any) -> float:
        return _coerce_float(value, default=0.8)


class ItineraryDayWeather(BaseModel):
    summary: str
    notes: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class ItineraryDay(BaseModel):
    day_index: int
    title: str
    summary: str
    total_cost: float
    items: list[ItineraryItem]
    weather: ItineraryDayWeather | None = None
    budget_breakdown: BudgetBreakdown | None = None

    @field_validator("total_cost", mode="before")
    @classmethod
    def _normalize_total_cost(cls, value: Any) -> float:
        return _coerce_float(value, default=0.0)


class AgentRunStep(BaseModel):
    key: str
    title: str
    description: str
    prompt_focus: str | None = None
    output_summary: str | None = None
    prompt_version: str | None = None
    status: str = "completed"
    model: str | None = None
    notes: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class AgentRunTrace(BaseModel):
    provider: str
    workflow_id: str
    notes: list[str]
    license_notice: str | None = None
    agent_runs: list[AgentRunStep] = Field(default_factory=list)
    grounding_documents: list[dict[str, Any]] = Field(default_factory=list)
    transport_guidance: dict[str, Any] | None = None


class GeneratedItinerary(BaseModel):
    summary: str
    total_budget_estimate: float
    days: list[ItineraryDay]
    risks: list[str]
    budget_summary: BudgetSummary | None = None
    transport_booking_summary: TransportBookingSummary | None = None
    stay_recommendation: StayRecommendation | None = None

    @field_validator("total_budget_estimate", mode="before")
    @classmethod
    def _normalize_total_budget_estimate(cls, value: Any) -> float:
        return _coerce_float(value, default=0.0)


class TripCreateRequest(BaseModel):
    title: str = Field(default="", max_length=255)
    origin: str = Field(min_length=2, max_length=255)
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
    origin: str | None = None
    destination: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    budget: float | None = Field(default=None, gt=0)
    travelers: int | None = Field(default=None, ge=1, le=12)
    interests: list[str] | None = None
    accommodation_preference: str | None = None
    pace: str | None = None
    transport_mode: str | None = None




class TripIntakeChatMessage(BaseModel):
    role: str = Field(pattern=r"^(assistant|user)$")
    text: str = Field(default="")


class TripIntakeDraft(BaseModel):
    title: str = Field(default="")
    origin: str = Field(default="")
    destination: str = Field(default="")
    start_date: str = Field(default="")
    end_date: str = Field(default="")
    budget: float = 0.0
    travelers: int = 0
    interests: list[str] = Field(default_factory=list)
    accommodation_preference: str = Field(default="")
    pace: str = Field(default="")
    transport_mode: str = Field(default="")


class TripIntakeChatRequest(BaseModel):
    draft: TripIntakeDraft = Field(default_factory=TripIntakeDraft)
    messages: list[TripIntakeChatMessage] = Field(default_factory=list)
    user_message: str | None = Field(default=None, max_length=2000)


class TripIntakeChatResponse(BaseModel):
    assistant_message: str
    draft: TripIntakeDraft
    missing_required_fields: list[str] = Field(default_factory=list)
    ready_to_create: bool = False

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
    latest_agent_trace: dict[str, Any] | None = None


class CommunityTripPublicationState(BaseModel):
    post_id: str
    published_at: datetime
    updated_at: datetime
    source_trip_updated_at: datetime
    is_stale: bool


class TripResponse(BaseModel):
    id: str
    user_id: str
    title: str
    origin: str
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
    community_post: CommunityTripPublicationState | None = None
