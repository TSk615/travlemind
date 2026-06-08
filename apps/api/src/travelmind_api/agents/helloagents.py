from __future__ import annotations

import logging
import json
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from importlib import import_module
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from travelmind_api.agents.base import (
    AgentRunStep,
    AgentTrace,
    BookingInfo,
    ExportDraft,
    PlannedDay,
    PlannedDayWeather,
    PlannedItem,
    PlannedLocationReference,
    PlannedRouteReference,
    PlanningRequest,
    PlanningResult,
    SourceSummary,
    TransportBookingSummary,
    VisitRequirements,
)
from travelmind_api.agents.stub import StubOrchestrator
from travelmind_api.core.logging_utils import log_job_event
from travelmind_api.core.security import generate_identifier, generate_workflow_id
from travelmind_api.services.budgeting import enrich_plan_with_budget
from travelmind_api.services.llm import LlmConfig, LlmEndpointConfig, OpenAICompatibleClient, build_planning_messages, parse_planning_response
from travelmind_api.services.llm.localization import build_output_language_instruction, infer_output_locale, is_chinese_output, planning_payload_needs_language_repair
from travelmind_api.prompts.roles.helloagents import (
    build_attraction_specialist_prompt,
    build_brief_parser_prompt,
    build_hotel_specialist_prompt,
    build_itinerary_planner_prompt,
    build_transport_specialist_prompt,
    build_weather_specialist_prompt,
)
from travelmind_api.services.llm.prompts import PLANNING_OUTPUT_SCHEMA
from travelmind_api.services.maps import MapsPoiProvider, PoiDetail, PoiSearchResult, poi_to_route_stop
from travelmind_api.services.search_connector import ConfiguredSearchGateway, SearchServiceConfig
from travelmind_api.services.search_service import search_documents

_LOGGER = logging.getLogger(__name__)

_LICENSE_NOTICE = "PoC adapter only. Do not ship a commercial release while this adapter remains in production."
_ROLE_SEQUENCE = (
    "brief_parser",
    "attraction_specialist",
    "weather_specialist",
    "hotel_specialist",
    "transport_specialist",
    "itinerary_planner",
)
_SPECIALIST_PARALLEL_ROLES = ("attraction_specialist", "weather_specialist", "hotel_specialist", "transport_specialist")
_TOOL_RESULT_URL_METADATA_KEYS = {
    "url",
    "urls",
    "link",
    "links",
    "href",
    "website",
    "crawl_urls",
    "citations",
    "source_url",
    "source_urls",
}

RoleProgressCallback = Callable[[str, str, str, int], None]


