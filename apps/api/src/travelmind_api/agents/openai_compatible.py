from __future__ import annotations

from urllib.parse import urlparse

from travelmind_api.agents.base import (
    AgentTrace,
    PlannedDay,
    PlannedItem,
    PlannedLocationReference,
    PlannedRouteReference,
    PlanningRequest,
    PlanningResult,
)
from travelmind_api.agents.stub import StubOrchestrator
from travelmind_api.core.security import generate_identifier, generate_workflow_id
from travelmind_api.services.llm.client import OpenAICompatibleClient
from travelmind_api.services.llm.config import LlmConfig
from travelmind_api.services.llm.parser import LlmPlanningPayload, parse_planning_response
from travelmind_api.services.llm.prompts import build_planning_messages
from travelmind_api.services.maps import MapsPoiProvider, PoiDetail, PoiSearchResult, poi_to_route_stop


class OpenAICompatibleOrchestrator(StubOrchestrator):
    def __init__(
        self,
        llm_config: LlmConfig,
        *,
        llm_client: OpenAICompatibleClient | None = None,
        maps_provider: MapsPoiProvider | None = None,
    ) -> None:
        super().__init__(maps_provider=maps_provider)
        self._llm_config = llm_config
        self._llm_client = llm_client or OpenAICompatibleClient(llm_config)

    def plan_trip(self, request: PlanningRequest) -> PlanningResult:
        try:
            messages = build_planning_messages(request)
            content = self._llm_client.create_chat_completion(messages=messages)
            payload = parse_planning_response(content)
            return self._build_result_from_payload(payload, request)
        except Exception as exc:
            fallback = super().plan_trip(request)
            reason = str(exc).strip() or exc.__class__.__name__
            fallback.trace.notes.append(f"OpenAI-compatible LLM fallback triggered: {reason}")
            fallback.trace.notes.append("Returned the deterministic stub itinerary after LLM generation failed.")
            return fallback

    def _build_result_from_payload(self, payload: LlmPlanningPayload, request: PlanningRequest) -> PlanningResult:
        expected_days = max(1, (request.end_date - request.start_date).days + 1)
        if len(payload.days) != expected_days:
            raise ValueError(f"Expected {expected_days} day entries but received {len(payload.days)}")

        route_mode = self._resolve_route_mode(request.transport_mode)
        planned_days: list[PlannedDay] = []

        for day_index, day in enumerate(payload.days, start=1):
            poi_details = [self._resolve_item_poi(item, request, preferred_index=day_index + item_index) for item_index, item in enumerate(day.items)]
            route_stops = [poi_to_route_stop(poi) for poi in poi_details]
            route_matrix = self._maps_provider.batch_route_matrix(route_stops, mode=route_mode) if route_stops else None
            matrix_lookup = {
                (cell.origin_stop_id, cell.destination_stop_id): cell
                for cell in (route_matrix.cells if route_matrix is not None else [])
            }

            planned_items: list[PlannedItem] = []
            previous_stop = None
            for item_index, item in enumerate(day.items):
                poi = poi_details[item_index]
                current_stop = route_stops[item_index]
                route_ref = None
                note = item.note.strip() or "Generated from the configured OpenAI-compatible itinerary draft."
                if previous_stop is not None:
                    route_estimate = self._maps_provider.estimate_route(previous_stop, current_stop, route_mode)
                    matrix_cell = matrix_lookup[(previous_stop.stop_id, current_stop.stop_id)]
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
                    note = f"{note} Transfer from previous stop is about {matrix_cell.duration_minutes} min."

                location_text = item.location.strip() or poi.location.address.formatted
                planned_items.append(
                    PlannedItem(
                        id=generate_identifier("item"),
                        type=item.type,
                        name=item.name,
                        start_time=item.start_time,
                        end_time=item.end_time,
                        location=location_text,
                        score=item.score,
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

            planned_days.append(
                PlannedDay(
                    day_index=day_index,
                    title=day.title,
                    summary=day.summary,
                    total_cost=day.total_cost,
                    items=planned_items,
                )
            )

        host = urlparse(self._llm_config.base_url).netloc or self._llm_config.base_url
        total_budget = payload.total_budget_estimate if payload.total_budget_estimate and payload.total_budget_estimate > 0 else request.budget
        return PlanningResult(
            summary=payload.summary,
            total_budget_estimate=total_budget,
            days=planned_days,
            risks=payload.risks,
            trace=AgentTrace(
                provider="openai-compatible",
                workflow_id=generate_workflow_id(),
                notes=[
                    f"Generated the itinerary with OpenAI-compatible model {self._llm_config.model}.",
                    f"Sent a {self._llm_config.wire_api} request to {host}.",
                    f"Refined the LLM draft with structured POI and route references via {self._maps_provider.provider_name}.",
                ],
            ),
        )

    def _resolve_item_poi(self, item: object, request: PlanningRequest, preferred_index: int) -> PoiDetail:
        item_name = getattr(item, "name", "")
        item_location = getattr(item, "location", "")
        item_type = getattr(item, "type", "local highlights")
        queries = [
            f"{item_name} {item_location}".strip(),
            str(item_name).strip(),
            str(item_location).strip(),
            str(item_type).strip(),
            "local highlights",
        ]
        seen: set[str] = set()
        for query in queries:
            if not query:
                continue
            key = query.casefold()
            if key in seen:
                continue
            seen.add(key)
            results = self._maps_provider.search_pois(query, request.destination)
            if results:
                return self._ensure_detail(results[preferred_index % len(results)])
        return self._ensure_detail(self._pick_poi(query="local highlights", city=request.destination, preferred_index=preferred_index))