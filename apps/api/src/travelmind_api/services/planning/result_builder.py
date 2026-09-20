"""Framework-neutral assembly of a validated planning payload into product models."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from travelmind_api.agents.base import (
    AgentRunStep,
    AgentTrace,
    PlannedDay,
    PlannedItem,
    PlannedLocationReference,
    PlannedRouteReference,
    PlanningRequest,
    PlanningResult,
)
from travelmind_api.core.security import generate_identifier, generate_workflow_id
from travelmind_api.services.budgeting import enrich_plan_with_budget
from travelmind_api.services.llm.localization import is_chinese_output
from travelmind_api.services.maps import poi_to_route_stop
from travelmind_api.services.planning.role_models import (
    HotelRecommendation,
    PoiGrounding,
    ResearchPoi,
    TransportGuidance,
    WeatherGuidance,
)
from travelmind_api.services.weather_evidence import has_unsupported_weather_condition


class PlanningResultBuilderMixin:
    """Result assembly shared by orchestrators without coupling it to a graph runtime.

    The concrete planning core supplies the maps provider and the deterministic
    evidence/booking helpers. Keeping the assembly algorithm here makes the
    workflow class responsible for orchestration rather than product-model
    conversion.
    """

    def _build_result_from_payload(
        self,
        payload: Any,
        request: PlanningRequest,
        pipeline_notes: list[str],
        agent_runs: list[AgentRunStep],
        *,
        poi_grounding: PoiGrounding | None = None,
        weather_guidance: WeatherGuidance | None = None,
        weather_citations: list[str] | None = None,
        weather_tool_results: dict[str, Any] | None = None,
        grounding_documents: list[dict[str, Any]] | None = None,
        hotel_recommendation: HotelRecommendation | None = None,
        transport_guidance: TransportGuidance | None = None,
    ) -> PlanningResult:
        expected_days = max(1, (request.end_date - request.start_date).days + 1)
        if len(payload.days) != expected_days:
            raise ValueError(f"Expected {expected_days} day entries but received {len(payload.days)}")

        zh_output = is_chinese_output(request)
        route_mode = self._resolve_route_mode(request.transport_mode)
        maps_grounded = self._maps_provider.provider_name != "stub-maps"
        planned_days: list[PlannedDay] = []
        filtered_food_item_count = 0

        for day_index, day in enumerate(payload.days, start=1):
            day_items = [item for item in day.items if not self._should_exclude_food_itinerary_item(item)]
            filtered_food_item_count += max(0, len(day.items) - len(day_items))
            poi_details = (
                [
                    self._resolve_item_poi(item, request, preferred_index=day_index + item_index)
                    for item_index, item in enumerate(day_items)
                ]
                if maps_grounded
                else [None for _ in day_items]
            )
            route_stops = [poi_to_route_stop(poi) for poi in poi_details if poi is not None]
            route_matrix = self._maps_provider.batch_route_matrix(route_stops, mode=route_mode) if route_stops else None
            matrix_lookup = {
                (cell.origin_stop_id, cell.destination_stop_id): cell
                for cell in (route_matrix.cells if route_matrix is not None else [])
            }

            planned_items: list[PlannedItem] = []
            previous_stop = None
            for item_index, item in enumerate(day_items):
                poi = poi_details[item_index]
                current_stop = route_stops[item_index] if maps_grounded else None
                matched_food = self._find_matching_featured_food(item.name, poi_grounding)
                matched_poi = self._find_matching_featured_poi(item.name, poi_grounding)
                if matched_food is not None and not self._is_food_item_type(item.type) and matched_poi is not None:
                    matched_food = None
                fallback_booking_info = (
                    self._build_food_booking_info(matched_food)
                    if matched_food is not None
                    else self._build_attraction_booking_info(matched_poi)
                    if matched_poi is not None
                    else None
                )
                fallback_visit_requirements = (
                    matched_poi.visit_requirements
                    if matched_poi is not None
                    else matched_food.visit_requirements
                    if isinstance(matched_food, ResearchPoi)
                    else None
                )
                route_ref = None
                note = item.note.strip() or (
                    "来自已配置的 LangGraph 行程草稿。"
                    if zh_output
                    else "Generated from the configured LangGraph itinerary draft."
                )
                if maps_grounded and previous_stop is not None and current_stop is not None:
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
                    note = (
                        f"{note} 从上一站转移到这里约 {matrix_cell.duration_minutes} 分钟。"
                        if zh_output
                        else f"{note} Transfer from previous stop is about {matrix_cell.duration_minutes} min."
                    )

                location_text = item.location.strip() or (
                    poi.location.address.formatted if poi is not None else request.destination
                )
                planned_items.append(
                    PlannedItem(
                        id=generate_identifier("item"),
                        type=item.type,
                        name=item.name,
                        start_time=item.start_time,
                        end_day_offset=item.end_day_offset,
                        end_time=item.end_time,
                        location=location_text,
                        score=item.score,
                        note=note,
                        booking_info=self._merge_booking_info(
                            getattr(item, "booking_info", None),
                            fallback_booking_info,
                            item_name=item.name,
                            grounding_documents=grounding_documents,
                        ),
                        visit_requirements=self._merge_visit_requirements(
                            getattr(item, "visit_requirements", None),
                            fallback_visit_requirements,
                        ),
                        location_ref=(
                            PlannedLocationReference(
                                provider=poi.provider,
                                poi_id=poi.id,
                                name=poi.name,
                                city=poi.city,
                                category=poi.category,
                                summary=poi.summary,
                                address=poi.location.address.formatted,
                                coordinates=poi.location.coordinates,
                            )
                            if poi is not None
                            else None
                        ),
                        route_from_previous=route_ref,
                    )
                )
                previous_stop = current_stop

            target_date = request.start_date + timedelta(days=day_index - 1)
            day_weather = self._build_day_weather(
                day_index,
                weather_guidance,
                weather_citations,
                weather_tool_results,
                target_date=target_date,
                trip_start_date=request.start_date,
                expected_days=expected_days,
            )
            planned_days.append(
                PlannedDay(
                    day_index=day_index,
                    title=day.title,
                    summary=day.summary,
                    total_cost=day.total_cost,
                    items=planned_items,
                    weather=day_weather,
                )
            )

        self._attach_nearby_poi_suggestions(planned_days, poi_grounding)

        if filtered_food_item_count:
            pipeline_notes.append(
                f"Filtered {filtered_food_item_count} food/cafe/restaurant itinerary item(s) from the final guide."
            )

        host = urlparse(self._llm_config.base_url).netloc or self._llm_config.base_url
        total_budget = (
            payload.total_budget_estimate
            if payload.total_budget_estimate and payload.total_budget_estimate > 0
            else request.budget
        )
        stay_recommendation = self._build_stay_recommendation(
            hotel_recommendation,
            destination=request.destination,
            accommodation_preference=request.accommodation_preference,
        )
        plan = PlanningResult(
            summary=payload.summary,
            total_budget_estimate=total_budget,
            days=planned_days,
            risks=payload.risks,
            stay_recommendation=stay_recommendation,
            transport_booking_summary=self._build_transport_booking_summary(
                getattr(payload, "transport_booking_summary", None),
                transport_guidance,
            ),
            trace=AgentTrace(
                provider="planning-core",
                workflow_id=generate_workflow_id(),
                notes=[
                    *pipeline_notes,
                    f"Default model endpoint: {host}.",
                    (
                        "Enriched the planner output with structured POI and route references "
                        f"via {self._maps_provider.provider_name}."
                        if maps_grounded
                        else "未配置真实地图服务，已关闭占位坐标、距离和路线分钟数。"
                    ),
                ],
                license_notice=None,
                agent_runs=agent_runs,
                grounding_documents=list(grounding_documents or []),
                transport_guidance=(
                    transport_guidance.model_dump(mode="json") if transport_guidance is not None else None
                ),
            ),
        )
        self._clear_unverified_lodging_prices(plan)
        self._downgrade_unverified_reservation_claims(plan)
        if weather_guidance is not None:
            verified_conditions = [
                forecast.condition
                for forecast in weather_guidance.daily_forecasts
                if forecast.forecast_type == "short_range" and forecast.source_urls
            ]
            plan.risks = [
                risk for risk in plan.risks if not has_unsupported_weather_condition(risk, verified_conditions)
            ]
        return enrich_plan_with_budget(plan, request)


__all__ = ["PlanningResultBuilderMixin"]
