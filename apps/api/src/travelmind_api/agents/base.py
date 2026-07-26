from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from pydantic import BaseModel, Field

from travelmind_api.services.maps.base import GeoPoint, TravelMode
from travelmind_api.services.search_connector import SearchServiceConfig


class PlanningRequest(BaseModel):
    trip_id: str
    user_id: str | None = None
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
    xhs_source_enabled: bool = False
    search_service: SearchServiceConfig | None = None
    locale: str | None = None


class BudgetBreakdown(BaseModel):
    tickets: float = 0.0
    dining: float = 0.0
    accommodation: float = 0.0
    transport: float = 0.0
    other: float = 0.0
    total: float = 0.0


class BudgetLineItem(BaseModel):
    key: str
    title: str
    category: str
    amount: float
    day_index: int | None = None
    note: str | None = None


class BudgetSummary(BaseModel):
    requested_budget: float
    estimated_total: float
    remaining_budget: float
    over_budget: float
    utilization_ratio: float
    status: str
    breakdown: BudgetBreakdown
    line_items: list[BudgetLineItem] = Field(default_factory=list)


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


class VisitRequirements(BaseModel):
    reservation_policy: str | None = None
    timed_entry: bool = False
    identity_required: bool = False
    advance_booking_note: str | None = None
    notes: list[str] = Field(default_factory=list)


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


class PlannedLocationReference(BaseModel):
    provider: str
    poi_id: str | None = None
    name: str
    city: str | None = None
    category: str | None = None
    summary: str | None = None
    address: str | None = None
    coordinates: GeoPoint | None = None


class PlannedRouteReference(BaseModel):
    provider: str
    mode: TravelMode
    origin_poi_id: str | None = None
    destination_poi_id: str | None = None
    origin_name: str
    destination_name: str
    distance_meters: int
    duration_minutes: int
    summary: str


class PlannedItem(BaseModel):
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
    location_ref: PlannedLocationReference | None = None
    route_from_previous: PlannedRouteReference | None = None
    image_urls: list[str] = Field(default_factory=list)
    image_source_urls: list[str] = Field(default_factory=list)
    image_status: str | None = None
    image_priority_tier: str | None = None
    image_priority_reason: str | None = None
    image_failure_reason: str | None = None


class PlannedDayWeather(BaseModel):
    summary: str
    notes: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class PlannedDay(BaseModel):
    day_index: int
    title: str
    summary: str
    total_cost: float
    items: list[PlannedItem]
    weather: PlannedDayWeather | None = None
    budget_breakdown: BudgetBreakdown | None = None


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


class AgentTrace(BaseModel):
    provider: str
    workflow_id: str
    notes: list[str]
    license_notice: str | None = None
    agent_runs: list[AgentRunStep] = Field(default_factory=list)
    grounding_documents: list[dict[str, Any]] = Field(default_factory=list)
    transport_guidance: dict[str, Any] | None = None


class PlanningResult(BaseModel):
    summary: str
    total_budget_estimate: float
    days: list[PlannedDay]
    risks: list[str]
    trace: AgentTrace
    budget_summary: BudgetSummary | None = None
    transport_booking_summary: TransportBookingSummary | None = None
    stay_recommendation: StayRecommendation | None = None


class SourceSummary(BaseModel):
    summary: str
    bullets: list[str]


class ExportDraft(BaseModel):
    title: str
    subtitle: str
    sections: list[str]


class AgentOrchestrator(Protocol):
    def plan_trip(self, request: PlanningRequest) -> PlanningResult:
        ...

    def refine_trip(
        self,
        request: PlanningRequest,
        current_plan: PlanningResult,
        *,
        instruction: str,
        scope: str,
        day_index: int | None,
    ) -> PlanningResult:
        ...

    def summarize_sources(self, destination: str, findings: list[str]) -> SourceSummary:
        ...

    def draft_export_payload(self, request: PlanningRequest, plan: PlanningResult) -> ExportDraft:
        ...
