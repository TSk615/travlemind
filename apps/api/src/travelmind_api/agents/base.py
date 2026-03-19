from __future__ import annotations

from datetime import date
from typing import Protocol

from pydantic import BaseModel

from travelmind_api.services.maps.base import GeoPoint, TravelMode


class PlanningRequest(BaseModel):
    trip_id: str
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
    location_ref: PlannedLocationReference | None = None
    route_from_previous: PlannedRouteReference | None = None


class PlannedDay(BaseModel):
    day_index: int
    title: str
    summary: str
    total_cost: float
    items: list[PlannedItem]


class AgentTrace(BaseModel):
    provider: str
    workflow_id: str
    notes: list[str]
    license_notice: str | None = None


class PlanningResult(BaseModel):
    summary: str
    total_budget_estimate: float
    days: list[PlannedDay]
    risks: list[str]
    trace: AgentTrace


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

    def summarize_sources(self, destination: str, findings: list[str]) -> SourceSummary:
        ...

    def draft_export_payload(self, request: PlanningRequest, plan: PlanningResult) -> ExportDraft:
        ...