from __future__ import annotations

from collections.abc import Callable
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
from travelmind_api.services.budgeting import enrich_plan_with_budget
from travelmind_api.services.llm.localization import is_chinese_output
from travelmind_api.services.maps import MapsPoiProvider, PoiDetail, PoiSearchResult, TravelMode, build_maps_provider, poi_to_route_stop


class StubOrchestrator:
    def __init__(self, maps_provider: MapsPoiProvider | None = None) -> None:
        self._maps_provider = maps_provider or build_maps_provider("stub")
        self._execution_job_id: str | None = None
        self._execution_run_id: str | None = None
        self._execution_resume = False
        self._execution_cancellation_check: Callable[[], bool] | None = None
        self._execution_expected_input_fingerprint: str | None = None

    def set_execution_context(
        self,
        *,
        job_id: str | None = None,
        run_id: str | None = None,
        resume: bool = False,
        cancellation_check: Callable[[], bool] | None = None,
        expected_input_fingerprint: str | None = None,
    ) -> None:
        self._execution_job_id = job_id
        self._execution_run_id = run_id
        self._execution_resume = resume
        self._execution_cancellation_check = cancellation_check
        self._execution_expected_input_fingerprint = expected_input_fingerprint

    def plan_trip(self, request: PlanningRequest) -> PlanningResult:
        zh_output = is_chinese_output(request)
        total_days = max(1, (request.end_date - request.start_date).days + 1)
        budget_per_day = round(request.budget / total_days, 2)
        interests = request.interests or self._default_interests(zh_output)
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
            slot_definitions = (
                [
                    ("sight", f"上午 {focus}", "09:00", "11:30", "以低切换成本的步行锚点开场。"),
                    ("meal", "中午在交通方便处用餐", "12:00", "13:30", "把转场和预算波动压到更稳。"),
                    ("explore", f"下午 {self._travel_mode_label(route_mode, zh_output)} 轻量串联", "14:00", "18:00", "留出一个强记忆点，同时避免节奏过满。"),
                ]
                if zh_output
                else [
                    ("sight", f"Morning {focus}", "09:00", "11:30", "Low-friction start with a walkable anchor."),
                    ("meal", "Lunch near transit", "12:00", "13:30", "Keeps transfer costs predictable."),
                    ("explore", f"Afternoon {request.transport_mode} loop", "14:00", "18:00", "Balances pace with one strong visual moment."),
                ]
            )

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
                    note = (
                        f"{base_note} 从上一站转移到这里约 {matrix_cell.duration_minutes} 分钟。"
                        if zh_output
                        else f"{base_note} Route from previous stop is about {matrix_cell.duration_minutes} min."
                    )

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

            if zh_output:
                day_summary = f"这一天以 {request.destination} 的 {focus} 为主，整体节奏偏{self._pace_label(request.pace, zh_output)}。"
                if inter_stop_minutes:
                    day_summary += f" 预计站点间转移约 {inter_stop_minutes} 分钟，方式为{self._travel_mode_label(route_mode, zh_output)}。"
                day_title = f"{current_date.isoformat()} | {request.destination} 第{offset + 1}天"
            else:
                day_summary = f"A {request.pace} day centered on {focus} in {request.destination}."
                if inter_stop_minutes:
                    day_summary += f" Estimated inter-stop travel: {inter_stop_minutes} min by {route_mode}."
                day_title = f"{current_date.isoformat()} | {focus.title()}"

            days.append(
                PlannedDay(
                    day_index=offset + 1,
                    title=day_title,
                    summary=day_summary,
                    total_cost=budget_per_day,
                    items=items,
                )
            )

        risks: list[str] = []
        if request.pace == "packed":
            risks.append("紧凑节奏会提高疲劳和转场风险。" if zh_output else "Packed pace increases fatigue and transfer risk.")
        if request.budget / total_days < 500:
            risks.append("在交通和住宿最终敲定后，预算可能会偏紧。" if zh_output else "Budget may be tight once transport and accommodation are finalized.")

        summary = (
            f"{request.destination} {total_days} 天行程，按{self._pace_label(request.pace, zh_output)}节奏为 {request.travelers} 位出行者安排。"
            if zh_output
            else f"{request.destination} trip with {total_days} day(s), tuned for {request.pace} pacing and {request.travelers} traveler(s)."
        )
        trace_notes = (
            [
                "已生成稳定的 MVP 占位行程。",
                "当前输出结构与后续可替换 orchestrator 保持兼容。",
                f"已通过 {self._maps_provider.provider_name} 附加结构化 POI 与路线引用。",
                f"全程共解析 {total_pois} 个 POI 引用。",
            ]
            if zh_output
            else [
                "Generated a deterministic MVP itinerary.",
                "Kept the output compatible with later orchestrator swaps.",
                f"Attached structured POI and route references via {self._maps_provider.provider_name}.",
                f"Resolved {total_pois} POI references across the trip.",
            ]
        )

        plan = PlanningResult(
            summary=summary,
            total_budget_estimate=request.budget,
            days=days,
            risks=risks,
            trace=AgentTrace(
                provider="stub",
                workflow_id=generate_workflow_id(),
                notes=trace_notes,
            ),
        )
        return enrich_plan_with_budget(plan, request)

    def refine_trip(
        self,
        request: PlanningRequest,
        current_plan: PlanningResult,
        *,
        instruction: str,
        scope: str,
        day_index: int | None,
    ) -> PlanningResult:
        refined = current_plan.model_copy(deep=True)
        refined.trace.notes.append("Applied stub refine flow on top of the existing itinerary context.")
        refined.trace.notes.append(f"Refine scope: {scope}.")
        if day_index is not None:
            self._require_day(refined, day_index)
            refined.trace.notes.append(f"Refined day {day_index}.")
        refined.trace.notes.append(f"Instruction: {instruction}")

        if day_index is not None:
            for day in refined.days:
                if day.day_index != day_index:
                    continue
                day.title = f"{day.title} | Refined"
                day.summary = f"{day.summary} Refinement: {instruction}."
                if day.items:
                    day.items[0].note = f"{day.items[0].note} Refinement: {instruction}."
                break
            refined.summary = f"{refined.summary} Refined day {day_index} for {scope}."
        else:
            refined.summary = f"{refined.summary} Refined for {scope}: {instruction}."
            if refined.days:
                refined.days[0].summary = f"{refined.days[0].summary} Refinement scope {scope}: {instruction}."
                if refined.days[0].items:
                    refined.days[0].items[0].note = f"{refined.days[0].items[0].note} Refinement scope {scope}: {instruction}."

        return enrich_plan_with_budget(refined, request)

    def summarize_sources(self, destination: str, findings: list[str]) -> SourceSummary:
        return SourceSummary(
            summary=f"Collected grounded signals for {destination} from official and user-supplied sources.",
            bullets=findings[:5],
        )

    def draft_export_payload(self, request: PlanningRequest, plan: PlanningResult) -> ExportDraft:
        zh_output = is_chinese_output(request)
        lines = (
            [
                f"目的地：{request.destination}",
                f"日期：{request.start_date.isoformat()} 到 {request.end_date.isoformat()}",
                f"预算：{request.budget}",
                f"出行人数：{request.travelers}",
                f"摘要：{plan.summary}",
            ]
            if zh_output
            else [
                f"Destination: {request.destination}",
                f"Dates: {request.start_date.isoformat()} to {request.end_date.isoformat()}",
                f"Budget: {request.budget}",
                f"Travelers: {request.travelers}",
                f"Summary: {plan.summary}",
            ]
        )
        for day in plan.days:
            lines.append(
                f"第 {day.day_index} 天：{day.title} | {day.summary}"
                if zh_output
                else f"Day {day.day_index}: {day.title} | {day.summary}"
            )
            for item in day.items:
                route_suffix = ""
                if item.route_from_previous is not None:
                    route_suffix = (
                        f" | 转场 {item.route_from_previous.duration_minutes} 分钟"
                        if zh_output
                        else f" | transfer {item.route_from_previous.duration_minutes} min"
                    )
                lines.append(
                    f"- {item.start_time}-{item.end_time}：{item.name} @ {item.location}{route_suffix}"
                    if zh_output
                    else f"- {item.start_time}-{item.end_time}: {item.name} @ {item.location}{route_suffix}"
                )
        return ExportDraft(
            title=request.title,
            subtitle=(f"{request.destination} 行程包" if zh_output else f"{request.destination} planning packet"),
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

    def _require_day(self, plan: PlanningResult, day_index: int) -> None:
        if not any(day.day_index == day_index for day in plan.days):
            raise ValueError(f"day_index {day_index} is outside the itinerary range")

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

    def _default_interests(self, zh_output: bool) -> list[str]:
        return ["本地亮点", "美食", "慢节奏散步"] if zh_output else ["local highlights", "food", "slow walks"]

    def _pace_label(self, pace: str, zh_output: bool) -> str:
        if not zh_output:
            return pace
        mapping = {
            "slow": "慢节奏",
            "balanced": "均衡",
            "packed": "紧凑",
        }
        return mapping.get((pace or "balanced").strip().lower(), "均衡")

    def _travel_mode_label(self, route_mode: TravelMode, zh_output: bool) -> str:
        if not zh_output:
            return route_mode
        mapping = {
            "walking": "步行",
            "transit": "公共交通",
            "driving": "驾车",
            "cycling": "骑行",
            "mixed": "混合交通",
        }
        return mapping.get(route_mode, "混合交通")
