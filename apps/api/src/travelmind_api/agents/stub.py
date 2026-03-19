from __future__ import annotations

from datetime import timedelta

from travelmind_api.agents.base import (
    AgentTrace,
    ExportDraft,
    PlannedDay,
    PlannedItem,
    PlannedLocationReference,
    PlannedRouteReference,
    PlanningRequest,
    PlanningResult,
    SourceSummary,
)
from travelmind_api.core.security import generate_identifier, generate_workflow_id
from travelmind_api.services.maps import MapsPoiProvider, PoiDetail, PoiSearchResult, TravelMode, build_maps_provider, poi_to_route_stop


class StubOrchestrator:
    def __init__(self, maps_provider: MapsPoiProvider | None = None) -> None:
        self._maps_provider = maps_provider or build_maps_provider("stub")

    def plan_trip(self, request: PlanningRequest) -> PlanningResult:
        # This deterministic planner keeps tests and local development stable
        # while the external agent provider remains an optional PoC adapter.
        total_days = max(1, (request.end_date - request.start_date).days + 1)
        budget_per_day = round(request.budget / total_days, 2)
        interests = request.interests or ["local highlights", "food", "slow walks"]
        route_mode = self._resolve_route_mode(request.transport_mode)
        days: list[PlannedDay] = []
        total_pois = 0

        for offset in range(total_days):
            current_date = request.start_date + timedelta(days=offset)
            focus = interests[offset % len(interests)]
            morning_poi = self._pick_poi(query=focus, city=request.destination, preferred_index=offset)
            lunch_poi = self._pick_poi(query="food", city=request.destination, preferred_index=offset + 1)
            afternoon_poi = self._pick_poi(query=f"{focus} {request.transport_mode}", city=request.destination, preferred_index=offset + 2)
            poi_details = [self._ensure_detail(poi) for poi in [morning_poi, lunch_poi, afternoon_poi]]
            total_pois += len(poi_details)

            route_stops = [poi_to_route_stop(poi) for poi in poi_details]
            route_matrix = self._maps_provider.batch_route_matrix(route_stops, mode=route_mode)
            matrix_lookup = {
                (cell.origin_stop_id, cell.destination_stop_id): cell
                for cell in route_matrix.cells
            }

            items: list[PlannedItem] = []
            previous_stop = None
            inter_stop_minutes = 0
            slot_definitions = [
                ("sight", f"Morning {focus}", "09:00", "11:30", "Low-friction start with a walkable anchor."),
                ("meal", "Lunch near transit", "12:00", "13:30", "Keeps transfer costs predictable."),
                ("explore", f"Afternoon {request.transport_mode} loop", "14:00", "18:00", "Balances pace with one strong visual moment."),
            ]

            for item_index, (slot_type, fallback_name, start_time, end_time, base_note) in enumerate(slot_definitions):
                poi = poi_details[item_index]
                current_stop = route_stops[item_index]
                route_ref = None
                note = base_note
                if previous_stop is not None:
                    route_estimate = self._maps_provider.estimate_route(previous_stop, current_stop, route_mode)
                    matrix_cell = matrix_lookup[(previous_stop.stop_id, current_stop.stop_id)]
                    inter_stop_minutes += matrix_cell.duration_minutes
                    route_ref = PlannedRouteReference(
                        provider=route_estimate.provider,
                        mode=route_estimate.mode,
                        origin_poi_id=route_estimate.origin.poi_id,
                        destination_poi_id=route_estimate.destination.poi_id,
                        origin_name=route_estimate.origin.name,
                        destination_name=route_estimate.destination.name,
                        distance_meters=matrix_cell.distance_meters,
                        duration_minutes=matrix_cell.duration_minutes,
                        summary=route_estimate.summary,
                    )
                    note = f"{base_note} Route from previous stop is about {matrix_cell.duration_minutes} min."

                items.append(
                    PlannedItem(
                        id=generate_identifier("item"),
                        type=slot_type,
                        name=poi.name or fallback_name,
                        start_time=start_time,
                        end_time=end_time,
                        location=poi.location.address.formatted,
                        score=round(max(0.72, min(0.94, 0.76 + (poi.relevance_score / 20.0))), 2),
                        note=note,
                        location_ref=PlannedLocationReference(
                            provider=poi.provider,
                            poi_id=poi.id,
                            name=poi.name,
                            city=poi.city,
                            category=poi.category,
                            summary=poi.summary,
                            address=poi.location.address.formatted,
                            coordinates=poi.location.coordinates,
                        ),
                        route_from_previous=route_ref,
                    )
                )
                previous_stop = current_stop

            day_summary = f"A {request.pace} day centered on {focus} in {request.destination}."
            if inter_stop_minutes:
                day_summary += f" Estimated inter-stop travel: {inter_stop_minutes} min by {route_mode}."

            days.append(
                PlannedDay(
                    day_index=offset + 1,
                    title=f"{current_date.isoformat()} | {focus.title()}",
                    summary=day_summary,
                    total_cost=budget_per_day,
                    items=items,
                )
            )

        risks = []
        if request.pace == "packed":
            risks.append("Packed pace increases fatigue and transfer risk.")
        if request.budget / total_days < 500:
            risks.append("Budget may be tight once transport and accommodation are finalized.")

        return PlanningResult(
            summary=f"{request.destination} trip with {total_days} day(s), tuned for {request.pace} pacing and {request.travelers} traveler(s).",
            total_budget_estimate=request.budget,
            days=days,
            risks=risks,
            trace=AgentTrace(
                provider="stub",
                workflow_id=generate_workflow_id(),
                notes=[
                    "Generated a deterministic MVP itinerary.",
                    "Kept the output compatible with later orchestrator swaps.",
                    f"Attached structured POI and route references via {self._maps_provider.provider_name}.",
                    f"Resolved {total_pois} POI references across the trip.",
                ],
            ),
        )

    def summarize_sources(self, destination: str, findings: list[str]) -> SourceSummary:
        return SourceSummary(
            summary=f"Collected grounded signals for {destination} from official and user-supplied sources.",
            bullets=findings[:5],
        )

    def draft_export_payload(self, request: PlanningRequest, plan: PlanningResult) -> ExportDraft:
        lines = [
            f"Destination: {request.destination}",
            f"Dates: {request.start_date.isoformat()} to {request.end_date.isoformat()}",
            f"Budget: {request.budget}",
            f"Travelers: {request.travelers}",
            f"Summary: {plan.summary}",
        ]
        for day in plan.days:
            lines.append(f"Day {day.day_index}: {day.title} | {day.summary}")
            for item in day.items:
                route_suffix = ""
                if item.route_from_previous is not None:
                    route_suffix = f" | transfer {item.route_from_previous.duration_minutes} min"
                lines.append(f"- {item.start_time}-{item.end_time}: {item.name} @ {item.location}{route_suffix}")
        return ExportDraft(
            title=request.title,
            subtitle=f"{request.destination} planning packet",
            sections=lines,
        )

    def _pick_poi(self, query: str, city: str, preferred_index: int) -> PoiSearchResult:
        results = self._maps_provider.search_pois(query, city)
        if not results:
            results = self._maps_provider.search_pois("local highlights", city)
        return results[preferred_index % len(results)]

    def _ensure_detail(self, poi: PoiSearchResult) -> PoiDetail:
        detail = self._maps_provider.get_poi_detail(poi.id)
        if detail is not None:
            return detail
        return PoiDetail(
            id=poi.id,
            provider=poi.provider,
            name=poi.name,
            city=poi.city,
            category=poi.category,
            summary=poi.summary,
            tags=list(poi.tags),
            location=poi.location,
            relevance_score=poi.relevance_score,
        )

    def _resolve_route_mode(self, transport_mode: str) -> TravelMode:
        normalized = (transport_mode or "mixed").strip().lower()
        mapping = {
            "walk": "walking",
            "walking": "walking",
            "rail": "transit",
            "train": "transit",
            "subway": "transit",
            "bus": "transit",
            "car": "driving",
            "drive": "driving",
            "cycling": "cycling",
            "bike": "cycling",
            "mixed": "mixed",
        }
        return mapping.get(normalized, "mixed")