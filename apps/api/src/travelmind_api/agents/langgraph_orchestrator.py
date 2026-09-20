from __future__ import annotations

import json
import time
from contextlib import nullcontext
from datetime import timedelta
from threading import Lock
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from travelmind_api.agents.base import AgentRunStep, PlanningRequest, PlanningResult
from travelmind_api.agents.helloagents import (
    HelloAgentsBrief,
    HelloAgentsHotelRecommendation,
    HelloAgentsOrchestrator,
    HelloAgentsPoiGrounding,
    HelloAgentsRoleConfig,
    HelloAgentsTransportGuidance,
    HelloAgentsWeatherGuidance,
)
from travelmind_api.agents.runtime import RoleProgressCallback, WorkflowRuntime
from travelmind_api.agents.workflows.state import (
    TRIP_GENERATION_GRAPH_VERSION,
    TRIP_GENERATION_STATE_SCHEMA_VERSION,
    TripGenerationState,
    build_input_fingerprint,
    non_sensitive_model_identity,
)
from travelmind_api.agents.workflows.trip_generation import build_initial_state, build_trip_generation_graph
from travelmind_api.core.security import generate_identifier
from travelmind_api.services.hotel_evidence import verify_hotel_pages
from travelmind_api.services.llm import LlmConfig, LlmEndpointConfig, LlmPlanningPayload, parse_planning_response
from travelmind_api.services.llm.localization import planning_payload_needs_language_repair
from travelmind_api.services.llm.prompts import PLANNING_OUTPUT_SCHEMA
from travelmind_api.services.llm.role_invoker import (
    OpenAICompatibleRoleInvoker,
    RoleInvocation,
    RoleInvocationResult,
    RoleInvoker,
)
from travelmind_api.services.maps import MapsPoiProvider
from travelmind_api.services.planning.role_models import parse_structured_response
from travelmind_api.services.poi_operation_evidence import verify_poi_open_days
from travelmind_api.services.search_connector import SearchServiceConfig
from travelmind_api.services.transport_evidence import verify_transport_candidate_pages
from travelmind_api.services.weather_evidence import verify_daily_forecast_pages


_ROLE_SEQUENCE = (
    "brief_parser",
    "poi_specialist",
    "weather_specialist",
    "hotel_specialist",
    "transport_specialist",
    "itinerary_planner",
)
_SEARCH_ROLES = {"poi_specialist", "weather_specialist", "hotel_specialist", "transport_specialist"}


