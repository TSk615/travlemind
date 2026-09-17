from __future__ import annotations

from urllib.parse import urlparse

from travelmind_api.agents.base import (
    AgentTrace,
    BookingInfo,
    PlannedDay,
    PlannedItem,
    PlannedLocationReference,
    PlannedRouteReference,
    PlanningRequest,
    PlanningResult,
    TransportBookingSummary,
    VisitRequirements,
)
from travelmind_api.agents.stub import StubOrchestrator
from travelmind_api.core.security import generate_identifier, generate_workflow_id
from travelmind_api.services.budgeting import enrich_plan_with_budget
from travelmind_api.services.llm.client import OpenAICompatibleClient
from travelmind_api.services.llm.config import LlmConfig, normalize_provider_protocol
from travelmind_api.services.llm.localization import infer_output_locale, is_chinese_output, planning_payload_needs_language_repair
from travelmind_api.services.llm.parser import LlmPlanningPayload, parse_planning_response
from travelmind_api.services.llm.prompts import build_planning_prompt_bundle, build_refinement_prompt_bundle
from travelmind_api.services.maps import MapsPoiProvider, PoiDetail, poi_to_route_stop


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
        target_locale = infer_output_locale(request)
        try:
            prompt_bundle = build_planning_prompt_bundle(request)
            content = self._llm_client.create_chat_completion(messages=prompt_bundle.as_messages())
            payload = parse_planning_response(content)
            language_warning = planning_payload_needs_language_repair(payload, request)
            result = self._build_result_from_payload(payload, request, prompt_bundle.version, mode="plan")
            if language_warning:
                result.trace.notes.append(
                    "The planner output did not fully match the requested locale; returning the original model output without localization repair."
                )
            return result
        except Exception as exc:
            fallback = super().plan_trip(request)
            reason = str(exc).strip() or exc.__class__.__name__
            if target_locale == "zh-CN":
                fallback.trace.notes.append(f"OpenAI-compatible generation fallback triggered: {reason}")
            else:
                fallback.trace.notes.append(f"OpenAI-compatible generation fallback triggered: {reason}")
            fallback.trace.notes.append("Returned the deterministic stub itinerary after LLM generation failed.")
            return fallback

    def refine_trip(
        self,
        request: PlanningRequest,
        current_plan: PlanningResult,
        *,
        instruction: str,
        scope: str,
        day_index: int | None,
    ) -> PlanningResult:
        target_locale = infer_output_locale(request)
        try:
            if day_index is not None:
                self._require_day(current_plan, day_index)
            prompt_bundle = build_refinement_prompt_bundle(
                request,
                current_plan,
                instruction=instruction,
                scope=scope,
                day_index=day_index,
            )
            content = self._llm_client.create_chat_completion(messages=prompt_bundle.as_messages())
            payload = parse_planning_response(content)
            language_warning = planning_payload_needs_language_repair(payload, request)
            result = self._build_result_from_payload(payload, request, prompt_bundle.version, mode="refine")
            result = self._merge_refine_structured_fields(current_plan, result)
            result.trace.notes.append(f"Refine scope: {scope}.")
            if day_index is not None:
                result.trace.notes.append(f"Refined day {day_index}.")
            result.trace.notes.append(f"Instruction: {instruction}")
            if language_warning:
                result.trace.notes.append(
                    "The refine output did not fully match the requested locale; returning the original model output without localization repair."
                )
            return result
        except Exception as exc:
            fallback = super().refine_trip(request, current_plan, instruction=instruction, scope=scope, day_index=day_index)
            reason = str(exc).strip() or exc.__class__.__name__
            if target_locale == "zh-CN":
                fallback.trace.notes.append(f"OpenAI-compatible refine fallback triggered: {reason}")
            else:
                fallback.trace.notes.append(f"OpenAI-compatible refine fallback triggered: {reason}")
            return fallback

    def _build_result_from_payload(
        self,
        payload: LlmPlanningPayload,
        request: PlanningRequest,
        prompt_version: str,
        *,
        mode: str,
    ) -> PlanningResult:
        expected_days = max(1, (request.end_date - request.start_date).days + 1)
        if len(payload.days) != expected_days:
            raise ValueError(f"Expected {expected_days} day entries but received {len(payload.days)}")

        zh_output = is_chinese_output(request)
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
                note = item.note.strip() or (
                    "来自已配置的 OpenAI-compatible 行程草稿。"
                    if zh_output
                    else "Generated from the configured OpenAI-compatible itinerary draft."
                )
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
                    note = (
                        f"{note} 从上一站转移到这里约 {matrix_cell.duration_minutes} 分钟。"
                        if zh_output
                        else f"{note} Transfer from previous stop is about {matrix_cell.duration_minutes} min."
                    )

                location_text = item.location.strip() or poi.location.address.formatted
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
                        booking_info=self._coerce_booking_info(getattr(item, "booking_info", None)),
                        visit_requirements=self._coerce_visit_requirements(getattr(item, "visit_requirements", None)),
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
        trace_notes = self._build_trace_notes(host, prompt_version, mode)
        plan = PlanningResult(
            summary=payload.summary,
            total_budget_estimate=total_budget,
            days=planned_days,
            risks=payload.risks,
            transport_booking_summary=self._coerce_transport_booking_summary(getattr(payload, "transport_booking_summary", None)),
            trace=AgentTrace(
                provider=self._trace_provider_name(),
                workflow_id=generate_workflow_id(),
                notes=trace_notes,
            ),
        )
        return enrich_plan_with_budget(plan, request)

    def _trace_provider_name(self) -> str:
        protocol = normalize_provider_protocol(self._llm_config.provider_protocol)
        if protocol in {"openai", "newapi", "neiapi"}:
            return "openai-compatible"
        return f"{protocol}-official"

    def _coerce_booking_info(self, raw: object | None) -> BookingInfo | None:
        if raw is None:
            return None
        if isinstance(raw, BookingInfo):
            return raw
        if hasattr(raw, "model_dump"):
            return BookingInfo.model_validate(raw.model_dump(mode="json"))
        if isinstance(raw, dict):
            return BookingInfo.model_validate(raw)
        return None

    def _coerce_visit_requirements(self, raw: object | None) -> VisitRequirements | None:
        if raw is None:
            return None
        if isinstance(raw, VisitRequirements):
            return raw
        if hasattr(raw, "model_dump"):
            return VisitRequirements.model_validate(raw.model_dump(mode="json"))
        if isinstance(raw, dict):
            return VisitRequirements.model_validate(raw)
        return None

    def _coerce_transport_booking_summary(self, raw: object | None) -> TransportBookingSummary | None:
        if raw is None:
            return None
        if isinstance(raw, TransportBookingSummary):
            return raw
        if hasattr(raw, "model_dump"):
            return TransportBookingSummary.model_validate(raw.model_dump(mode="json"))
        if isinstance(raw, dict):
            return TransportBookingSummary.model_validate(raw)
        return None

    def _merge_refine_structured_fields(self, current_plan: PlanningResult, result: PlanningResult) -> PlanningResult:
        merged = result.model_copy(deep=True)
        previous_days = {day.day_index: day for day in current_plan.days}
        for day in merged.days:
            previous_day = previous_days.get(day.day_index)
            if previous_day is None:
                continue
            for index, item in enumerate(day.items):
                if index >= len(previous_day.items):
                    continue
                previous_item = previous_day.items[index]
                if not self._should_reuse_previous_item(previous_item, item):
                    continue
                item.id = previous_item.id
                item.image_urls = list(previous_item.image_urls)
                item.image_source_urls = list(previous_item.image_source_urls)
                item.image_status = previous_item.image_status
                item.image_priority_tier = previous_item.image_priority_tier
                item.image_priority_reason = previous_item.image_priority_reason
                item.image_failure_reason = previous_item.image_failure_reason
                if previous_item.booking_info is not None:
                    item.booking_info = self._merge_booking_info_with_previous(item.booking_info, previous_item.booking_info)
                if previous_item.visit_requirements is not None:
                    item.visit_requirements = self._merge_visit_requirements_with_previous(item.visit_requirements, previous_item.visit_requirements)
        if current_plan.transport_booking_summary is not None:
            merged.transport_booking_summary = self._merge_transport_summary_with_previous(
                merged.transport_booking_summary,
                current_plan.transport_booking_summary,
            )
        if current_plan.stay_recommendation is not None and merged.stay_recommendation is None:
            merged.stay_recommendation = current_plan.stay_recommendation.model_copy(deep=True)
        return merged

    def _should_reuse_previous_item(self, previous_item: PlannedItem, next_item: PlannedItem) -> bool:
        previous_name = str(previous_item.name or "").strip().casefold()
        next_name = str(next_item.name or "").strip().casefold()
        if previous_name and next_name and previous_name == next_name:
            return True
        return (
            str(previous_item.type or "").strip().casefold() == str(next_item.type or "").strip().casefold()
            and previous_item.start_time == next_item.start_time
            and previous_item.end_time == next_item.end_time
        )

    def _merge_booking_info_with_previous(self, current: BookingInfo | None, previous: BookingInfo) -> BookingInfo:
        if current is None:
            return previous.model_copy(deep=True)
        merged = current.model_copy(deep=True)
        if merged.price_label is None:
            merged.price_label = previous.price_label
        if merged.estimated_price is None:
            merged.estimated_price = previous.estimated_price
        merged.booking_required = merged.booking_required or previous.booking_required
        merged.reservation_required = merged.reservation_required or previous.reservation_required
        if merged.official_booking_url is None:
            merged.official_booking_url = previous.official_booking_url
        if merged.booking_window is None:
            merged.booking_window = previous.booking_window
        if merged.reminder is None:
            merged.reminder = previous.reminder
        merged.notes = list(dict.fromkeys([*merged.notes, *previous.notes]))
        merged.source_urls = list(dict.fromkeys([*merged.source_urls, *previous.source_urls]))
        return merged

    def _merge_visit_requirements_with_previous(self, current: VisitRequirements | None, previous: VisitRequirements) -> VisitRequirements:
        if current is None:
            return previous.model_copy(deep=True)
        merged = current.model_copy(deep=True)
        if merged.reservation_policy is None:
            merged.reservation_policy = previous.reservation_policy
        merged.timed_entry = merged.timed_entry or previous.timed_entry
        merged.identity_required = merged.identity_required or previous.identity_required
        if merged.advance_booking_note is None:
            merged.advance_booking_note = previous.advance_booking_note
        merged.notes = list(dict.fromkeys([*merged.notes, *previous.notes]))
        return merged

    def _merge_transport_summary_with_previous(
        self,
        current: TransportBookingSummary | None,
        previous: TransportBookingSummary,
    ) -> TransportBookingSummary:
        if current is None:
            return previous.model_copy(deep=True)
        merged = current.model_copy(deep=True)
        if merged.summary is None:
            merged.summary = previous.summary
        if merged.recommended_option is None:
            merged.recommended_option = previous.recommended_option
        if merged.estimated_intercity_cost <= 0:
            merged.estimated_intercity_cost = previous.estimated_intercity_cost
        if merged.estimated_local_transport_cost <= 0:
            merged.estimated_local_transport_cost = previous.estimated_local_transport_cost
        merged.booking_required = merged.booking_required or previous.booking_required
        if merged.official_booking_url is None:
            merged.official_booking_url = previous.official_booking_url
        if merged.booking_window is None:
            merged.booking_window = previous.booking_window
        merged.pass_or_ticket_notes = list(dict.fromkeys([*merged.pass_or_ticket_notes, *previous.pass_or_ticket_notes]))
        merged.reminders = list(dict.fromkeys([*merged.reminders, *previous.reminders]))
        merged.notes = list(dict.fromkeys([*merged.notes, *previous.notes]))
        merged.source_urls = list(dict.fromkeys([*merged.source_urls, *previous.source_urls]))
        return merged

    def _build_trace_notes(self, host: str, prompt_version: str, mode: str) -> list[str]:
        if mode == "refine":
            return [
                f"Refined the itinerary with {self._llm_config.provider_protocol} model {self._llm_config.model}.",
                f"Sent a {self._llm_config.provider_protocol}/{self._llm_config.wire_api} request to {host}.",
                "Passed the current itinerary back into the model as context so unchanged content is preserved whenever possible.",
                f"Planning prompt version: {prompt_version}.",
            ]
        return [
            f"Generated the itinerary with {self._llm_config.provider_protocol} model {self._llm_config.model}.",
            f"Sent a {self._llm_config.provider_protocol}/{self._llm_config.wire_api} request to {host}.",
            f"Refined the LLM draft with structured POI and route references via {self._maps_provider.provider_name}.",
            f"Planning prompt version: {prompt_version}.",
        ]

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