class HelloAgentsBrief(BaseModel):
    destination: str = Field(min_length=1)
    trip_days: int = Field(ge=1)
    budget_band: str = Field(default="")
    budget_is_hard_constraint: bool = True
    budget_priority: str = Field(default="")
    allow_budget_flex: bool = False
    pace: str = Field(default="")
    must_have: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    transport: str = Field(default="")
    accommodation: str = Field(default="")
    interests: list[str] = Field(default_factory=list)
    planning_constraints: list[str] = Field(default_factory=list)

    @field_validator("budget_is_hard_constraint", "allow_budget_flex", mode="before")
    @classmethod
    def _coerce_bool(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        normalized = str(value or "").strip().lower()
        if normalized in {"1", "true", "yes", "y", "required"}:
            return True
        if normalized in {"0", "false", "no", "n", "not_required"}:
            return False
        return False


class HelloAgentsResearchPoi(BaseModel):
    name: str = Field(min_length=1)
    area: str = Field(default="")
    reason: str = Field(default="")
    suggested_time: str = Field(default="")
    booking_info: BookingInfo | None = None
    visit_requirements: VisitRequirements | None = None


class HelloAgentsAttractionGrounding(BaseModel):
    candidate_areas: list[str] = Field(default_factory=list)
    featured_pois: list[HelloAgentsResearchPoi] = Field(default_factory=list)
    sequencing_hints: list[str] = Field(default_factory=list)
    crowd_notes: list[str] = Field(default_factory=list)
    attraction_risks: list[str] = Field(default_factory=list)


class HelloAgentsWeatherGuidance(BaseModel):
    overall_outlook: str = Field(min_length=1)
    daily_outlook: list[str] = Field(default_factory=list)
    packing_notes: list[str] = Field(default_factory=list)
    timing_guidance: list[str] = Field(default_factory=list)
    weather_risks: list[str] = Field(default_factory=list)


class HelloAgentsHotelCandidate(BaseModel):
    name: str = Field(min_length=1)
    area: str = Field(default="")
    hotel_type: str = Field(default="")
    reason: str = Field(default="")
    price_hint: str = Field(default="")
    price_checked_at: str = Field(default="")
    price_valid_for: str = Field(default="")
    review_score: str = Field(default="")
    review_count: str = Field(default="")
    review_summary: str = Field(default="")
    preference_match: str = Field(default="")
    booking_confidence: str = Field(default="")
    caveats: list[str] = Field(default_factory=list)


class HelloAgentsHotelRecommendation(BaseModel):
    recommended_areas: list[str] = Field(default_factory=list)
    final_recommended_hotel: HelloAgentsHotelCandidate | None = None
    hotel_candidates: list[HelloAgentsHotelCandidate] = Field(default_factory=list)
    stay_strategy: list[str] = Field(default_factory=list)
    budget_notes: list[str] = Field(default_factory=list)
    price_timeliness_notes: list[str] = Field(default_factory=list)
    review_notes: list[str] = Field(default_factory=list)
    preference_match_notes: list[str] = Field(default_factory=list)
    hotel_risks: list[str] = Field(default_factory=list)


class HelloAgentsTransportOption(BaseModel):
    mode: str = Field(default="")
    route: str = Field(default="")
    duration_hint: str = Field(default="")
    price_hint: str = Field(default="")
    booking_window: str = Field(default="")
    reason: str = Field(default="")
    official_booking_url: str = Field(default="")
    booking_required: bool = False
    reservation_required: bool = False
    booking_notes: list[str] = Field(default_factory=list)

    @field_validator("booking_required", "reservation_required", mode="before")
    @classmethod
    def _coerce_bool(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        normalized = str(value or "").strip().lower()
        if normalized in {"1", "true", "yes", "y", "required"}:
            return True
        if normalized in {"0", "false", "no", "n", "not_required"}:
            return False
        return False


class HelloAgentsTransportGuidance(BaseModel):
    intercity_options: list[HelloAgentsTransportOption] = Field(default_factory=list)
    arrival_strategy: list[str] = Field(default_factory=list)
    local_mobility_strategy: list[str] = Field(default_factory=list)
    pass_or_ticket_notes: list[str] = Field(default_factory=list)
    budget_notes: list[str] = Field(default_factory=list)
    transport_risks: list[str] = Field(default_factory=list)
    sequencing_constraints: list[str] = Field(default_factory=list)
    estimated_intercity_cost: float = 0.0
    estimated_local_transport_cost: float = 0.0
    summary: str = Field(default="")
    recommended_option: str = Field(default="")
    booking_required: bool = False
    official_booking_url: str = Field(default="")
    booking_window: str = Field(default="")
    reminders: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)

    @field_validator("estimated_intercity_cost", "estimated_local_transport_cost", mode="before")
    @classmethod
    def _coerce_cost(cls, value: Any) -> float:
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            match = re.search(r"-?\d+(?:\.\d+)?", str(value))
            return float(match.group()) if match else 0.0

    @field_validator("booking_required", mode="before")
    @classmethod
    def _coerce_bool(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        normalized = str(value or "").strip().lower()
        if normalized in {"1", "true", "yes", "y", "required"}:
            return True
        if normalized in {"0", "false", "no", "n", "not_required"}:
            return False
        return False


@dataclass(frozen=True)
class HelloAgentsRoleConfig:
    role_name: str
    title: str
    description: str
    prompt_focus: str
    agent_class_name: str
    system_prompt: str
    prompt_version: str
    temperature: float = 0.2
    progress_percent: int = 0


@dataclass(frozen=True)
class HelloAgentsInvokeResult:
    content: str
    usage: dict[str, Any]
    latency_ms: int


class HelloAgentsCompatibleLLM:
    def __init__(self, config: LlmEndpointConfig, *, temperature: float = 0.2, max_tokens: int | None = None) -> None:
        effective_timeout = max(float(config.timeout_seconds), 120.0)
        self._config = config.model_copy(update={"timeout_seconds": effective_timeout})
        self.model = self._config.model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.retry_attempts = 2
        self.kwargs = {
            "model": self._config.model,
            "api_key": self._config.api_key,
            "base_url": self._config.base_url,
            "temperature": temperature,
            "timeout": int(self._config.timeout_seconds),
            "wire_api": self._config.wire_api,
            "provider_protocol": self._config.provider_protocol,
        }
        self._client = OpenAICompatibleClient(self._config)

    def invoke(self, messages: list[dict[str, Any]], **kwargs) -> HelloAgentsInvokeResult:
        temperature = float(kwargs.pop("temperature", self.temperature))
        max_tokens = kwargs.pop("max_tokens", self.max_tokens)
        last_error: httpx.HTTPError | None = None

        for attempt in range(1, self.retry_attempts + 1):
            started = time.perf_counter()
            try:
                content = self._client.create_chat_completion(
                    messages=deepcopy(messages),
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                latency_ms = int((time.perf_counter() - started) * 1000)
                return HelloAgentsInvokeResult(content=content, usage={}, latency_ms=latency_ms)
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt >= self.retry_attempts:
                    raise
                time.sleep(min(2.0 * attempt, 4.0))
            except httpx.TransportError as exc:
                last_error = exc
                if attempt >= self.retry_attempts:
                    raise
                time.sleep(min(2.0 * attempt, 4.0))

        assert last_error is not None
        raise last_error

    def stream_invoke(self, messages: list[dict[str, Any]], **kwargs):
        result = self.invoke(messages, **kwargs)
        yield result.content

    def invoke_with_tools(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], tool_choice: str | dict[str, Any] = "auto", **kwargs) -> Any:
        temperature = float(kwargs.pop("temperature", self.temperature))
        max_tokens = kwargs.pop("max_tokens", self.max_tokens)
        return self._client.create_tool_completion(
            messages=deepcopy(messages),
            tools=deepcopy(tools),
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
        )


class HelloAgentsOrchestrator(StubOrchestrator):
    def __init__(
        self,
        llm_config: LlmConfig | None,
        *,
        maps_provider: MapsPoiProvider | None = None,
        progress_callback: RoleProgressCallback | None = None,
    ) -> None:
        super().__init__(maps_provider=maps_provider)
        self._llm_config = llm_config
        self._progress_callback = progress_callback
        self._role_search_gateway_cache: dict[str, list[tuple[ConfiguredSearchGateway, set[str]]]] = {}
        self._current_xhs_source_enabled = False
        self._current_user_id: str | None = None
        self._current_search_service: SearchServiceConfig | None = None
        self._current_job_id: str | None = None
    def plan_trip(self, request: PlanningRequest) -> PlanningResult:
        self._role_search_gateway_cache = {}
        self._current_xhs_source_enabled = bool(getattr(request, "xhs_source_enabled", False))
        self._current_user_id = getattr(request, "user_id", None)
        self._current_search_service = getattr(request, "search_service", None) or SearchServiceConfig.from_env()
        try:
            self._log_event("helloagents_plan_trip_started", message="HelloAgents trip planning started.", destination=request.destination)
            payload, pipeline_notes, agent_runs, attraction, weather, weather_citations, weather_tool_results, grounding_documents, transport = self._run_helloagents_pipeline(request)
            result = self._build_result_from_payload(
                payload,
                request,
                pipeline_notes,
                agent_runs,
                attraction_grounding=attraction,
                weather_guidance=weather,
                weather_citations=weather_citations,
                weather_tool_results=weather_tool_results,
                grounding_documents=grounding_documents,
                transport_guidance=transport,
            )
            result.trace.provider = "helloagents-poc"
            result.trace.license_notice = _LICENSE_NOTICE
            self._log_event("helloagents_plan_trip_completed", message="HelloAgents trip planning completed.", day_count=len(result.days), risk_count=len(result.risks))
            return result
        finally:
            self._current_xhs_source_enabled = False
            self._current_user_id = None
            self._current_search_service = None

    def summarize_sources(self, destination: str, findings: list[str]) -> SourceSummary:
        return super().summarize_sources(destination, findings)

    def draft_export_payload(self, request: PlanningRequest, plan: PlanningResult) -> ExportDraft:
        draft = super().draft_export_payload(request, plan)
        draft.sections.append("Agent provider: helloagents-poc")
        return draft

    def _log_event(self, event: str, *, message: str, level: str = "INFO", **payload: Any) -> None:
        log_job_event(
            event,
            job_id=self._current_job_id,
            logger_name=__name__,
            level=level,
            message=message,
            **payload,
        )

    def _run_helloagents_pipeline(
        self,
        request: PlanningRequest,
    ) -> tuple[Any, list[str], list[AgentRunStep], HelloAgentsWeatherGuidance, list[str], dict[str, Any], list[dict[str, Any]], HelloAgentsTransportGuidance]:
        if self._llm_config is None:
            raise RuntimeError("HelloAgents requires configured LLM settings")

        module = import_module("hello_agents")
        trip_payload = self._build_trip_payload(request)
        role_configs = self._build_role_configs(request)
        role_llm_configs = self._build_role_llm_configs()
        agent_runs: list[AgentRunStep] = []

        brief_role = role_configs["brief_parser"]
        self._emit_role_progress(brief_role)
        brief_response = self._run_role(
            module=module,
            role_config=brief_role,
            llm_config=role_llm_configs[brief_role.role_name],
            input_payload={"trip_request": trip_payload},
        )
        brief = self._parse_structured_response(brief_response, HelloAgentsBrief)
        agent_runs.append(self._build_agent_run(brief_role, role_llm_configs[brief_role.role_name], self._summarize_brief(brief)))

        attraction_payload = self._build_attraction_research_payload(request, brief)
        weather_payload = self._build_weather_research_payload(request, brief)
        hotel_payload = self._build_hotel_research_payload(request, brief)
        transport_payload = self._build_transport_research_payload(request, brief)

        attraction_role = role_configs["attraction_specialist"]
        weather_role = role_configs["weather_specialist"]
        hotel_role = role_configs["hotel_specialist"]
        transport_role = role_configs["transport_specialist"]

        for role in (attraction_role, weather_role, hotel_role, transport_role):
            self._emit_role_progress(role)

        self._log_event(
            "helloagents_specialists_parallel_started",
            message="Running specialist roles in parallel.",
            roles=list(_SPECIALIST_PARALLEL_ROLES),
        )
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="helloagents-specialists") as executor:
            futures = {
                "attraction_specialist": executor.submit(
                    self._run_role,
                    module=module,
                    role_config=attraction_role,
                    llm_config=role_llm_configs[attraction_role.role_name],
                    input_payload=attraction_payload,
                ),
                "weather_specialist": executor.submit(
                    self._run_role,
                    module=module,
                    role_config=weather_role,
                    llm_config=role_llm_configs[weather_role.role_name],
                    input_payload=weather_payload,
                ),
                "hotel_specialist": executor.submit(
                    self._run_role,
                    module=module,
                    role_config=hotel_role,
                    llm_config=role_llm_configs[hotel_role.role_name],
                    input_payload=hotel_payload,
                ),
                "transport_specialist": executor.submit(
                    self._run_role,
                    module=module,
                    role_config=transport_role,
                    llm_config=role_llm_configs[transport_role.role_name],
                    input_payload=transport_payload,
                ),
            }

            attraction = self._parse_structured_response(futures["attraction_specialist"].result(), HelloAgentsAttractionGrounding)
            weather = self._parse_structured_response(futures["weather_specialist"].result(), HelloAgentsWeatherGuidance)
            weather_language_warning = self._weather_guidance_needs_language_repair(weather, request)
            hotel = self._parse_structured_response(futures["hotel_specialist"].result(), HelloAgentsHotelRecommendation)
            transport = self._parse_structured_response(futures["transport_specialist"].result(), HelloAgentsTransportGuidance)
        self._log_event("helloagents_specialists_parallel_completed", message="Specialist roles completed.")

        attraction_tool_results = attraction_payload.get("tool_results") if isinstance(attraction_payload.get("tool_results"), dict) else {}
        weather_tool_results = weather_payload.get("tool_results") if isinstance(weather_payload.get("tool_results"), dict) else {}
        hotel_tool_results = hotel_payload.get("tool_results") if isinstance(hotel_payload.get("tool_results"), dict) else {}
        transport_tool_results = transport_payload.get("tool_results") if isinstance(transport_payload.get("tool_results"), dict) else {}
        attraction_citations = self._extract_urls_from_search_result(attraction_tool_results)
        weather_citations = [str(item).strip() for item in weather_tool_results.get("citations", []) if str(item).strip()]
        hotel_citations = self._extract_urls_from_search_result(hotel_tool_results)
        transport_citations = [str(item).strip() for item in transport_tool_results.get("citations", []) if str(item).strip()]
        if not transport_citations:
            transport_citations = self._extract_urls_from_search_result(transport_tool_results)
        grounding_documents = self._merge_grounding_documents(
            attraction_tool_results.get("grounding_docs"),
            hotel_tool_results.get("grounding_docs"),
            transport_tool_results.get("grounding_docs"),
        )

        agent_runs.append(
            self._build_agent_run(
                attraction_role,
                role_llm_configs[attraction_role.role_name],
                self._summarize_attractions(attraction),
                extra_citations=attraction_citations,
            )
        )
        agent_runs.append(
            self._build_agent_run(
                weather_role,
                role_llm_configs[weather_role.role_name],
                self._summarize_weather(weather),
                extra_citations=weather_citations,
            )
        )
        agent_runs.append(
            self._build_agent_run(
                hotel_role,
                role_llm_configs[hotel_role.role_name],
                self._summarize_hotels(hotel),
                extra_citations=hotel_citations,
            )
        )
        agent_runs.append(
            self._build_agent_run(
                transport_role,
                role_llm_configs[transport_role.role_name],
                self._summarize_transport(transport),
                extra_citations=transport_citations,
            )
        )
        planner_role = role_configs["itinerary_planner"]
        self._emit_role_progress(planner_role)
        planner_attractions = self._build_planner_attractions_payload(attraction)
        planner_weather = self._build_planner_weather_payload(weather, expected_days=max(1, (request.end_date - request.start_date).days + 1))
        planner_hotels = self._build_planner_hotels_payload(hotel)
        planner_transport = self._build_planner_transport_payload(transport)
        self._log_event(
            "helloagents_planner_payload_ready",
            message="Planner payload assembled.",
            payload_keys=["trip_request", "planning_brief", "attractions", "weather", "hotels", "transport", "output_schema"],
            planner_payload_bytes=len(
                json.dumps(
                    {
                        "trip_request": trip_payload,
                        "planning_brief": brief.model_dump(mode="json"),
                        "attractions": planner_attractions,
                        "weather": planner_weather,
                        "hotels": planner_hotels,
                        "transport": planner_transport,
                        "output_schema": PLANNING_OUTPUT_SCHEMA,
                    },
                    ensure_ascii=False,
                )
            ),
        )
        planner_response = self._run_role(
            module=module,
            role_config=planner_role,
            llm_config=role_llm_configs[planner_role.role_name],
            input_payload={
                "trip_request": trip_payload,
                "planning_brief": brief.model_dump(mode="json"),
                "attractions": planner_attractions,
                "weather": planner_weather,
                "hotels": planner_hotels,
                "transport": planner_transport,
                "output_schema": PLANNING_OUTPUT_SCHEMA,
            },
        )
        self._log_event("helloagents_planner_response_received", message="Planner response received.", response_chars=len(planner_response))
        final_payload = parse_planning_response(planner_response)
        self._log_event("helloagents_planner_response_parsed", message="Planner response parsed into structured payload.", day_count=len(final_payload.days))
        repair_needed = planning_payload_needs_language_repair(final_payload, request)
        agent_runs.append(self._build_agent_run(planner_role, role_llm_configs[planner_role.role_name], self._summarize_itinerary(final_payload.summary, final_payload.days, final_payload.risks)))

        role_model_summary = ", ".join(f"{role_name}={role_llm_configs[role_name].model}" for role_name in _ROLE_SEQUENCE)
        role_endpoint_summary = ", ".join(
            f"{role_name}@{self._describe_endpoint(role_llm_configs[role_name])}" for role_name in _ROLE_SEQUENCE
        )
        pipeline_notes = [
            "Generated the itinerary with HelloAgents business-specialist multi-agent pipeline.",
            "Roles executed: brief_parser -> (attraction_specialist || weather_specialist || hotel_specialist || transport_specialist) -> itinerary_planner.",
            f"Role models: {role_model_summary}.",
            f"Role endpoints: {role_endpoint_summary}.",
            "Weather guidance is currently planning-oriented model output, not a live forecast feed.",
            "Hotel recommendations currently use the configured maps provider plus model synthesis, not a dedicated booking inventory API.",
            "Transport guidance uses the configured search provider to ground transfer, fare, and sequencing assumptions before final planning.",
            "Executed through the HelloAgents PoC adapter boundary with third-party-only role execution.",
        ]
        if weather_language_warning:
            warning = "Weather specialist output did not fully match the requested locale; returning the original specialist output without localization repair."
            self._log_event(
                "helloagents_weather_language_warning",
                message=warning,
                level="WARNING",
                role="weather_specialist",
            )
            pipeline_notes.append(warning)
        if repair_needed:
            warning = "Itinerary planner output did not fully match the requested locale; returning the original planner output without localization repair."
            self._log_event(
                "helloagents_planner_language_warning",
                message=warning,
                level="WARNING",
                role="itinerary_planner",
                response_chars=len(planner_response),
            )
            pipeline_notes.append(warning)
        return final_payload, pipeline_notes, agent_runs, attraction, weather, weather_citations, weather_tool_results, grounding_documents, transport

    def _build_trip_payload(self, request: PlanningRequest) -> dict[str, Any]:
        return {
            "trip_id": request.trip_id,
            "title": request.title,
            "origin": request.origin,
            "destination": request.destination,
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
            "trip_days": max(1, (request.end_date - request.start_date).days + 1),
            "budget": request.budget,
            "travelers": request.travelers,
            "interests": request.interests,
            "accommodation_preference": request.accommodation_preference,
            "pace": request.pace,
            "transport_mode": request.transport_mode,
        }

    def _build_role_llm_configs(self) -> dict[str, LlmEndpointConfig]:
        assert self._llm_config is not None
        return {role_name: self._llm_config.config_for_role(role_name) for role_name in _ROLE_SEQUENCE}

    def _build_role_configs(self, request: PlanningRequest) -> dict[str, HelloAgentsRoleConfig]:
        planner_messages = build_planning_messages(request)
        planner_system_prompt = next((message["content"] for message in planner_messages if message.get("role") == "system"), "")
        brief_prompt = build_brief_parser_prompt()
        attraction_prompt = build_attraction_specialist_prompt()
        weather_prompt = build_weather_specialist_prompt()
        hotel_prompt = build_hotel_specialist_prompt()
        transport_prompt = build_transport_specialist_prompt()
        planner_prompt = build_itinerary_planner_prompt(planner_system_prompt)
        output_locale = infer_output_locale(request)
        language_instruction = build_output_language_instruction(output_locale)
        locale_clause = f" Target output locale: {output_locale}."
        return {
            # brief_parser:
            # 中文注释：先把原始 trip request 压缩成结构化 brief，避免后续角色直接面对松散输入。
            "brief_parser": HelloAgentsRoleConfig(
                role_name="brief_parser",
                title="Brief parser",
                description="Compresses the trip input into a compact planning brief.",
                prompt_focus="Extract constraints and preferences into JSON only. Do not draft the itinerary.",
                agent_class_name="SimpleAgent",
                system_prompt=f"{brief_prompt.system_prompt} {language_instruction}{locale_clause}",
                prompt_version=brief_prompt.version,
                progress_percent=24,
            ),
            # attraction_specialist:
            # 中文注释：负责景点 grounding，把候选区域、POI 和串联建议结构化输出。
            "attraction_specialist": HelloAgentsRoleConfig(
                role_name="attraction_specialist",
                title="Attraction specialist",
                description="Builds candidate areas, featured POIs, and visit sequencing suggestions.",
                prompt_focus="Use MCP tool results plus the trip brief and attraction candidates to return attraction grounding JSON only.",
                agent_class_name="SimpleAgent",
                system_prompt=f"{attraction_prompt.system_prompt} {language_instruction}{locale_clause}",
                prompt_version=attraction_prompt.version,
                progress_percent=40,
            ),
            # weather_specialist:
            # 中文注释：负责天气 planning guidance，强调季节性和可执行建议，不伪装成实时预报。
            "weather_specialist": HelloAgentsRoleConfig(
                role_name="weather_specialist",
                title="Weather specialist",
                description="Produces planning-oriented weather guidance, timing advice, and packing notes.",
                prompt_focus="Use MCP tool results to gather weather-oriented web context, then return weather guidance JSON only.",
                agent_class_name="SimpleAgent",
                system_prompt=f"{weather_prompt.system_prompt} {language_instruction}{locale_clause}",
                prompt_version=weather_prompt.version,
                progress_percent=48,
            ),
            # hotel_specialist:
            # 中文注释：负责住宿区域与候选酒店建议，目标是降低转场成本并匹配预算。
            "hotel_specialist": HelloAgentsRoleConfig(
                role_name="hotel_specialist",
                title="Hotel specialist",
                description="Recommends stay areas and candidate hotels aligned with transit, budget, and pace.",
                prompt_focus="Use MCP tool results plus the stay preference, budget, and candidate hotel context to return hotel recommendation JSON only.",
                agent_class_name="SimpleAgent",
                system_prompt=f"{hotel_prompt.system_prompt} {language_instruction}{locale_clause}",
                prompt_version=hotel_prompt.version,
                progress_percent=56,
            ),
            # transport_specialist:
            # 中文注释：负责交通票价、换乘约束和到离程策略，把交通价格与时效从最终 planner 里拆出来单独 grounding。
            "transport_specialist": HelloAgentsRoleConfig(
                role_name="transport_specialist",
                title="Transport specialist",
                description="Builds grounded transport options, pricing constraints, and transfer strategy.",
                prompt_focus="Use MCP tool results plus the trip brief to return transport guidance JSON only, including grounded cost estimates.",
                agent_class_name="SimpleAgent",
                system_prompt=f"{transport_prompt.system_prompt} {language_instruction}{locale_clause}",
                prompt_version=transport_prompt.version,
                progress_percent=64,
            ),
            # itinerary_planner:
            # 中文注释：最终总控角色，复用主 planner prompt，再消费四份结构化中间结果生成最终 itinerary。
            "itinerary_planner": HelloAgentsRoleConfig(
                role_name="itinerary_planner",
                title="Itinerary planner",
                description="Combines attractions, weather, hotel strategy, and booking constraints into the final itinerary draft.",
                prompt_focus="Return the final itinerary JSON using the brief, attraction package, weather guidance, hotel strategy, and transport guidance.",
                agent_class_name="SimpleAgent",
                system_prompt=f"{planner_prompt.system_prompt} {language_instruction}{locale_clause}",
                prompt_version=planner_prompt.version,
                progress_percent=78,
            ),
        }

    def _emit_role_progress(self, role_config: HelloAgentsRoleConfig) -> None:
        if self._progress_callback is None:
            return
        self._progress_callback(role_config.role_name, role_config.title, role_config.description, role_config.progress_percent)

    def _describe_endpoint(self, llm_config: LlmEndpointConfig) -> str:
        return urlparse(llm_config.base_url).netloc or llm_config.base_url

    def _build_agent_run(
        self,
        role_config: HelloAgentsRoleConfig,
        llm_config: LlmEndpointConfig,
        output_summary: str,
        *,
        extra_notes: list[str] | None = None,
        extra_citations: list[str] | None = None,
    ) -> AgentRunStep:
        notes = [
            f"Third-party endpoint: {self._describe_endpoint(llm_config)}.",
            f"Wire API: {llm_config.wire_api}.",
        ]
        if extra_notes:
            notes.extend(extra_notes)
        citations = [str(citation).strip() for citation in (extra_citations or []) if str(citation).strip()]
        return AgentRunStep(
            key=role_config.role_name,
            title=role_config.title,
            description=role_config.description,
            prompt_focus=role_config.prompt_focus,
            output_summary=output_summary,
            prompt_version=role_config.prompt_version,
            status="completed",
            model=llm_config.model,
            notes=notes,
            citations=citations,
        )

    def _run_role(
        self,
        *,
        module: Any,
        role_config: HelloAgentsRoleConfig,
        llm_config: LlmEndpointConfig,
        input_payload: dict[str, Any],
    ) -> str:
        agent_class = getattr(module, role_config.agent_class_name, None)
        if agent_class is None:
            raise RuntimeError(f"hello_agents does not expose {role_config.agent_class_name}")

        llm = HelloAgentsCompatibleLLM(
            llm_config,
            temperature=role_config.temperature,
        )
        enriched_payload = self._augment_payload_with_tool_results(role_config.role_name, input_payload)
        prompt_payload = self._build_role_prompt_payload(enriched_payload)
        agent = agent_class(
            name=role_config.role_name,
            llm=llm,
            system_prompt=role_config.system_prompt,
            enable_tool_calling=False,
        )
        started = time.perf_counter()
        self._log_event(
            "helloagents_role_started",
            message=f"Role {role_config.role_name} started.",
            role=role_config.role_name,
            endpoint=self._describe_endpoint(llm_config),
            model=llm_config.model,
            payload_keys=sorted(prompt_payload.keys()),
        )
        try:
            response = agent.run(json.dumps(prompt_payload, ensure_ascii=False))
        except Exception as exc:
            endpoint = self._describe_endpoint(llm_config)
            elapsed_seconds = max(time.perf_counter() - started, 0.0)
            raw_reason = str(exc).strip() or exc.__class__.__name__
            if isinstance(exc, httpx.TimeoutException) or "timed out" in raw_reason.lower() or "timeout" in raw_reason.lower():
                reason = f"timed out after {elapsed_seconds:.1f}s"
            else:
                reason = raw_reason
            self._log_event(
                "helloagents_role_failed",
                message=f"Role {role_config.role_name} failed.",
                level="ERROR",
                role=role_config.role_name,
                endpoint=endpoint,
                model=llm_config.model,
                elapsed_seconds=round(elapsed_seconds, 3),
                reason=reason,
            )
            raise RuntimeError(
                f"HelloAgents role '{role_config.role_name}' failed via third-party endpoint {endpoint} after {elapsed_seconds:.1f}s: {reason}"
            ) from exc

        content = self._coerce_text(response)
        if not content.strip():
            endpoint = self._describe_endpoint(llm_config)
            raise RuntimeError(
                f"HelloAgents role '{role_config.role_name}' returned an empty response from third-party endpoint {endpoint}"
            )
        self._log_event(
            "helloagents_role_completed",
            message=f"Role {role_config.role_name} completed.",
            role=role_config.role_name,
            endpoint=self._describe_endpoint(llm_config),
            model=llm_config.model,
            elapsed_seconds=round(max(time.perf_counter() - started, 0.0), 3),
            response_chars=len(content),
        )
        return content

    def _build_role_prompt_payload(self, enriched_payload: dict[str, Any]) -> dict[str, Any]:
        prompt_payload = deepcopy(enriched_payload)
        tool_results = prompt_payload.get("tool_results")
        if isinstance(tool_results, dict):
            prompt_payload["tool_results"] = self._strip_tool_url_metadata(tool_results)
        return prompt_payload

    def _strip_tool_url_metadata(self, value: Any) -> Any:
        if isinstance(value, dict):
            stripped: dict[str, Any] = {}
            for key, item in value.items():
                normalized_key = str(key).strip().lower()
                if normalized_key in _TOOL_RESULT_URL_METADATA_KEYS:
                    continue
                stripped[key] = self._strip_tool_url_metadata(item)
            return stripped
        if isinstance(value, list):
            return [self._strip_tool_url_metadata(item) for item in value]
        if isinstance(value, str):
            return re.sub(r"https?://[^\s<>'\"\]]+", "[link omitted]", value)
        return value

    def _build_attraction_research_payload(self, request: PlanningRequest, brief: HelloAgentsBrief) -> dict[str, Any]:
        queries = [*brief.interests, *brief.must_have, request.destination, "local highlights"]
        return {
            "trip_request": self._build_trip_payload(request),
            "planning_brief": brief.model_dump(mode="json"),
            "candidate_attractions": self._collect_poi_candidates(request, queries, limit=8),
        }

    def _build_weather_research_payload(self, request: PlanningRequest, brief: HelloAgentsBrief) -> dict[str, Any]:
        trip_days = max(1, (request.end_date - request.start_date).days + 1)
        return {
            "trip_request": self._build_trip_payload(request),
            "planning_brief": brief.model_dump(mode="json"),
            "season_context": {
                "month": request.start_date.month,
                "season": self._season_for_month(request.start_date.month),
                "days": trip_days,
                "destination": request.destination,
                "weather_focus": self._weather_focus_for_month(request.start_date.month),
            },
        }

    def _build_hotel_research_payload(self, request: PlanningRequest, brief: HelloAgentsBrief) -> dict[str, Any]:
        queries = [brief.accommodation, request.accommodation_preference, f"{request.destination} hotel", "hotel", "stay"]
        return {
            "trip_request": self._build_trip_payload(request),
            "planning_brief": brief.model_dump(mode="json"),
            "candidate_hotels": self._collect_hotel_candidates(request, queries, limit=6),
        }

    def _build_transport_research_payload(self, request: PlanningRequest, brief: HelloAgentsBrief) -> dict[str, Any]:
        return {
            "trip_request": self._build_trip_payload(request),
            "planning_brief": brief.model_dump(mode="json"),
            "transport_context": {
                "origin": request.origin,
                "destination": request.destination,
                "start_date": request.start_date.isoformat(),
                "end_date": request.end_date.isoformat(),
                "trip_days": max(1, (request.end_date - request.start_date).days + 1),
                "transport_mode": request.transport_mode,
                "travelers": request.travelers,
                "pace": request.pace,
            },
        }

    def _build_planner_attractions_payload(self, attraction: HelloAgentsAttractionGrounding) -> dict[str, Any]:
        return {
            "candidate_areas": [str(area).strip() for area in attraction.candidate_areas if str(area).strip()][:4],
            "featured_pois": [
                {
                    "name": poi.name,
                    "area": poi.area,
                    "reason": poi.reason,
                    "suggested_time": poi.suggested_time,
                }
                for poi in attraction.featured_pois[:6]
            ],
            "sequencing_hints": [str(item).strip() for item in attraction.sequencing_hints if str(item).strip()][:5],
            "attraction_risks": [str(item).strip() for item in attraction.attraction_risks if str(item).strip()][:4],
            "summary": self._compress_notes(
                [
                    *[f"Area: {area}" for area in attraction.candidate_areas[:3]],
                    *attraction.sequencing_hints[:3],
                    *attraction.crowd_notes[:2],
                ],
                limit=3,
            ),
        }

    def _build_planner_weather_payload(self, weather: HelloAgentsWeatherGuidance, *, expected_days: int) -> dict[str, Any]:
        return {
            "overall_outlook": weather.overall_outlook,
            "daily_outlook": [str(item).strip() for item in weather.daily_outlook if str(item).strip()][:expected_days],
            "packing_notes": [str(item).strip() for item in weather.packing_notes if str(item).strip()][:5],
            "timing_guidance": [str(item).strip() for item in weather.timing_guidance if str(item).strip()][:5],
            "weather_risks": [str(item).strip() for item in weather.weather_risks if str(item).strip()][:4],
        }

    def _build_planner_hotels_payload(self, hotel: HelloAgentsHotelRecommendation) -> dict[str, Any]:
        final_hotel = hotel.final_recommended_hotel or (hotel.hotel_candidates[0] if hotel.hotel_candidates else None)
        return {
            "recommended_areas": [str(area).strip() for area in hotel.recommended_areas if str(area).strip()][:3],
            "final_recommended_hotel": self._hotel_candidate_to_planner_dict(final_hotel) if final_hotel is not None else None,
            "hotel_candidates": [
                self._hotel_candidate_to_planner_dict(candidate)
                for candidate in hotel.hotel_candidates[:4]
            ],
            "stay_strategy": [str(item).strip() for item in hotel.stay_strategy if str(item).strip()][:4],
            "budget_notes": [str(item).strip() for item in hotel.budget_notes if str(item).strip()][:4],
            "price_timeliness_notes": [str(item).strip() for item in hotel.price_timeliness_notes if str(item).strip()][:4],
            "review_notes": [str(item).strip() for item in hotel.review_notes if str(item).strip()][:4],
            "preference_match_notes": [str(item).strip() for item in hotel.preference_match_notes if str(item).strip()][:4],
            "hotel_risks": [str(item).strip() for item in hotel.hotel_risks if str(item).strip()][:4],
            "summary": self._compress_notes(
                [
                    *([f"Final hotel: {final_hotel.name} ({final_hotel.area})"] if final_hotel is not None else []),
                    *[f"Stay area: {area}" for area in hotel.recommended_areas[:2]],
                    *hotel.stay_strategy[:2],
                    *hotel.budget_notes[:2],
                    *hotel.review_notes[:2],
                ],
                limit=3,
            ),
        }

    def _hotel_candidate_to_planner_dict(self, candidate: HelloAgentsHotelCandidate) -> dict[str, Any]:
        return {
            "name": candidate.name,
            "area": candidate.area,
            "hotel_type": candidate.hotel_type,
            "reason": candidate.reason,
            "price_hint": candidate.price_hint,
            "price_checked_at": candidate.price_checked_at,
            "price_valid_for": candidate.price_valid_for,
            "review_score": candidate.review_score,
            "review_count": candidate.review_count,
            "review_summary": candidate.review_summary,
            "preference_match": candidate.preference_match,
            "booking_confidence": candidate.booking_confidence,
            "caveats": [str(item).strip() for item in candidate.caveats if str(item).strip()][:4],
        }

    def _build_planner_transport_payload(self, transport: HelloAgentsTransportGuidance) -> dict[str, Any]:
        return {
            "intercity_options": [
                {
                    "mode": option.mode,
                    "route": option.route,
                    "duration_hint": option.duration_hint,
                    "price_hint": option.price_hint,
                    "booking_window": option.booking_window,
                    "reason": option.reason,
                }
                for option in transport.intercity_options[:3]
            ],
            "arrival_strategy": [str(item).strip() for item in transport.arrival_strategy if str(item).strip()][:4],
            "local_mobility_strategy": [str(item).strip() for item in transport.local_mobility_strategy if str(item).strip()][:4],
            "pass_or_ticket_notes": [str(item).strip() for item in transport.pass_or_ticket_notes if str(item).strip()][:4],
            "transport_risks": [str(item).strip() for item in transport.transport_risks if str(item).strip()][:4],
            "sequencing_constraints": [str(item).strip() for item in transport.sequencing_constraints if str(item).strip()][:4],
            "estimated_intercity_cost": transport.estimated_intercity_cost,
            "estimated_local_transport_cost": transport.estimated_local_transport_cost,
            "summary": self._compress_notes(
                [
                    *transport.arrival_strategy[:2],
                    *transport.local_mobility_strategy[:2],
                    *transport.pass_or_ticket_notes[:2],
                    *transport.sequencing_constraints[:2],
                ],
                limit=4,
            ),
        }

    def _compress_notes(self, values: list[str], *, limit: int) -> list[str]:
        compressed: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = str(value or "").strip()
            if not normalized:
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            compressed.append(normalized)
            if len(compressed) >= limit:
                break
        return compressed


    def _build_role_mcp_clients(self, role_name: str) -> list[tuple[ConfiguredSearchGateway, set[str]]]:
        if role_name not in set(_SPECIALIST_PARALLEL_ROLES):
            return []
        cached = self._role_search_gateway_cache.get(role_name)
        if cached is not None:
            return cached
        configs = self._resolve_role_search_configs()
        resolved_clients: list[tuple[ConfiguredSearchGateway, set[str]]] = []
        for config in configs:
            client = ConfiguredSearchGateway(config)
            try:
                available_tools = client.available_tools()
            except Exception as exc:
                _LOGGER.warning("HelloAgents role=%s provider=%s unable_to_list_tools=%s", role_name, config.provider, exc)
                continue
            _LOGGER.debug("HelloAgents role=%s provider=%s available_tools=%s", role_name, config.provider, sorted(available_tools))
            resolved_clients.append((client, available_tools))
        self._role_search_gateway_cache[role_name] = resolved_clients
        return resolved_clients

    # Backward-compatible shim for tests and legacy internal call sites that expect
    # a single search client instead of a provider chain.
    def _build_role_mcp_client(self, role_name: str) -> ConfiguredSearchGateway | None:
        clients = self._build_role_mcp_clients(role_name)
        return clients[0][0] if clients else None

    # Backward-compatible shim paired with _build_role_mcp_client.
    def _available_mcp_tools(self, role_name: str, client: ConfiguredSearchGateway) -> set[str]:
        del role_name
        return client.available_tools()

    def _resolve_role_search_configs(self) -> list[SearchServiceConfig]:
        configs: list[SearchServiceConfig] = []
        seen: set[tuple[str, str, str, str]] = set()

        def append(config: SearchServiceConfig | None) -> None:
            if config is None:
                return
            identity = (config.provider, config.transport, config.base_url, config.api_key)
            if identity in seen:
                return
            seen.add(identity)
            configs.append(config)

        primary = self._current_search_service
        append(primary)
        return configs

    def _pick_mcp_tool(self, available_tools: set[str], *candidates: str) -> str | None:
        for candidate in candidates:
            if candidate in available_tools:
                return candidate
        return None

    def _search_provider(self, client: ConfiguredSearchGateway) -> str:
        config = getattr(client, "config", None)
        provider = getattr(config, "provider", None)
        normalized = str(provider or "").strip().lower()
        return normalized

    def _is_groksearch_provider(self, client: ConfiguredSearchGateway) -> bool:
        return self._search_provider(client) == "groksearch"

    def _pick_search_tool(self, client: ConfiguredSearchGateway, available_tools: set[str], *, allow_answer: bool = False) -> str | None:
        if self._is_groksearch_provider(client):
            candidates = ("web_search", "answer", "search") if allow_answer else ("web_search",)
            return self._pick_mcp_tool(available_tools, *candidates)
        candidates = ("search", "answer") if allow_answer else ("search",)
        return self._pick_mcp_tool(available_tools, *candidates)

    def _pick_fetch_tool(self, client: ConfiguredSearchGateway, available_tools: set[str]) -> str | None:
        if self._is_groksearch_provider(client):
            return self._pick_mcp_tool(available_tools, "web_fetch", "contents")
        return self._pick_mcp_tool(available_tools, "contents", "web_fetch")

    def _augment_payload_with_tool_results(self, role_name: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        clients = self._build_role_mcp_clients(role_name)
        if not clients:
            return input_payload
        started = time.perf_counter()
        tool_results: dict[str, Any] = {}
        last_error: Exception | None = None
        for client, available_tools in clients:
            try:
                tool_results = self._collect_role_tool_results(role_name, client, available_tools, input_payload)
            except Exception as exc:
                last_error = exc
                _LOGGER.warning("HelloAgents role=%s provider=%s tool_collection_failed=%s", role_name, self._search_provider(client), exc)
                continue
            if tool_results:
                if self._search_provider(client) != self._search_provider(clients[0][0]):
                    self._log_event(
                        "helloagents_tool_collection_fallback_succeeded",
                        message=f"Tool collection fallback succeeded for {role_name}.",
                        role=role_name,
                        provider=self._search_provider(client),
                    )
                break
        if not tool_results and last_error is not None:
            self._log_event(
                "helloagents_tool_collection_failed",
                message=f"Tool collection failed for {role_name}.",
                level="ERROR",
                role=role_name,
                elapsed_seconds=round(max(time.perf_counter() - started, 0.0), 3),
                error=str(last_error).strip() or last_error.__class__.__name__,
            )
            _LOGGER.warning("HelloAgents role=%s tool_collection_failed=%s", role_name, last_error)
            return input_payload
        self._log_event(
            "helloagents_tool_collection_completed",
            message=f"Tool collection completed for {role_name}.",
            role=role_name,
            elapsed_seconds=round(max(time.perf_counter() - started, 0.0), 3),
            tool_result_keys=sorted(tool_results.keys()) if isinstance(tool_results, dict) else [],
        )
        if not tool_results:
            return input_payload
        input_payload["tool_results"] = tool_results
        return input_payload

    def _collect_role_tool_results(self, role_name: str, client: ConfiguredSearchGateway, available_tools: set[str], input_payload: dict[str, Any]) -> dict[str, Any]:
        if role_name == "attraction_specialist":
            return self._collect_attraction_tool_results(client, available_tools, input_payload)
        if role_name == "weather_specialist":
            return self._collect_weather_tool_results(client, available_tools, input_payload)
        if role_name == "hotel_specialist":
            return self._collect_hotel_tool_results(client, available_tools, input_payload)
        if role_name == "transport_specialist":
            return self._collect_transport_tool_results(client, available_tools, input_payload)
        return {}

    def _collect_grounding_docs(
        self,
        query: str,
        destination: str,
        *,
        interests: list[str],
        social_context: str,
        xhs_source_enabled: bool | None = None,
        include_remote_search: bool = False,
    ) -> list[dict[str, Any]]:
        if not destination:
            return []
        search_kwargs = {
            "interests": interests,
            "social_context": social_context,
            "xhs_source_enabled": bool(getattr(self, "_current_xhs_source_enabled", False))
            if xhs_source_enabled is None
            else bool(xhs_source_enabled),
            "xhs_user_id": getattr(self, "_current_user_id", None),
        }
        if include_remote_search:
            search_kwargs["search_service_configs"] = self._resolve_role_search_configs()
        documents = search_documents(
            query,
            destination,
            [],
            **search_kwargs,
        )
        return [doc.model_dump(mode="json") for doc in documents[:8]]

    def _collect_attraction_tool_results(self, client: ConfiguredSearchGateway, available_tools: set[str], input_payload: dict[str, Any]) -> dict[str, Any]:
        trip_request = input_payload.get("trip_request") if isinstance(input_payload.get("trip_request"), dict) else {}
        brief = input_payload.get("planning_brief") if isinstance(input_payload.get("planning_brief"), dict) else {}
        destination = str(trip_request.get("destination") or brief.get("destination") or "").strip()
        interests = [str(item).strip() for item in brief.get("must_have", []) if str(item).strip()] or [str(item).strip() for item in brief.get("interests", []) if str(item).strip()]
        pace = str(trip_request.get("pace") or brief.get("pace") or "").strip()
        query = (
            f"Travel guide for {destination} attractions focused on "
            f"{', '.join(interests[:3]) or 'local highlights'}, suitable for a {pace or 'balanced'} itinerary"
        ).strip()
        search_tool = self._pick_search_tool(client, available_tools)
        if search_tool is None:
            return {}
        try:
            search_result = self._call_search_like_tool(client, search_tool, query, 6, role_name="attraction_specialist")
        except Exception as exc:
            _LOGGER.warning("HelloAgents role=attraction_specialist tool=%s failed=%s", search_tool, exc)
            return {}
        payload = {"search_tool": search_tool, "search": search_result}

        fetch_tool = self._pick_fetch_tool(client, available_tools)
        if fetch_tool is not None:
            crawl_urls = self._extract_urls_from_search_result(search_result)[:3]
            if crawl_urls:
                payload["crawl_tool"] = fetch_tool
                payload["crawl_urls"] = crawl_urls
                try:
                    payload["crawl"] = self._call_crawling_tool(client, fetch_tool, crawl_urls, role_name="attraction_specialist")
                except Exception as exc:
                    _LOGGER.warning("HelloAgents role=attraction_specialist tool=%s failed=%s", fetch_tool, exc)

        try:
            grounding_docs = self._collect_grounding_docs(query, destination, interests=interests, social_context="attraction")
        except Exception as exc:
            _LOGGER.warning("HelloAgents role=attraction_specialist grounding_failed=%s", exc)
        else:
            if grounding_docs:
                payload["grounding_docs"] = grounding_docs
        return payload

    def _collect_weather_tool_results(self, client: ConfiguredSearchGateway, available_tools: set[str], input_payload: dict[str, Any]) -> dict[str, Any]:
        trip_request = input_payload.get("trip_request") if isinstance(input_payload.get("trip_request"), dict) else {}
        destination = str(trip_request.get("destination") or "").strip()
        start_date = str(trip_request.get("start_date") or "").strip()
        end_date = str(trip_request.get("end_date") or "").strip()
        search_query = (
            f"Travel weather guidance for {destination} between {start_date} and {end_date}, "
            "including expected temperatures, rain risk, and packing advice"
        ).strip()
        research_instructions = (
            f"Provide planning-oriented weather guidance for travel in {destination} from {start_date} to {end_date}. "
            "Summarize likely temperature patterns, rain or storm risk, daylight or timing considerations, "
            "and practical packing advice for itinerary planning. Include source-backed detail."
        ).strip()

        if self._is_groksearch_provider(client):
            search_tool = self._pick_search_tool(client, available_tools, allow_answer=True)
            if search_tool is None:
                return {}
            try:
                search_result = self._call_search_like_tool(client, search_tool, search_query, 5, role_name="weather_specialist")
            except Exception as exc:
                _LOGGER.warning("HelloAgents role=weather_specialist tool=%s failed=%s", search_tool, exc)
                return {}
            return {
                "research_tool": search_tool,
                "search": search_result,
                "citations": self._extract_urls_from_search_result(search_result),
            }

        research_tool = self._pick_mcp_tool(available_tools, "deep_researcher_start", "research")
        if research_tool is not None:
            try:
                research_result = self._call_research_like_tool(client, research_tool, available_tools, research_instructions, role_name="weather_specialist")
            except Exception as exc:
                _LOGGER.warning("HelloAgents role=weather_specialist tool=%s failed=%s", research_tool, exc)
            else:
                citations = self._extract_urls_from_search_result(research_result)
                payload = {
                    "research_tool": research_tool,
                    "research": research_result,
                    "citations": citations,
                }
                if self._research_status(research_result) not in {"completed", "complete", "done"}:
                    fallback_tool = self._pick_mcp_tool(available_tools, "answer", "search")
                    if fallback_tool is not None:
                        try:
                            fallback_result = self._call_search_like_tool(client, fallback_tool, search_query, 5, role_name="weather_specialist")
                        except Exception as exc:
                            _LOGGER.warning("HelloAgents role=weather_specialist tool=%s failed=%s", fallback_tool, exc)
                        else:
                            payload["fallback_search_tool"] = fallback_tool
                            payload["fallback_search"] = fallback_result
                            payload["citations"] = list(dict.fromkeys([*citations, *self._extract_urls_from_search_result(fallback_result)]))
                return payload

        answer_tool = self._pick_mcp_tool(available_tools, "answer", "search")
        if answer_tool is None:
            return {}
        try:
            answer_result = self._call_search_like_tool(client, answer_tool, search_query, 5, role_name="weather_specialist")
        except Exception as exc:
            _LOGGER.warning("HelloAgents role=weather_specialist tool=%s failed=%s", answer_tool, exc)
            return {}
        return {"research_tool": answer_tool, "answer": answer_result, "citations": self._extract_urls_from_search_result(answer_result)}

    def _collect_hotel_tool_results(self, client: ConfiguredSearchGateway, available_tools: set[str], input_payload: dict[str, Any]) -> dict[str, Any]:
        trip_request = input_payload.get("trip_request") if isinstance(input_payload.get("trip_request"), dict) else {}
        brief = input_payload.get("planning_brief") if isinstance(input_payload.get("planning_brief"), dict) else {}
        candidate_hotels = input_payload.get("candidate_hotels") if isinstance(input_payload.get("candidate_hotels"), list) else []
        destination = str(trip_request.get("destination") or brief.get("destination") or "").strip()
        stay_pref = str(trip_request.get("accommodation_preference") or brief.get("accommodation") or "").strip()
        candidate_names = [
            str(item.get("name") or "").strip()
            for item in candidate_hotels
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        query = (
            f"Travel planning pages about staying in {destination} with a preference for {stay_pref or 'well-located hotels'}, "
            f"focusing on transit-friendly areas and hotels such as {', '.join(candidate_names[:2]) or 'well-reviewed stays'}"
        ).strip()
        search_tool = self._pick_search_tool(client, available_tools)
        crawl_tool = self._pick_fetch_tool(client, available_tools)
        if search_tool is None:
            return {}

        payload: dict[str, Any] = {}
        search_result: dict[str, Any] | None = None
        if search_tool is not None:
            try:
                search_result = self._call_search_like_tool(client, search_tool, query, 6, role_name="hotel_specialist")
            except Exception as exc:
                _LOGGER.warning("HelloAgents role=hotel_specialist tool=%s failed=%s", search_tool, exc)
                return {}
            payload["search_tool"] = search_tool
            payload["search"] = search_result

        try:
            grounding_docs = self._collect_grounding_docs(query, destination, interests=[], social_context="hotel")
        except Exception as exc:
            _LOGGER.warning("HelloAgents role=hotel_specialist grounding_failed=%s", exc)
        else:
            if grounding_docs:
                payload["grounding_docs"] = grounding_docs

        if crawl_tool is not None:
            crawl_urls = self._extract_urls_from_search_result(search_result or {})[:3]
            if crawl_urls:
                payload["crawl_tool"] = crawl_tool
                try:
                    payload["crawl"] = self._call_crawling_tool(client, crawl_tool, crawl_urls, role_name="hotel_specialist")
                except Exception as exc:
                    _LOGGER.warning("HelloAgents role=hotel_specialist tool=%s failed=%s", crawl_tool, exc)
                    return payload
                payload["crawl_urls"] = crawl_urls
                return payload

        return payload

    def _collect_transport_tool_results(self, client: ConfiguredSearchGateway, available_tools: set[str], input_payload: dict[str, Any]) -> dict[str, Any]:
        trip_request = input_payload.get("trip_request") if isinstance(input_payload.get("trip_request"), dict) else {}
        brief = input_payload.get("planning_brief") if isinstance(input_payload.get("planning_brief"), dict) else {}
        origin = str(trip_request.get("origin") or "").strip()
        destination = str(trip_request.get("destination") or brief.get("destination") or "").strip()
        start_date = str(trip_request.get("start_date") or "").strip()
        end_date = str(trip_request.get("end_date") or "").strip()
        transport_mode = str(trip_request.get("transport_mode") or brief.get("transport") or "").strip()
        travelers = int(trip_request.get("travelers") or 1)
        query = self._build_transport_query(
            origin=origin,
            destination=destination,
            start_date=start_date,
            end_date=end_date,
            transport_mode=transport_mode,
            travelers=travelers,
        )

        search_tool = self._pick_search_tool(client, available_tools, allow_answer=True)
        fetch_tool = self._pick_fetch_tool(client, available_tools)
        if search_tool is None:
            return {}

        payload: dict[str, Any] = {}
        try:
            search_result = self._call_search_like_tool(client, search_tool, query, 6, role_name="transport_specialist")
        except Exception as exc:
            _LOGGER.warning("HelloAgents role=transport_specialist tool=%s failed=%s", search_tool, exc)
            return {}

        payload["search_tool"] = search_tool
        payload["search"] = search_result
        citations = self._extract_urls_from_search_result(search_result)

        if fetch_tool is not None and citations:
            crawl_urls = citations[:2]
            payload["crawl_tool"] = fetch_tool
            payload["crawl_urls"] = crawl_urls
            try:
                crawl_result = self._call_crawling_tool(client, fetch_tool, crawl_urls, role_name="transport_specialist")
            except Exception as exc:
                _LOGGER.warning("HelloAgents role=transport_specialist tool=%s failed=%s", fetch_tool, exc)
            else:
                payload["crawl"] = crawl_result
                citations = list(dict.fromkeys([*citations, *crawl_urls, *self._extract_urls_from_search_result(crawl_result)]))

        try:
            grounding_docs = self._collect_grounding_docs(
                query,
                destination,
                interests=[],
                social_context="transport",
                xhs_source_enabled=False,
            )
        except Exception as exc:
            _LOGGER.warning("HelloAgents role=transport_specialist grounding_failed=%s", exc)
        else:
            if grounding_docs:
                payload["grounding_docs"] = grounding_docs

        if citations:
            payload["citations"] = citations
        return payload

    def _build_transport_query(
        self,
        *,
        origin: str,
        destination: str,
        start_date: str,
        end_date: str,
        transport_mode: str,
        travelers: int,
    ) -> str:
        route = f"from {origin} to {destination}" if origin and destination else f"around {destination or origin}"
        mode_focus = self._transport_focus_for_mode(transport_mode)
        return (
            f"Travel transport planning {route} for {start_date} to {end_date}, "
            f"focusing on {mode_focus}, realistic ticket prices, transfer steps, and local mobility for {travelers} traveler(s)"
        ).strip()

    def _transport_focus_for_mode(self, transport_mode: str) -> str:
        normalized = (transport_mode or "").strip().lower()
        if normalized in {"rail", "train", "transit", "subway", "bus"}:
            return "rail connections, station transfers, and local transit passes"
        if normalized in {"car", "drive", "driving"}:
            return "car rental, toll, parking, and airport or station transfer costs"
        if normalized in {"walking", "walk"}:
            return "walkable area clustering with realistic transit backup options"
        return "intercity arrival transfers and practical local transit options"

    def _call_research_like_tool(
        self,
        client: ConfiguredSearchGateway,
        tool_name: str,
        available_tools: set[str],
        instructions: str,
        *,
        role_name: str,
    ) -> dict[str, Any]:
        if tool_name == "deep_researcher_start":
            start_result = self._call_mcp_tool(
                client,
                tool_name,
                {"instructions": instructions},
                role_name=role_name,
            )
            research_id = str(start_result.get("researchId") or start_result.get("id") or "").strip()
            latest_result = start_result
            if research_id and "deep_researcher_check" in available_tools:
                for attempt in range(3):
                    latest_result = self._call_mcp_tool(
                        client,
                        "deep_researcher_check",
                        {"researchId": research_id},
                        role_name=role_name,
                    )
                    status = self._research_status(latest_result)
                    if status in {"completed", "complete", "done", "failed", "error"}:
                        break
                    if attempt < 2:
                        time.sleep(2.0)
            return {
                "tool_name": tool_name,
                "research_id": research_id,
                "status": self._research_status(latest_result) or self._research_status(start_result),
                "start": start_result,
                "result": latest_result,
            }
        result = self._call_mcp_tool(
            client,
            tool_name,
            {
                "instructions": instructions,
                "wait_for_completion": True,
                "poll_interval_seconds": 2.0,
                "max_wait_seconds": 30.0,
            },
            role_name=role_name,
        )
        return {
            "tool_name": tool_name,
            "status": self._research_status(result),
            "result": result,
        }

    def _call_crawling_tool(self, client: ConfiguredSearchGateway, tool_name: str, urls: list[str], *, role_name: str) -> dict[str, Any]:
        if tool_name == "web_fetch":
            results: list[dict[str, Any]] = []
            for url in urls:
                fetched = self._call_mcp_tool(client, tool_name, {"url": url}, role_name=role_name)
                item = {"url": url}
                if isinstance(fetched, dict):
                    item.update(fetched)
                else:
                    item["text"] = str(fetched)
                results.append(item)
            return {"results": results}
        return self._call_mcp_tool(client, tool_name, {"urls": urls, "include_text": True}, role_name=role_name)

    def _research_status(self, payload: dict[str, Any]) -> str:
        status = payload.get("status")
        if isinstance(status, str) and status.strip():
            return status.strip().lower()
        nested_result = payload.get("result")
        if isinstance(nested_result, dict):
            nested_status = nested_result.get("status")
            if isinstance(nested_status, str) and nested_status.strip():
                return nested_status.strip().lower()
        start_result = payload.get("start")
        if isinstance(start_result, dict):
            start_status = start_result.get("status")
            if isinstance(start_status, str) and start_status.strip():
                return start_status.strip().lower()
        return ""

    def _call_mcp_tool(self, client: ConfiguredSearchGateway, tool_name: str, arguments: dict[str, Any], *, role_name: str) -> dict[str, Any]:
        _LOGGER.debug("HelloAgents role=%s tool=%s args=%s", role_name, tool_name, json.dumps(arguments, ensure_ascii=False))
        return client.call_operation(tool_name, arguments)

    def _call_search_like_tool(self, client: ConfiguredSearchGateway, tool_name: str, query: str, num_results: int, *, role_name: str) -> dict[str, Any]:
        if tool_name == "web_search":
            return self._call_mcp_tool(client, tool_name, {"query": query}, role_name=role_name)
        if tool_name == "answer":
            return self._call_mcp_tool(client, tool_name, {"query": query, "include_text": True}, role_name=role_name)
        return self._call_mcp_tool(client, tool_name, {"query": query, "num_results": num_results, "include_text": True}, role_name=role_name)

    def _extract_urls_from_search_result(self, search_result: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()

        def record(candidate: str) -> None:
            normalized = candidate.strip()
            if ")[[" in normalized:
                normalized = normalized.split(")[[", 1)[0]
            normalized = normalized.rstrip(").,;]")
            if not normalized.startswith("http") or normalized in seen:
                return
            seen.add(normalized)
            urls.append(normalized)

        def visit(value: Any, parent_key: str = "") -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    normalized_key = str(key).strip().lower()
                    if normalized_key in {"url", "id", "link", "source", "website"} and isinstance(item, str):
                        record(item)
                    visit(item, normalized_key)
                return
            if isinstance(value, list):
                for item in value:
                    visit(item, parent_key)
                return
            if isinstance(value, str):
                if parent_key in {"url", "id", "link", "source", "website"}:
                    record(value)
                for match in re.findall(r"https?://[^\s<>'\"\]]+", value):
                    record(match)

        visit(search_result)
        return urls

    def _merge_grounding_documents(self, *collections: Any) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for collection in collections:
            if not isinstance(collection, list):
                continue
            for item in collection:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                if not url:
                    continue
                key = url.casefold()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
        return merged

    def _build_citation_notes(self, citations: list[str], request: PlanningRequest) -> list[str]:
        if not citations:
            return []
        prefix = "\u5929\u6c14\u5f15\u7528" if is_chinese_output(request) else "Weather citation"
        return [f"{prefix}: {url}" for url in citations]

    def _collect_poi_candidates(self, request: PlanningRequest, queries: list[str], limit: int) -> list[dict[str, Any]]:
        seen: set[str] = set()
        candidates: list[dict[str, Any]] = []
        for query in queries:
            normalized_query = str(query or "").strip()
            if not normalized_query:
                continue
            for result in self._maps_provider.search_pois(normalized_query, request.destination, limit=limit):
                if result.id in seen:
                    continue
                seen.add(result.id)
                detail = self._ensure_detail(result)
                candidates.append(self._poi_candidate_to_dict(detail))
                if len(candidates) >= limit:
                    return candidates
        return candidates

    def _collect_hotel_candidates(self, request: PlanningRequest, queries: list[str], limit: int) -> list[dict[str, Any]]:
        seen: set[str] = set()
        candidates: list[dict[str, Any]] = []
        for query in queries:
            normalized_query = str(query or "").strip()
            if not normalized_query:
                continue
            for result in self._maps_provider.search_pois(normalized_query, request.destination, limit=limit):
                if result.id in seen:
                    continue
                seen.add(result.id)
                detail = self._ensure_detail(result)
                candidates.append(
                    {
                        "name": detail.name,
                        "area": detail.location.address.district or detail.city or request.destination,
                        "summary": detail.summary,
                        "address": detail.location.address.formatted,
                        "price_hint": detail.price_level or "unknown",
                        "opening_hours": detail.opening_hours,
                    }
                )
                if len(candidates) >= limit:
                    return candidates
        return candidates

    def _poi_candidate_to_dict(self, detail: PoiDetail) -> dict[str, Any]:
        return {
            "name": detail.name,
            "area": detail.location.address.district or detail.city or "",
            "category": detail.category,
            "summary": detail.summary,
            "address": detail.location.address.formatted,
            "opening_hours": detail.opening_hours,
            "price_hint": detail.price_level or "unknown",
        }

    def _season_for_month(self, month: int) -> str:
        if month in {12, 1, 2}:
            return "winter"
        if month in {3, 4, 5}:
            return "spring"
        if month in {6, 7, 8}:
            return "summer"
        return "autumn"

    def _weather_focus_for_month(self, month: int) -> str:
        if month in {6, 7}:
            return "heat, humidity, and rain planning"
        if month in {8, 9}:
            return "heat and storm planning"
        if month in {12, 1, 2}:
            return "cold mornings and short daylight planning"
        return "mild temperatures and occasional rain planning"

    def _coerce_text(self, response: Any) -> str:
        if isinstance(response, str):
            return response
        content = getattr(response, "content", None)
        if isinstance(content, str) and content.strip():
            return content
        return str(response)

    def _weather_guidance_needs_language_repair(self, weather: HelloAgentsWeatherGuidance, request: PlanningRequest) -> bool:
        locale = infer_output_locale(request)
        texts = [
            weather.overall_outlook,
            *weather.daily_outlook,
            *weather.packing_notes,
            *weather.timing_guidance,
            *weather.weather_risks,
        ]
        combined = " ".join(str(item or "").strip() for item in texts if str(item or "").strip())
        if not combined:
            return False
        has_cjk = bool(re.search(r"[㐀-鿿]", combined))
        has_english = bool(re.search(r"[A-Za-z]{3,}", combined))
        if locale == "zh-CN":
            return has_english and not has_cjk
        return has_cjk and not has_english

    def _repair_weather_guidance_language(
        self,
        weather: HelloAgentsWeatherGuidance,
        request: PlanningRequest,
        llm_client: OpenAICompatibleClient,
    ) -> HelloAgentsWeatherGuidance:
        locale = infer_output_locale(request)
        target_language = "Simplified Chinese" if locale == "zh-CN" else "English"
        messages = [
            {
                "role": "system",
                "content": (
                    "You are TravelMind weather guidance localization formatter. "
                    "Return one valid JSON object only, with no markdown fences or prose outside JSON. "
                    f"Rewrite all user-visible weather guidance fields into {target_language}. "
                    "Preserve JSON structure, list lengths, field names, factual details, temperatures, dates, and citations exactly. "
                    f"{build_output_language_instruction(locale)} "
                    "If temperatures are present, keep them explicit in the localized text."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "target_locale": locale,
                        "rewrite_fields": [
                            "overall_outlook",
                            "daily_outlook[]",
                            "packing_notes[]",
                            "timing_guidance[]",
                            "weather_risks[]",
                        ],
                        "weather_guidance": weather.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        content = llm_client.create_chat_completion(messages=messages, temperature=0.1, max_tokens=1200)
        return self._parse_structured_response(content, HelloAgentsWeatherGuidance)

    def _parse_structured_response(self, content: str, model_cls: type[BaseModel]) -> BaseModel:
        payload = self._extract_json_payload(content)
        try:
            return model_cls.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc

    def _extract_json_payload(self, content: str) -> dict[str, Any]:
        candidate = str(content).strip()
        if not candidate:
            raise ValueError("HelloAgents response was empty")

        if candidate.startswith("```"):
            candidate = self._strip_code_fences(candidate)

        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise ValueError("HelloAgents response did not contain a valid JSON object")
            payload = json.loads(candidate[start : end + 1])

        if not isinstance(payload, dict):
            raise ValueError("HelloAgents response root must be a JSON object")
        return payload

    def _strip_code_fences(self, content: str) -> str:
        lines = content.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()

    def _summarize_brief(self, brief: HelloAgentsBrief) -> str:
        must_have = ", ".join(brief.must_have[:3]) if brief.must_have else "none"
        budget_mode = "hard budget" if brief.budget_is_hard_constraint else "flexible budget"
        priority = brief.budget_priority or "balanced"
        return f"{brief.destination}; {brief.trip_days} days; pace {brief.pace or 'n/a'}; {budget_mode}; priority {priority}; must-have {must_have}."

    def _summarize_attractions(self, attractions: HelloAgentsAttractionGrounding) -> str:
        booking_ready = sum(1 for poi in attractions.featured_pois if poi.booking_info is not None or poi.visit_requirements is not None)
        return (
            f"{len(attractions.candidate_areas)} areas, "
            f"{len(attractions.featured_pois)} featured POIs, "
            f"{booking_ready} POIs with ticket or reservation guidance, "
            f"{len(attractions.sequencing_hints)} sequencing hints."
        )

    def _summarize_weather(self, weather: HelloAgentsWeatherGuidance) -> str:
        return (
            f"{weather.overall_outlook} "
            f"{len(weather.packing_notes)} packing notes, {len(weather.weather_risks)} weather risks."
        )

    def _summarize_hotels(self, hotels: HelloAgentsHotelRecommendation) -> str:
        selected = hotels.final_recommended_hotel.name if hotels.final_recommended_hotel is not None else "none"
        return (
            f"selected hotel {selected}, "
            f"{len(hotels.recommended_areas)} stay areas, "
            f"{len(hotels.hotel_candidates)} hotel candidates, "
            f"{len(hotels.stay_strategy)} stay strategy notes, "
            f"{len(hotels.price_timeliness_notes)} price freshness notes, "
            f"{len(hotels.review_notes)} review notes."
        )

    def _summarize_transport(self, transport: HelloAgentsTransportGuidance) -> str:
        return (
            f"{len(transport.intercity_options)} intercity options, "
            f"estimated intercity cost {round(float(transport.estimated_intercity_cost or 0.0), 2)}, "
            f"estimated local transport cost {round(float(transport.estimated_local_transport_cost or 0.0), 2)}, "
            f"booking URL {'yes' if transport.official_booking_url else 'no'}."
        )

    def _summarize_itinerary(self, summary: str, days: list[Any], risks: list[str]) -> str:
        compact = summary.strip() or "Draft ready."
        return f"{compact} {len(days)} days, {len(risks)} risks."

    def _pick_weather_note(self, notes: list[str], day_index: int) -> str:
        normalized = [str(item).strip() for item in notes if str(item).strip()]
        if not normalized:
            return ""
        if day_index - 1 < len(normalized):
            return normalized[day_index - 1]
        return normalized[0]

    def _contains_temperature_signal(self, text: str) -> bool:
        candidate = str(text or "").strip()
        if not candidate:
            return False
        patterns = (
            r"\b-?\d+(?:\.\d+)?\s*(?:\u00b0\s?[CF]|\u2103|\u2109|\u00b0C|\u00b0F)\b",
            r"\b-?\d+(?:\.\d+)?\s*(?:to|-|\u2013|\u2014|~|\uff5e|\u81f3|\u5230)\s*-?\d+(?:\.\d+)?\s*(?:\u00b0\s?[CF]|\u2103|\u2109|\u00b0C|\u00b0F)?\b",
            r"(?:temperature|temperatures|temp|high|low|max|min)[^.;,\n]{0,32}\d",
            r"(?:\u6c14\u6e29|\u6e29\u5ea6|\u9ad8\u6e29|\u4f4e\u6e29|\u6700\u9ad8|\u6700\u4f4e)[^\u3002\uff1b\uff0c,\n]{0,32}\d",
        )
        lowered = candidate.casefold()
        return any(re.search(pattern, candidate, flags=re.IGNORECASE) for pattern in patterns) or any(
            token in lowered for token in ("\u00b0c", "\u00b0f", "\u2103", "\u2109")
        )

    def _extract_temperature_snippet(self, text: str) -> str:
        candidate = str(text or "").strip()
        if not candidate:
            return ""
        for segment in re.split(r"(?<=[\u3002\uff01\uff1f!?;\uff1b])\s+|\n+", candidate):
            normalized = str(segment or "").strip()
            if normalized and self._contains_temperature_signal(normalized):
                return normalized
        return candidate if self._contains_temperature_signal(candidate) else ""

    def _flatten_text_values(self, value: Any) -> list[str]:
        collected: list[str] = []

        def visit(node: Any) -> None:
            if isinstance(node, dict):
                for item in node.values():
                    visit(item)
                return
            if isinstance(node, list):
                for item in node:
                    visit(item)
                return
            if isinstance(node, str):
                normalized = node.strip()
                if normalized:
                    collected.append(normalized)

        visit(value)
        return collected

    def _resolve_weather_temperature_hint(
        self,
        day_index: int,
        weather_guidance: HelloAgentsWeatherGuidance,
        weather_tool_results: dict[str, Any] | None,
    ) -> str:
        candidates = [
            self._pick_weather_note(weather_guidance.daily_outlook, day_index),
            weather_guidance.overall_outlook,
            *self._flatten_text_values(weather_tool_results or {}),
        ]
        seen: set[str] = set()
        for candidate in candidates:
            snippet = self._extract_temperature_snippet(candidate)
            if not snippet:
                continue
            key = snippet.casefold()
            if key in seen:
                continue
            seen.add(key)
            return snippet
        return ""

    def _normalize_match_key(self, value: str) -> str:
        return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", str(value or "").strip().casefold())

    def _find_matching_featured_poi(
        self,
        item_name: str,
        attraction_grounding: HelloAgentsAttractionGrounding | None,
    ) -> HelloAgentsResearchPoi | None:
        if attraction_grounding is None:
            return None
        target = self._normalize_match_key(item_name)
        if not target:
            return None
        best_match: HelloAgentsResearchPoi | None = None
        best_score = -1
        for poi in attraction_grounding.featured_pois:
            candidate = self._normalize_match_key(poi.name)
            if not candidate:
                continue
            score = 0
            if candidate == target:
                score = 3
            elif candidate in target or target in candidate:
                score = 2
            elif any(token and token in target for token in candidate.split()):
                score = 1
            if score > best_score:
                best_match = poi
                best_score = score
        return best_match if best_score > 0 else None

    def _pick_official_url_for_poi(
        self,
        item_name: str,
        grounding_documents: list[dict[str, Any]] | None,
    ) -> str | None:
        target = self._normalize_match_key(item_name)
        if not target:
            return None
        best_url: str | None = None
        best_score = -1
        for raw_doc in grounding_documents or []:
            if not isinstance(raw_doc, dict):
                continue
            platform = str(raw_doc.get("platform") or "").strip().lower()
            source_type = str(raw_doc.get("source_type") or "").strip().lower()
            if platform != "official-tourism" and not source_type.startswith("official"):
                continue
            url = str(raw_doc.get("url") or "").strip()
            if not url.startswith("http"):
                continue
            haystack = " ".join(
                str(raw_doc.get(key) or "")
                for key in ("place_name", "title", "summary", "destination", "category")
            )
            candidate = self._normalize_match_key(haystack)
            if not candidate:
                continue
            score = 0
            if target == candidate:
                score = 4
            elif target in candidate:
                score = 3
            elif any(token and token in candidate for token in target.split()):
                score = 1
            if score > best_score:
                best_url = url
                best_score = score
        return best_url if best_score > 0 else None

    def _merge_booking_info(
        self,
        primary: Any,
        fallback: BookingInfo | None,
        *,
        item_name: str,
        grounding_documents: list[dict[str, Any]] | None,
    ) -> BookingInfo | None:
        primary_info = BookingInfo.model_validate(primary.model_dump(mode="json")) if isinstance(primary, BaseModel) else BookingInfo.model_validate(primary) if isinstance(primary, dict) else None
        if primary_info is None and fallback is None:
            return None
        merged = BookingInfo(
            price_label=(primary_info.price_label if primary_info and primary_info.price_label else None) or (fallback.price_label if fallback else None),
            estimated_price=(primary_info.estimated_price if primary_info and primary_info.estimated_price is not None else None),
            booking_required=bool((primary_info.booking_required if primary_info is not None else False) or (fallback.booking_required if fallback is not None else False)),
            reservation_required=bool((primary_info.reservation_required if primary_info is not None else False) or (fallback.reservation_required if fallback is not None else False)),
            official_booking_url=(primary_info.official_booking_url if primary_info and primary_info.official_booking_url else None)
            or (fallback.official_booking_url if fallback else None)
            or self._pick_official_url_for_poi(item_name, grounding_documents),
            booking_window=(primary_info.booking_window if primary_info and primary_info.booking_window else None) or (fallback.booking_window if fallback else None),
            reminder=(primary_info.reminder if primary_info and primary_info.reminder else None) or (fallback.reminder if fallback else None),
            notes=list(dict.fromkeys([*(((primary_info.notes if primary_info else None) or [])), *(((fallback.notes if fallback else None) or []))])),
            source_urls=list(
                dict.fromkeys(
                    [
                        *(((primary_info.source_urls if primary_info else None) or [])),
                        *(((fallback.source_urls if fallback else None) or [])),
                    ]
                )
            ),
        )
        if merged.official_booking_url and merged.official_booking_url not in merged.source_urls:
            merged.source_urls.append(merged.official_booking_url)
        if merged.estimated_price is None and fallback is not None and fallback.estimated_price is not None:
            merged.estimated_price = fallback.estimated_price
        if not any(
            [
                merged.price_label,
                merged.estimated_price is not None,
                merged.booking_required,
                merged.reservation_required,
                merged.official_booking_url,
                merged.booking_window,
                merged.reminder,
                merged.notes,
                merged.source_urls,
            ]
        ):
            return None
        return merged

    def _merge_visit_requirements(self, primary: Any, fallback: VisitRequirements | None) -> VisitRequirements | None:
        primary_requirements = (
            VisitRequirements.model_validate(primary.model_dump(mode="json"))
            if isinstance(primary, BaseModel)
            else VisitRequirements.model_validate(primary)
            if isinstance(primary, dict)
            else None
        )
        if primary_requirements is None and fallback is None:
            return None
        merged = VisitRequirements(
            reservation_policy=(primary_requirements.reservation_policy if primary_requirements and primary_requirements.reservation_policy else None)
            or (fallback.reservation_policy if fallback else None),
            timed_entry=bool((primary_requirements.timed_entry if primary_requirements is not None else False) or (fallback.timed_entry if fallback is not None else False)),
            identity_required=bool((primary_requirements.identity_required if primary_requirements is not None else False) or (fallback.identity_required if fallback is not None else False)),
            advance_booking_note=(primary_requirements.advance_booking_note if primary_requirements and primary_requirements.advance_booking_note else None)
            or (fallback.advance_booking_note if fallback else None),
            notes=list(dict.fromkeys([*(((primary_requirements.notes if primary_requirements else None) or [])), *(((fallback.notes if fallback else None) or []))])),
        )
        if not any([merged.reservation_policy, merged.timed_entry, merged.identity_required, merged.advance_booking_note, merged.notes]):
            return None
        return merged

    def _build_transport_booking_summary(
        self,
        payload_summary: Any,
        transport_guidance: HelloAgentsTransportGuidance | None,
    ) -> TransportBookingSummary | None:
        payload_transport = (
            TransportBookingSummary.model_validate(payload_summary.model_dump(mode="json"))
            if isinstance(payload_summary, BaseModel)
            else TransportBookingSummary.model_validate(payload_summary)
            if isinstance(payload_summary, dict)
            else None
        )
        if payload_transport is None and transport_guidance is None:
            return None
        first_option = transport_guidance.intercity_options[0] if transport_guidance and transport_guidance.intercity_options else None
        merged = TransportBookingSummary(
            summary=(payload_transport.summary if payload_transport and payload_transport.summary else None)
            or (transport_guidance.summary if transport_guidance and transport_guidance.summary else None)
            or (transport_guidance.arrival_strategy[0] if transport_guidance and transport_guidance.arrival_strategy else None),
            recommended_option=(payload_transport.recommended_option if payload_transport and payload_transport.recommended_option else None)
            or (transport_guidance.recommended_option if transport_guidance and transport_guidance.recommended_option else None)
            or (first_option.route if first_option else None),
            estimated_intercity_cost=(
                payload_transport.estimated_intercity_cost
                if payload_transport and payload_transport.estimated_intercity_cost > 0
                else round(float(transport_guidance.estimated_intercity_cost or 0.0), 2) if transport_guidance else 0.0
            ),
            estimated_local_transport_cost=(
                payload_transport.estimated_local_transport_cost
                if payload_transport and payload_transport.estimated_local_transport_cost > 0
                else round(float(transport_guidance.estimated_local_transport_cost or 0.0), 2) if transport_guidance else 0.0
            ),
            booking_required=bool(
                (payload_transport.booking_required if payload_transport is not None else False)
                or (transport_guidance.booking_required if transport_guidance is not None else False)
                or (first_option.booking_required if first_option is not None else False)
                or (first_option.reservation_required if first_option is not None else False)
            ),
            official_booking_url=(payload_transport.official_booking_url if payload_transport and payload_transport.official_booking_url else None)
            or (transport_guidance.official_booking_url if transport_guidance and transport_guidance.official_booking_url else None)
            or (first_option.official_booking_url if first_option and first_option.official_booking_url else None),
            booking_window=(payload_transport.booking_window if payload_transport and payload_transport.booking_window else None)
            or (transport_guidance.booking_window if transport_guidance and transport_guidance.booking_window else None)
            or (first_option.booking_window if first_option and first_option.booking_window else None),
            pass_or_ticket_notes=list(
                dict.fromkeys(
                    [
                        *(((payload_transport.pass_or_ticket_notes if payload_transport else None) or [])),
                        *(((transport_guidance.pass_or_ticket_notes if transport_guidance else None) or [])),
                    ]
                )
            ),
            reminders=list(
                dict.fromkeys(
                    [
                        *(((payload_transport.reminders if payload_transport else None) or [])),
                        *(((transport_guidance.reminders if transport_guidance else None) or [])),
                    ]
                )
            ),
            notes=list(
                dict.fromkeys(
                    [
                        *(((payload_transport.notes if payload_transport else None) or [])),
                        *(((transport_guidance.notes if transport_guidance else None) or [])),
                        *(((transport_guidance.budget_notes if transport_guidance else None) or [])),
                        *(((transport_guidance.transport_risks if transport_guidance else None) or [])),
                        *(((transport_guidance.sequencing_constraints if transport_guidance else None) or [])),
                        *(((first_option.booking_notes if first_option else None) or [])),
                    ]
                )
            ),
            source_urls=list(
                dict.fromkeys(
                    [
                        *(((payload_transport.source_urls if payload_transport else None) or [])),
                        *(((transport_guidance.source_urls if transport_guidance else None) or [])),
                        *(([first_option.official_booking_url] if first_option and first_option.official_booking_url else [])),
                    ]
                )
            ),
        )
        if merged.official_booking_url and merged.official_booking_url not in merged.source_urls:
            merged.source_urls.append(merged.official_booking_url)
        if not any(
            [
                merged.summary,
                merged.recommended_option,
                merged.estimated_intercity_cost > 0,
                merged.estimated_local_transport_cost > 0,
                merged.booking_required,
                merged.official_booking_url,
                merged.booking_window,
                merged.pass_or_ticket_notes,
                merged.reminders,
                merged.notes,
                merged.source_urls,
            ]
        ):
            return None
        return merged

    def _build_day_weather(
        self,
        day_index: int,
        weather_guidance: HelloAgentsWeatherGuidance | None,
        citations: list[str] | None,
        weather_tool_results: dict[str, Any] | None = None,
    ) -> PlannedDayWeather | None:
        if weather_guidance is None:
            return None
        summary = self._pick_weather_note(weather_guidance.daily_outlook, day_index) or weather_guidance.overall_outlook.strip()
        notes: list[str] = []
        for candidate in (
            self._pick_weather_note(weather_guidance.timing_guidance, day_index),
            self._pick_weather_note(weather_guidance.packing_notes, day_index),
            self._pick_weather_note(weather_guidance.weather_risks, day_index),
        ):
            if candidate and candidate not in notes:
                notes.append(candidate)
        temperature_hint = self._resolve_weather_temperature_hint(day_index, weather_guidance, weather_tool_results)
        if temperature_hint:
            if not self._contains_temperature_signal(summary) and temperature_hint.casefold() not in summary.casefold():
                summary = f"{summary} {temperature_hint}".strip() if summary else temperature_hint
            elif all(temperature_hint.casefold() not in note.casefold() for note in notes):
                notes.insert(0, temperature_hint)
        citation_list = [str(item).strip() for item in (citations or []) if str(item).strip()]
        if not summary and not notes and not citation_list:
            return None
        return PlannedDayWeather(summary=summary, notes=notes, citations=citation_list[:3])
    def _build_result_from_payload(
        self,
        payload: Any,
        request: PlanningRequest,
        pipeline_notes: list[str],
        agent_runs: list[AgentRunStep],
        *,
        attraction_grounding: HelloAgentsAttractionGrounding | None = None,
        weather_guidance: HelloAgentsWeatherGuidance | None = None,
        weather_citations: list[str] | None = None,
        weather_tool_results: dict[str, Any] | None = None,
        grounding_documents: list[dict[str, Any]] | None = None,
        transport_guidance: HelloAgentsTransportGuidance | None = None,
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
                matched_poi = self._find_matching_featured_poi(item.name, attraction_grounding)
                route_ref = None
                note = item.note.strip() or ("\u6765\u81ea\u5df2\u914d\u7f6e\u7684 HelloAgents \u884c\u7a0b\u8349\u7a3f\u3002" if zh_output else "Generated from the configured HelloAgents itinerary draft.")
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
                    note = f"{note} \u4ece\u4e0a\u4e00\u7ad9\u8f6c\u79fb\u5230\u8fd9\u91cc\u7ea6 {matrix_cell.duration_minutes} \u5206\u949f\u3002" if zh_output else f"{note} Transfer from previous stop is about {matrix_cell.duration_minutes} min."

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
                        booking_info=self._merge_booking_info(
                            getattr(item, "booking_info", None),
                            matched_poi.booking_info if matched_poi is not None else None,
                            item_name=item.name,
                            grounding_documents=grounding_documents,
                        ),
                        visit_requirements=self._merge_visit_requirements(
                            getattr(item, "visit_requirements", None),
                            matched_poi.visit_requirements if matched_poi is not None else None,
                        ),
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

            day_weather = self._build_day_weather(day_index, weather_guidance, weather_citations, weather_tool_results)
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

        host = urlparse(self._llm_config.base_url).netloc or self._llm_config.base_url
        total_budget = payload.total_budget_estimate if payload.total_budget_estimate and payload.total_budget_estimate > 0 else request.budget
        plan = PlanningResult(
            summary=payload.summary,
            total_budget_estimate=total_budget,
            days=planned_days,
            risks=payload.risks,
            transport_booking_summary=self._build_transport_booking_summary(
                getattr(payload, "transport_booking_summary", None),
                transport_guidance,
            ),
            trace=AgentTrace(
                provider="helloagents-poc",
                workflow_id=generate_workflow_id(),
                notes=[
                    *pipeline_notes,
                    f"Default HelloAgents endpoint: {host}.",
                    f"Enriched the HelloAgents planner output with structured POI and route references via {self._maps_provider.provider_name}.",
                ],
                license_notice=_LICENSE_NOTICE,
                agent_runs=agent_runs,
                grounding_documents=list(grounding_documents or []),
                transport_guidance=transport_guidance.model_dump(mode="json") if transport_guidance is not None else None,
            ),
        )
        return enrich_plan_with_budget(plan, request)

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