class LangGraphOrchestrator(HelloAgentsOrchestrator):
    """LangGraph execution over the existing, battle-tested travel rules.

    This transitional implementation inherits the deterministic payload,
    evidence, validation, and result-building helpers. It deliberately does
    not import or instantiate ``hello_agents.SimpleAgent``; every model call
    goes through the framework-neutral ``RoleInvoker``.
    """

    def __init__(
        self,
        llm_config: LlmConfig | None,
        *,
        maps_provider: MapsPoiProvider | None = None,
        progress_callback: RoleProgressCallback | None = None,
        role_invoker: RoleInvoker | None = None,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
    ) -> None:
        super().__init__(
            llm_config,
            maps_provider=maps_provider,
            progress_callback=progress_callback,
        )
        self._role_invoker = role_invoker or OpenAICompatibleRoleInvoker()
        self._graph_checkpointer = checkpointer or InMemorySaver()
        self._workflow_runtime: WorkflowRuntime | None = None
        self._workflow_request: PlanningRequest | None = None
        self._workflow_role_configs: dict[str, HelloAgentsRoleConfig] = {}
        self._workflow_llm_configs: dict[str, LlmEndpointConfig] = {}
        self._workflow_role_locks: dict[tuple[str, str, str], Lock] = {}
        self._last_graph_state: TripGenerationState | None = None

    def plan_trip(self, request: PlanningRequest) -> PlanningResult:
        if self._llm_config is None:
            raise RuntimeError("LangGraph planning requires configured LLM settings")

        self._role_search_gateway_cache = {}
        self._native_role_citations = {}
        self._current_xhs_source_enabled = bool(request.xhs_source_enabled)
        self._current_user_id = request.user_id
        self._current_search_service = request.search_service or SearchServiceConfig.from_env()
        run_id = generate_identifier("run")
        self._workflow_runtime = WorkflowRuntime(
            run_id=run_id,
            job_id=self._execution_job_id,
            owner_user_id=request.user_id,
            progress_callback=self._progress_callback,
        )
        self._workflow_request = request
        self._workflow_role_configs = self._build_role_configs(request)
        self._workflow_llm_configs = self._build_role_llm_configs()
        self._workflow_role_locks = {}
        self._last_graph_state = None

        try:
            self._log_event(
                "langgraph_plan_trip_started",
                message="LangGraph trip planning started.",
                run_id=run_id,
                destination=request.destination,
            )
            graph = build_trip_generation_graph(self, checkpointer=self._graph_checkpointer)
            initial_state = build_initial_state(
                request,
                run_id=run_id,
                brief_endpoint=self._workflow_llm_configs["brief_parser"],
            )
            initial_state.update(
                {
                    "graph_version": TRIP_GENERATION_GRAPH_VERSION,
                    "schema_version": TRIP_GENERATION_STATE_SCHEMA_VERSION,
                    "input_fingerprint": build_input_fingerprint(
                        trip_request=initial_state["trip_request"],
                        output_locale=initial_state["output_locale"],
                        prompt_versions={
                            name: config.prompt_version
                            for name, config in self._workflow_role_configs.items()
                        },
                        model_identities={
                            name: non_sensitive_model_identity(config)
                            for name, config in self._workflow_llm_configs.items()
                        },
                    ),
                    "repair_count": 0,
                    "validation_errors": [],
                }
            )
            config = {"configurable": {"thread_id": run_id}}
            try:
                final_state = graph.invoke(initial_state, config=config)
            except Exception:
                snapshot = graph.get_state(config)
                self._last_graph_state = dict(snapshot.values) if snapshot.values else None
                raise
            self._last_graph_state = final_state
            result = PlanningResult.model_validate(final_state["planning_result"])
            self._log_event(
                "langgraph_plan_trip_completed",
                message="LangGraph trip planning completed.",
                run_id=run_id,
                day_count=len(result.days),
                risk_count=len(result.risks),
            )
            return result
        finally:
            self._workflow_runtime = None
            self._workflow_request = None
            self._workflow_role_configs = {}
            self._workflow_llm_configs = {}
            self._workflow_role_locks = {}
            self._current_xhs_source_enabled = False
            self._current_user_id = None
            self._current_search_service = None

    def get_graph_state(self) -> TripGenerationState | None:
        return dict(self._last_graph_state) if self._last_graph_state is not None else None

    def _request(self) -> PlanningRequest:
        if self._workflow_request is None:
            raise RuntimeError("LangGraph workflow request is unavailable")
        return self._workflow_request

    def _runtime(self) -> WorkflowRuntime:
        if self._workflow_runtime is None:
            raise RuntimeError("LangGraph workflow runtime is unavailable")
        return self._workflow_runtime

    def _invoke_workflow_role(
        self,
        role_name: str,
        input_payload: dict[str, Any],
    ) -> tuple[RoleInvocationResult, dict[str, Any]]:
        role_config = self._workflow_role_configs[role_name]
        endpoint = self._workflow_llm_configs[role_name]
        runtime = self._runtime()
        runtime.emit_progress(
            role_config.role_name,
            role_config.title,
            role_config.description,
            role_config.progress_percent,
        )
        effective_endpoint = endpoint
        if role_config.timeout_cap_seconds is not None:
            effective_endpoint = endpoint.model_copy(
                update={
                    "timeout_seconds": min(
                        float(endpoint.timeout_seconds),
                        float(role_config.timeout_cap_seconds),
                    )
                }
            )
        enriched_payload = self._augment_payload_with_tool_results(role_name, input_payload)
        prompt_payload = self._build_role_prompt_payload(enriched_payload, role_name=role_name)
        invocation = RoleInvocation(
            role_name=role_name,
            prompt_version=role_config.prompt_version,
            system_prompt=role_config.system_prompt,
            input_payload=prompt_payload,
            endpoint=effective_endpoint,
            temperature=role_config.temperature,
            max_tokens=role_config.max_tokens,
            stream=role_config.stream,
        )
        lock_context = nullcontext()
        if role_name in _SEARCH_ROLES and self._role_config_uses_search_capable_grok(role_name, endpoint):
            lock = self._workflow_role_locks.setdefault(self._rate_limit_identity(endpoint), Lock())
            lock_context = lock

        started = time.perf_counter()
        self._log_event(
            "langgraph_role_started",
            message=f"Role {role_name} started.",
            run_id=runtime.run_id,
            role=role_name,
            endpoint=self._describe_endpoint(effective_endpoint),
            model=effective_endpoint.model,
            payload_keys=sorted(prompt_payload.keys()),
        )
        try:
            with lock_context:
                result = self._role_invoker.invoke(invocation)
        except Exception as exc:
            self._log_event(
                "langgraph_role_failed",
                message=f"Role {role_name} failed.",
                level="ERROR",
                run_id=runtime.run_id,
                role=role_name,
                endpoint=self._describe_endpoint(effective_endpoint),
                model=effective_endpoint.model,
                elapsed_seconds=round(max(time.perf_counter() - started, 0.0), 3),
                reason=str(exc).strip() or exc.__class__.__name__,
            )
            raise
        runtime.check_cancelled()
        if not result.content.strip():
            raise RuntimeError(f"LangGraph role '{role_name}' returned an empty response")
        self._native_role_citations[role_name] = list(result.citations)
        self._log_event(
            "langgraph_role_completed",
            message=f"Role {role_name} completed.",
            run_id=runtime.run_id,
            role=role_name,
            endpoint=result.endpoint_host,
            model=result.model,
            elapsed_seconds=round(max(time.perf_counter() - started, 0.0), 3),
            response_chars=len(result.content),
        )
        return result, enriched_payload

    def parse_brief(self, state: TripGenerationState) -> dict[str, Any]:
        result, _ = self._invoke_workflow_role(
            "brief_parser",
            {"trip_request": state["trip_request"]},
        )
        brief = parse_structured_response(result.content, HelloAgentsBrief)
        return {
            "planning_brief": brief.model_dump(mode="json"),
            "role_results": {"brief_parser": result.checkpoint_metadata()},
        }

    def research_pois(self, state: TripGenerationState) -> dict[str, Any]:
        brief = HelloAgentsBrief.model_validate(state["planning_brief"])
        result, payload = self._invoke_workflow_role(
            "poi_specialist",
            self._build_poi_research_payload(self._request(), brief),
        )
        grounding = parse_structured_response(result.content, HelloAgentsPoiGrounding)
        return {
            "poi_payload": payload,
            "poi_grounding": grounding.model_dump(mode="json"),
            "role_results": {"poi_specialist": result.checkpoint_metadata()},
        }

    def research_weather(self, state: TripGenerationState) -> dict[str, Any]:
        request = self._request()
        brief = HelloAgentsBrief.model_validate(state["planning_brief"])
        result, payload = self._invoke_workflow_role(
            "weather_specialist",
            self._build_weather_research_payload(request, brief),
        )
        weather = parse_structured_response(result.content, HelloAgentsWeatherGuidance)
        weather.source_urls = list(
            dict.fromkeys(
                [
                    *[str(item).strip() for item in weather.source_urls if str(item).strip()],
                    *result.citations,
                ]
            )
        )
        self._validate_weather_date_coverage(weather, request)
        return {
            "weather_payload": payload,
            "weather_guidance": weather.model_dump(mode="json"),
            "role_results": {"weather_specialist": result.checkpoint_metadata()},
        }

    def join_initial_research(self, state: TripGenerationState) -> dict[str, Any]:
        grounding = HelloAgentsPoiGrounding.model_validate(state["poi_grounding"])
        weather = HelloAgentsWeatherGuidance.model_validate(state["weather_guidance"])
        self._validate_weather_date_coverage(weather, self._request())
        return {"poi_collection": self._build_poi_collection(grounding)}

    def research_hotels(self, state: TripGenerationState) -> dict[str, Any]:
        brief = HelloAgentsBrief.model_validate(state["planning_brief"])
        result, payload = self._invoke_workflow_role(
            "hotel_specialist",
            self._build_hotel_research_payload(
                self._request(),
                brief,
                poi_collection=state["poi_collection"],
            ),
        )
        hotel = parse_structured_response(result.content, HelloAgentsHotelRecommendation)
        return {
            "hotel_payload": payload,
            "hotel_recommendation": hotel.model_dump(mode="json"),
            "role_results": {"hotel_specialist": result.checkpoint_metadata()},
        }

    def research_transport(self, state: TripGenerationState) -> dict[str, Any]:
        brief = HelloAgentsBrief.model_validate(state["planning_brief"])
        result, payload = self._invoke_workflow_role(
            "transport_specialist",
            self._build_transport_research_payload(
                self._request(),
                brief,
                poi_collection=state["poi_collection"],
            ),
        )
        transport = parse_structured_response(result.content, HelloAgentsTransportGuidance)
        return {
            "transport_payload": payload,
            "transport_guidance": transport.model_dump(mode="json"),
            "role_results": {"transport_specialist": result.checkpoint_metadata()},
        }

    def verify_evidence(self, state: TripGenerationState) -> dict[str, Any]:
        request = self._request()
        brief = HelloAgentsBrief.model_validate(state["planning_brief"])
        poi_grounding = HelloAgentsPoiGrounding.model_validate(state["poi_grounding"])
        weather = HelloAgentsWeatherGuidance.model_validate(state["weather_guidance"])
        hotel = HelloAgentsHotelRecommendation.model_validate(state["hotel_recommendation"])
        transport = HelloAgentsTransportGuidance.model_validate(state["transport_guidance"])
        transport = self._sanitize_transport_service_candidates(transport, request)

        from travelmind_api.services.trip_image_enrichment import _resolve_tavily_image_search_config

        evidence_search_config = _resolve_tavily_image_search_config(request.search_service)
        weather = verify_daily_forecast_pages(weather, evidence_search_config)
        transport = verify_transport_candidate_pages(transport, evidence_search_config)
        hotel = verify_hotel_pages(hotel, evidence_search_config)
        poi_grounding = verify_poi_open_days(
            poi_grounding,
            start_date=request.start_date,
            end_date=request.end_date,
            search_config=evidence_search_config,
        )
        poi_collection = self._build_poi_collection(poi_grounding)
        hotel = self._sanitize_hotel_recommendation(
            hotel,
            destination=request.destination,
            accommodation_preference=request.accommodation_preference,
        )

        poi_tool_results = self._tool_results(state.get("poi_payload"))
        weather_tool_results = self._tool_results(state.get("weather_payload"))
        hotel_tool_results = self._tool_results(state.get("hotel_payload"))
        transport_tool_results = self._tool_results(state.get("transport_payload"))
        poi_citations = list(
            dict.fromkeys(
                [
                    *self._extract_urls_from_search_result(poi_tool_results),
                    *self._role_citations(state, "poi_specialist"),
                ]
            )
        )
        weather_citations = list(
            dict.fromkeys(
                [
                    *self._string_list(weather_tool_results.get("citations")),
                    *self._role_citations(state, "weather_specialist"),
                    *self._string_list(weather.source_urls),
                    *[
                        str(url).strip()
                        for forecast in weather.daily_forecasts
                        for url in forecast.source_urls
                        if str(url).strip()
                    ],
                ]
            )
        )
        hotel_citations = list(
            dict.fromkeys(
                [
                    *self._extract_urls_from_search_result(hotel_tool_results),
                    *self._role_citations(state, "hotel_specialist"),
                ]
            )
        )
        transport_citations = list(
            dict.fromkeys(
                [
                    *self._string_list(transport_tool_results.get("citations")),
                    *self._role_citations(state, "transport_specialist"),
                ]
            )
        )
        if not transport_citations:
            transport_citations = self._extract_urls_from_search_result(transport_tool_results)
        grounding_documents = self._merge_grounding_documents(
            poi_tool_results.get("grounding_docs"),
            weather_tool_results.get("grounding_docs"),
            hotel_tool_results.get("grounding_docs"),
            transport_tool_results.get("grounding_docs"),
        )

        role_configs = self._workflow_role_configs
        endpoints = self._workflow_llm_configs
        agent_runs = [
            self._build_agent_run(
                role_configs["brief_parser"],
                endpoints["brief_parser"],
                self._summarize_brief(brief),
            ),
            self._build_agent_run(
                role_configs["poi_specialist"],
                endpoints["poi_specialist"],
                self._summarize_pois(poi_grounding),
                extra_notes=self._build_poi_debug_notes(
                    state.get("poi_payload", {}),
                    poi_grounding,
                    poi_tool_results,
                ),
                extra_citations=poi_citations,
            ),
            self._build_agent_run(
                role_configs["weather_specialist"],
                endpoints["weather_specialist"],
                self._summarize_weather(weather),
                extra_citations=weather_citations,
            ),
            self._build_agent_run(
                role_configs["hotel_specialist"],
                endpoints["hotel_specialist"],
                self._summarize_hotels(hotel, destination=request.destination),
                extra_citations=hotel_citations,
            ),
            self._build_agent_run(
                role_configs["transport_specialist"],
                endpoints["transport_specialist"],
                self._summarize_transport(transport),
                extra_citations=transport_citations,
            ),
        ]
        return {
            "poi_grounding": poi_grounding.model_dump(mode="json"),
            "weather_guidance": weather.model_dump(mode="json"),
            "hotel_recommendation": hotel.model_dump(mode="json"),
            "transport_guidance": transport.model_dump(mode="json"),
            "poi_collection": poi_collection,
            "weather_citations": weather_citations,
            "weather_tool_results": weather_tool_results,
            "grounding_documents": grounding_documents,
            "agent_runs": [item.model_dump(mode="json") for item in agent_runs],
        }

    def draft_itinerary(self, state: TripGenerationState) -> dict[str, Any]:
        request = self._request()
        weather = HelloAgentsWeatherGuidance.model_validate(state["weather_guidance"])
        hotel = HelloAgentsHotelRecommendation.model_validate(state["hotel_recommendation"])
        transport = HelloAgentsTransportGuidance.model_validate(state["transport_guidance"])
        planner_payload = {
            "trip_request": state["trip_request"],
            "planning_brief": state["planning_brief"],
            "poi_collection": self._build_planner_poi_collection_payload(state["poi_collection"]),
            "poi_scheduling_policy": {
                "closed_dates_are_date_specific": True,
                "open_dates_remain_eligible": True,
                "selection_remains_planner_discretion": True,
                "do_not_treat_one_closed_date_as_global_exclusion": True,
            },
            "weather": self._build_planner_weather_payload(
                weather,
                expected_days=max(1, (request.end_date - request.start_date).days + 1),
            ),
            "hotels": self._build_planner_hotels_payload(
                hotel,
                destination=request.destination,
                accommodation_preference=request.accommodation_preference,
            ),
            "transport": self._build_planner_transport_payload(transport),
            "output_schema": PLANNING_OUTPUT_SCHEMA,
        }
        result, _ = self._invoke_workflow_role("itinerary_planner", planner_payload)
        payload = self._normalize_draft(parse_planning_response(result.content), transport)
        return {
            "planner_payload": planner_payload,
            "final_payload": payload.model_dump(mode="json"),
            "validation_errors": [],
            "repair_count": 0,
            "role_results": {"itinerary_planner": result.checkpoint_metadata()},
        }

    def validate_itinerary(self, state: TripGenerationState) -> dict[str, Any]:
        request = self._request()
        payload = LlmPlanningPayload.model_validate(state["final_payload"])
        transport = HelloAgentsTransportGuidance.model_validate(state["transport_guidance"])
        poi_grounding = HelloAgentsPoiGrounding.model_validate(state["poi_grounding"])
        payload = self._normalize_draft(payload, transport)
        try:
            self._validate_execution_constraints(
                payload,
                request,
                transport,
                available_poi_count=len(state["poi_collection"].get("pois", [])),
                poi_grounding=poi_grounding,
            )
        except ValueError as exc:
            message = str(exc)
            if not message.startswith("行程可执行性校验失败："):
                raise
            if int(state.get("repair_count", 0)) >= 1:
                raise
            errors = [
                value.strip()
                for value in message.removeprefix("行程可执行性校验失败：").split("；")
                if value.strip()
            ]
            return {
                "final_payload": payload.model_dump(mode="json"),
                "validation_errors": errors,
            }
        return {
            "final_payload": payload.model_dump(mode="json"),
            "validation_errors": [],
        }

    def repair_itinerary(self, state: TripGenerationState) -> dict[str, Any]:
        repair_payload = {
            **state["planner_payload"],
            "previous_itinerary": state["final_payload"],
            "validation_errors": list(state["validation_errors"]),
            "repair_instruction": (
                "上一个完整行程未通过后端硬校验。只修正 validation_errors 指出的冲突，"
                "保持已核验班次、住宿和无冲突日程不变，并重新输出一份完整 JSON 行程。"
                "如果冲突是某个 POI 在特定日期闭馆，只禁止该 POI 出现在这个日期；"
                "其他开放日期仍按路线、兴趣、节奏和优先级正常参与选择，不得把单日闭馆解释为全程排除。"
            ),
        }
        result, _ = self._invoke_workflow_role("itinerary_planner", repair_payload)
        transport = HelloAgentsTransportGuidance.model_validate(state["transport_guidance"])
        payload = self._normalize_draft(parse_planning_response(result.content), transport)
        return {
            "final_payload": payload.model_dump(mode="json"),
            "repair_count": int(state.get("repair_count", 0)) + 1,
            "validation_errors": [],
            "role_results": {"itinerary_planner": result.checkpoint_metadata()},
        }

    def assemble_result(self, state: TripGenerationState) -> dict[str, Any]:
        request = self._request()
        payload = LlmPlanningPayload.model_validate(state["final_payload"])
        poi_grounding = HelloAgentsPoiGrounding.model_validate(state["poi_grounding"])
        weather = HelloAgentsWeatherGuidance.model_validate(state["weather_guidance"])
        hotel = HelloAgentsHotelRecommendation.model_validate(state["hotel_recommendation"])
        transport = HelloAgentsTransportGuidance.model_validate(state["transport_guidance"])
        payload = self._normalize_draft(payload, transport)
        self._validate_execution_constraints(
            payload,
            request,
            transport,
            available_poi_count=len(state["poi_collection"].get("pois", [])),
            poi_grounding=poi_grounding,
        )

        agent_runs = [AgentRunStep.model_validate(item) for item in state.get("agent_runs", [])]
        planner_role = self._workflow_role_configs["itinerary_planner"]
        agent_runs.append(
            self._build_agent_run(
                planner_role,
                self._workflow_llm_configs["itinerary_planner"],
                self._summarize_itinerary(payload.summary, payload.days, payload.risks),
            )
        )
        pipeline_notes = self._build_pipeline_notes(state, weather, payload)
        result = self._build_result_from_payload(
            payload,
            request,
            pipeline_notes,
            agent_runs,
            poi_grounding=poi_grounding,
            weather_guidance=weather,
            weather_citations=state.get("weather_citations", []),
            weather_tool_results=state.get("weather_tool_results", {}),
            grounding_documents=state.get("grounding_documents", []),
            hotel_recommendation=hotel,
            transport_guidance=transport,
        )
        result.trace.provider = "langgraph"
        result.trace.workflow_id = self._runtime().run_id
        result.trace.license_notice = None
        result.trace.notes = [
            note.replace("HelloAgents", "LangGraph")
            for note in result.trace.notes
        ]
        return {
            "planning_result": result.model_dump(mode="json"),
            "pipeline_notes": pipeline_notes,
        }

    def _normalize_draft(
        self,
        payload: LlmPlanningPayload,
        transport: HelloAgentsTransportGuidance,
    ) -> LlmPlanningPayload:
        payload = self._mark_unverified_schedules_as_planning_windows(
            payload,
            self._request(),
            transport,
        )
        return self._normalize_departure_waiting_blocks(payload, transport)

    def _build_pipeline_notes(
        self,
        state: TripGenerationState,
        weather: HelloAgentsWeatherGuidance,
        payload: LlmPlanningPayload,
    ) -> list[str]:
        request = self._request()
        models = ", ".join(
            f"{name}={self._workflow_llm_configs[name].model}"
            for name in _ROLE_SEQUENCE
        )
        notes = [
            "Generated the itinerary with the LangGraph travel-planning workflow.",
            "Roles executed: brief_parser -> (poi_specialist || weather_specialist) -> initial_research_join -> (hotel_specialist || transport_specialist) -> evidence_join -> itinerary_planner -> execution_validation.",
            f"Role models: {models}.",
            "The graph uses explicit batch joins and one bounded deterministic-validation repair.",
            "Credentials, clients, callbacks, and database sessions were injected at runtime and excluded from checkpoint state.",
        ]
        expected_weather_dates = {
            request.start_date + timedelta(days=offset)
            for offset in range(max(1, (request.end_date - request.start_date).days + 1))
        }
        dated_weather = {
            forecast.date: tuple(
                dict.fromkeys(str(url).strip() for url in forecast.source_urls if str(url).strip())
            )
            for forecast in weather.daily_forecasts
        }
        if any(not dated_weather.get(day) for day in expected_weather_dates):
            notes.append("天气已按日期生成，但至少一天没有独立逐日来源；该日仅保留城市/月份参考并标注风险。")
        if any(forecast.evidence_status == "referenced" for forecast in weather.daily_forecasts):
            notes.append("至少一天逐日天气保留了日期与来源，但正文抓取或解析未完成；已作为参考展示并提示出发前刷新。")
        if any(forecast.evidence_status == "conflicted" for forecast in weather.daily_forecasts):
            notes.append("至少一天逐日天气与来源正文存在字段冲突；仅清空冲突字段，其余字段继续按证据等级展示。")
        if self._weather_guidance_needs_language_repair(weather, request):
            notes.append("Weather specialist output did not fully match the requested locale; returning the original specialist output without localization repair.")
        if planning_payload_needs_language_repair(payload, request):
            notes.append("Itinerary planner output did not fully match the requested locale; returning the original planner output without localization repair.")
        if int(state.get("repair_count", 0)):
            notes.append("The itinerary draft required one deterministic-validation repair.")
        return notes

    @staticmethod
    def _tool_results(payload: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        value = payload.get("tool_results")
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _role_citations(state: TripGenerationState, role_name: str) -> list[str]:
        role_results = state.get("role_results", {})
        entry = role_results.get(role_name) if isinstance(role_results, dict) else None
        citations = entry.get("citations") if isinstance(entry, dict) else None
        return LangGraphOrchestrator._string_list(citations)
