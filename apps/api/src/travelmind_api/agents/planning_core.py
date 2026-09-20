"""Framework-neutral deterministic travel-planning business rules."""
from __future__ import annotations

import logging
import json
import re
import time
from datetime import date, timedelta
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ValidationError

from travelmind_api.agents.base import (
    AgentRunStep,
    BookingInfo,
    ExportDraft,
    NearbyPoiSuggestion,
    PlannedDay,
    PlannedDayWeather,
    PlannedItem,
    PlanningRequest,
    PlanningResult,
    SourceSummary,
    StayHotelCandidate,
    StayRecommendation,
    TransportBookingSummary,
    VisitRequirements,
)
from travelmind_api.agents.stub import StubOrchestrator
from travelmind_api.agents.runtime import RoleProgressCallback
from travelmind_api.core.logging_utils import log_job_event
from travelmind_api.core.security import generate_identifier
from travelmind_api.services.execution_validation import has_closed_weekday_constraint, validate_timeline
from travelmind_api.services.entity_identity import normalize_identity, entity_matches
from travelmind_api.services.hotel_evidence import verify_hotel_pages
from travelmind_api.services.poi_operation_evidence import verify_poi_open_days
from travelmind_api.services.transport_evidence import verify_transport_candidate_pages
from travelmind_api.services.weather_evidence import verify_daily_forecast_pages
from travelmind_api.services.planning_details import BookingDetails, HotelEvidence, TransportServiceCandidate
from travelmind_api.services.planning.payloads import PlanningPayloadMixin, build_trip_request_payload
from travelmind_api.services.planning.result_builder import PlanningResultBuilderMixin
from travelmind_api.services.planning.role_models import (
    AttractionGrounding,
    DailyForecast,
    FoodPoi,
    FoodRecommendation,
    HotelCandidate,
    HotelRecommendation,
    PlanningBrief,
    PoiGrounding,
    ResearchPoi,
    TopPoiItem,
    TransportGuidance,
    TransportOption,
    WeatherGuidance,
    WeatherSegment,
)
from travelmind_api.services.llm import LlmConfig, LlmEndpointConfig, LlmPlanningPayload, OpenAICompatibleClient, build_planning_messages, parse_planning_response
from travelmind_api.services.llm.localization import build_output_language_instruction, infer_output_locale, is_chinese_output, planning_payload_needs_language_repair
from travelmind_api.prompts.roles.planning import (
    build_brief_parser_prompt,
    build_hotel_specialist_prompt,
    build_itinerary_planner_prompt,
    build_poi_specialist_prompt,
    build_transport_specialist_prompt,
    build_weather_specialist_prompt,
)
from travelmind_api.services.llm.prompts import PLANNING_OUTPUT_SCHEMA
from travelmind_api.services.llm.parser import LlmBookingInfo
from travelmind_api.services.maps import MapsPoiProvider, PoiDetail, PoiSearchResult
from travelmind_api.services.search_connector import ConfiguredSearchGateway, SearchServiceConfig
from travelmind_api.services.search_service import search_documents



_LOGGER = logging.getLogger(__name__)

_ROLE_SEQUENCE = (
    "brief_parser",
    "poi_specialist",
    "weather_specialist",
    "hotel_specialist",
    "transport_specialist",
    "itinerary_planner",
)
_INITIAL_PARALLEL_ROLES = ("poi_specialist", "weather_specialist")
_SECONDARY_PARALLEL_ROLES = ("hotel_specialist", "transport_specialist")
_SPECIALIST_PARALLEL_ROLES = (*_INITIAL_PARALLEL_ROLES, *_SECONDARY_PARALLEL_ROLES)
_DIRECT_GROK_SEARCH_ROLES = {"weather_specialist", "hotel_specialist", "transport_specialist"}
@dataclass(frozen=True)
class PlanningRoleConfig:
    role_name: str
    title: str
    description: str
    prompt_focus: str
    system_prompt: str
    prompt_version: str
    temperature: float = 0.2
    progress_percent: int = 0
    max_tokens: int | None = None
    max_request_attempts: int = 2
    min_timeout_seconds: float = 120.0
    timeout_cap_seconds: float | None = None
    stream: bool = False


class PlanningCore(PlanningPayloadMixin, PlanningResultBuilderMixin, StubOrchestrator):
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
        self._native_role_citations: dict[str, list[str]] = {}

    def plan_trip(self, request: PlanningRequest) -> PlanningResult:
        del request
        raise RuntimeError("PlanningCore contains business rules only; execute planning through LangGraphOrchestrator")

    def summarize_sources(self, destination: str, findings: list[str]) -> SourceSummary:
        return super().summarize_sources(destination, findings)

    def draft_export_payload(self, request: PlanningRequest, plan: PlanningResult) -> ExportDraft:
        return super().draft_export_payload(request, plan)

    def _log_event(self, event: str, *, message: str, level: str = "INFO", **payload: Any) -> None:
        log_job_event(
            event,
            job_id=self._execution_job_id,
            logger_name=__name__,
            level=level,
            message=message,
            **payload,
        )








    def _build_trip_payload(self, request: PlanningRequest) -> dict[str, Any]:
        return build_trip_request_payload(request)

    def _build_role_llm_configs(self) -> dict[str, LlmEndpointConfig]:
        assert self._llm_config is not None
        return {role_name: self._llm_config.config_for_role(role_name) for role_name in _ROLE_SEQUENCE}

    def _build_role_configs(self, request: PlanningRequest) -> dict[str, PlanningRoleConfig]:
        planner_messages = build_planning_messages(request)
        planner_system_prompt = next((message["content"] for message in planner_messages if message.get("role") == "system"), "")
        brief_prompt = build_brief_parser_prompt()
        poi_prompt = build_poi_specialist_prompt()
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
            "brief_parser": PlanningRoleConfig(
                role_name="brief_parser",
                title="Brief parser",
                description="Compresses the trip input into a compact planning brief.",
                prompt_focus="Extract constraints and preferences into JSON only. Do not draft the itinerary.",
                system_prompt=f"{brief_prompt.system_prompt} {language_instruction}{locale_clause}",
                prompt_version=brief_prompt.version,
                progress_percent=24,
            ),
            # poi_specialist:
            # 中文注释：统一负责景点、街区、自然风景与非餐饮体验类 POI grounding，不生成日程顺序。
            "poi_specialist": PlanningRoleConfig(
                role_name="poi_specialist",
                title="POI specialist",
                description="Discovers core attraction, district, scenery, and non-food experience POIs with compact evidence.",
                prompt_focus="Use trip_request, planning_brief, poi_context, and native search when the configured POI model supports it; do not call external tools, plan the final itinerary, include food/cafe stops, or pass long evidence.",
                system_prompt=f"{poi_prompt.system_prompt} {language_instruction}{locale_clause}",
                prompt_version=poi_prompt.version,
                progress_percent=44,
                max_tokens=4800,
                max_request_attempts=1,
                min_timeout_seconds=300.0,
                timeout_cap_seconds=420.0,
                stream=True,
            ),
            # weather_specialist:
            # 中文注释：负责天气 planning guidance，强调季节性和可执行建议，不伪装成实时预报。
            "weather_specialist": PlanningRoleConfig(
                role_name="weather_specialist",
                title="Weather specialist",
                description="Produces city or area weather guidance, timing advice, and packing notes.",
                prompt_focus="Use Grok's native search context when this role runs on Grok; otherwise use MCP tool results. Return weather guidance JSON only.",
                system_prompt=f"{weather_prompt.system_prompt} {language_instruction}{locale_clause}",
                prompt_version=weather_prompt.version,
                progress_percent=52,
                stream=True,
            ),
            # hotel_specialist:
            # 中文注释：负责住宿区域与候选酒店建议，目标是降低转场成本并匹配预算。
            "hotel_specialist": PlanningRoleConfig(
                role_name="hotel_specialist",
                title="Hotel specialist",
                description="Recommends stay areas and hotels based on POI clusters, budget, and pace.",
                prompt_focus="Use poi_collection, stay preference, budget, candidate hotels, and Grok native search context when this role runs on Grok; otherwise use MCP tool results. Return hotel recommendation JSON only.",
                system_prompt=f"{hotel_prompt.system_prompt} {language_instruction}{locale_clause}",
                prompt_version=hotel_prompt.version,
                progress_percent=62,
                max_tokens=1800,
                stream=True,
            ),
            # transport_specialist:
            # 中文注释：负责交通票价、换乘约束和到离程策略，把交通价格与时效从最终 planner 里拆出来单独 grounding。
            "transport_specialist": PlanningRoleConfig(
                role_name="transport_specialist",
                title="Transport specialist",
                description="Builds grounded transport options, pricing constraints, and transfer strategy.",
                prompt_focus="Use poi_collection, the trip brief, and Grok native search context when this role runs on Grok; otherwise use MCP tool results. Return transport guidance JSON only, including grounded cost estimates.",
                system_prompt=f"{transport_prompt.system_prompt} {language_instruction}{locale_clause}",
                prompt_version=transport_prompt.version,
                progress_percent=68,
                max_tokens=1600,
                stream=True,
            ),
            # itinerary_planner:
            # 中文注释：最终总控角色，复用主 planner prompt，再消费四份结构化中间结果生成最终 itinerary。
            "itinerary_planner": PlanningRoleConfig(
                role_name="itinerary_planner",
                title="Itinerary planner",
                description="Combines the POI collection, weather, hotel strategy, and transport constraints into the final itinerary draft.",
                prompt_focus="Return the final itinerary JSON using the brief, poi_collection, weather guidance, hotel strategy, and transport guidance.",
                system_prompt=f"{planner_prompt.system_prompt} {language_instruction}{locale_clause}",
                prompt_version=planner_prompt.version,
                progress_percent=82,
                stream=True,
            ),
        }

    def _emit_role_progress(self, role_config: PlanningRoleConfig) -> None:
        if self._progress_callback is None:
            return
        self._progress_callback(role_config.role_name, role_config.title, role_config.description, role_config.progress_percent)

    def _describe_endpoint(self, llm_config: LlmEndpointConfig) -> str:
        return urlparse(llm_config.base_url).netloc or llm_config.base_url

    def _build_agent_run(
        self,
        role_config: PlanningRoleConfig,
        llm_config: LlmEndpointConfig,
        output_summary: str,
        *,
        invocation_metadata: dict[str, Any] | None = None,
        extra_notes: list[str] | None = None,
        extra_citations: list[str] | None = None,
    ) -> AgentRunStep:
        metadata = invocation_metadata or {}
        notes = [
            f"Third-party endpoint: {self._describe_endpoint(llm_config)}.",
            f"Wire API: {llm_config.wire_api}.",
        ]
        if extra_notes:
            notes.extend(extra_notes)
        citations = list(
            dict.fromkeys(
                str(citation).strip()
                for citation in [*(metadata.get("citations") or []), *(extra_citations or [])]
                if str(citation).strip()
            )
        )
        usage = metadata.get("usage")
        return AgentRunStep(
            key=role_config.role_name,
            title=role_config.title,
            description=role_config.description,
            prompt_focus=role_config.prompt_focus,
            output_summary=output_summary,
            prompt_version=role_config.prompt_version,
            status="completed",
            model=llm_config.model,
            request_id=str(metadata.get("request_id") or "") or None,
            endpoint_host=str(metadata.get("endpoint_host") or self._describe_endpoint(llm_config)),
            provider_protocol=str(metadata.get("provider_protocol") or llm_config.provider_protocol),
            wire_api=str(metadata.get("wire_api") or llm_config.wire_api),
            latency_ms=(int(metadata["latency_ms"]) if metadata.get("latency_ms") is not None else None),
            usage=(dict(usage) if isinstance(usage, dict) else None),
            retry_count=int(metadata.get("retry_count") or 0),
            request_count=int(metadata.get("request_count") or 0),
            cache_reused=bool(metadata.get("cache_reused", False)),
            notes=notes,
            citations=citations,
        )



    def _has_native_search(self, role_name: str, llm_config: LlmEndpointConfig | None) -> bool:
        """Return true only for a model whose endpoint is known to provide built-in web search."""
        if llm_config is None:
            return False
        model = str(getattr(llm_config, "model", "") or "").strip().lower()
        search_model = model == "web/grok-chat-fast" or model.startswith("console/grok-4.20")
        return role_name in {"poi_specialist", *_DIRECT_GROK_SEARCH_ROLES} and search_model

    def _role_config_uses_search_capable_grok(self, role_name: str, llm_config: LlmEndpointConfig) -> bool:
        return self._has_native_search(role_name, llm_config)

    def _rate_limit_identity(self, llm_config: LlmEndpointConfig) -> tuple[str, str, str]:
        protocol = str(getattr(llm_config, "provider_protocol", "") or "").strip().lower()
        base_url = str(getattr(llm_config, "base_url", "") or "").strip().rstrip("/").lower()
        api_key = str(getattr(llm_config, "api_key", "") or "").strip()
        return protocol, base_url, api_key


    def _build_poi_input_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        trip_request = payload.get("trip_request") if isinstance(payload.get("trip_request"), dict) else {}
        planning_brief = payload.get("planning_brief") if isinstance(payload.get("planning_brief"), dict) else {}
        poi_context = payload.get("poi_context") if isinstance(payload.get("poi_context"), dict) else {}
        tool_results = payload.get("tool_results") if isinstance(payload.get("tool_results"), dict) else {}
        return {
            "trip_request": {
                key: trip_request.get(key)
                for key in (
                    "trip_id",
                    "title",
                    "origin",
                    "destination",
                    "start_date",
                    "end_date",
                    "trip_days",
                    "budget",
                    "travelers",
                    "interests",
                    "accommodation_preference",
                    "pace",
                    "transport_mode",
                )
                if key in trip_request
            },
            "planning_brief": {
                key: planning_brief.get(key)
                for key in (
                    "destination",
                    "trip_days",
                    "budget_band",
                    "budget_priority",
                    "pace",
                    "must_have",
                    "avoid",
                    "transport",
                    "accommodation",
                    "interests",
                    "planning_constraints",
                )
                if key in planning_brief
            },
            "poi_context": {
                key: poi_context.get(key)
                for key in ("budget", "travelers", "pace", "interests", "must_have", "avoid")
                if key in poi_context
            },
            "tool_results": self._compact_poi_tool_snapshot(tool_results),
        }

    def _compact_poi_candidate_snapshot(self, value: Any, *, limit: int) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        candidates: list[dict[str, Any]] = []
        for item in value[:limit]:
            if not isinstance(item, dict):
                continue
            compact = {
                key: item.get(key)
                for key in ("name", "area", "category", "summary", "address", "opening_hours", "price_hint", "food_query")
                if item.get(key) not in (None, "", [])
            }
            if compact:
                candidates.append(compact)
        return candidates

    def _compact_poi_tool_snapshot(self, tool_results: dict[str, Any]) -> dict[str, Any]:
        if not tool_results:
            return {}
        crawl_urls = [str(item).strip() for item in tool_results.get("crawl_urls", []) if str(item).strip()] if isinstance(tool_results.get("crawl_urls"), list) else []
        grounding_docs = tool_results.get("grounding_docs") if isinstance(tool_results.get("grounding_docs"), list) else []
        return {
            "keys": sorted(str(key) for key in tool_results.keys()),
            "search_tool": tool_results.get("search_tool"),
            "search_query": tool_results.get("search_query"),
            "crawl_tool": tool_results.get("crawl_tool"),
            "crawl_urls": crawl_urls[:8],
            "citations": self._extract_urls_from_search_result(tool_results)[:12],
            "grounding_docs": self._compact_grounding_doc_snapshot(grounding_docs, limit=8),
        }

    def _compact_grounding_doc_snapshot(self, docs: list[Any], *, limit: int) -> list[dict[str, Any]]:
        compact_docs: list[dict[str, Any]] = []
        for item in docs[:limit]:
            if not isinstance(item, dict):
                continue
            compact_docs.append(
                {
                    key: item.get(key)
                    for key in ("platform", "source_type", "title", "url", "place_name", "category", "summary")
                    if item.get(key) not in (None, "", [])
                }
            )
        return compact_docs

    def _build_poi_output_snapshot(self, grounding: PoiGrounding) -> dict[str, Any]:
        return {
            "candidate_areas": [str(item).strip() for item in grounding.candidate_areas if str(item).strip()],
            "featured_pois": [
                {
                    "name": poi.name,
                    "kind": self._normalize_poi_collection_kind(poi),
                    "raw_kind": poi.kind,
                    "area": poi.area,
                    "category": poi.category,
                    "highlights": [str(item).strip() for item in poi.highlights if str(item).strip()][:4],
                    "reason": poi.reason,
                    "suggested_time": poi.suggested_time,
                    "confidence": poi.confidence,
                    "source_urls": [str(item).strip() for item in poi.source_urls if str(item).strip()],
                    "evidence_notes": [str(item).strip() for item in poi.evidence_notes if str(item).strip()],
                    "caveats": [str(item).strip() for item in poi.caveats if str(item).strip()],
                    "booking_info": poi.booking_info.model_dump(mode="json") if poi.booking_info is not None else None,
                    "visit_requirements": poi.visit_requirements.model_dump(mode="json") if poi.visit_requirements is not None else None,
                    "cuisine_or_type": poi.cuisine_or_type,
                    "price_hint": poi.price_hint,
                    "price_checked_at": poi.price_checked_at,
                    "price_valid_for": poi.price_valid_for,
                    "review_score": poi.review_score,
                    "review_count": poi.review_count,
                    "review_summary": poi.review_summary,
                    "signature_dishes": [str(item).strip() for item in poi.signature_dishes if str(item).strip()],
                    "reservation_hint": poi.reservation_hint,
                    "queue_hint": poi.queue_hint,
                }
                for poi in grounding.featured_pois
            ],
            "sequencing_hints": [str(item).strip() for item in grounding.sequencing_hints if str(item).strip()],
            "crowd_notes": [str(item).strip() for item in grounding.crowd_notes if str(item).strip()],
            "meal_strategy": [str(item).strip() for item in grounding.meal_strategy if str(item).strip()],
            "price_notes": [str(item).strip() for item in grounding.price_notes if str(item).strip()],
            "review_notes": [str(item).strip() for item in grounding.review_notes if str(item).strip()],
            "poi_risks": [str(item).strip() for item in grounding.poi_risks if str(item).strip()],
        }

    def _build_poi_debug_notes(
        self,
        input_payload: dict[str, Any],
        grounding: PoiGrounding,
        tool_results: dict[str, Any],
    ) -> list[str]:
        input_snapshot = self._build_poi_input_snapshot(input_payload)
        poi_names = [
            f"{self._normalize_poi_collection_kind(poi)}:{poi.name}@{poi.area or 'unknown'}({poi.confidence or 'low'})"
            for poi in grounding.featured_pois[:20]
        ]
        search_query = str(tool_results.get("search_query") or "").strip()
        crawl_urls = [str(item).strip() for item in tool_results.get("crawl_urls", []) if str(item).strip()] if isinstance(tool_results.get("crawl_urls"), list) else []
        citations = self._extract_urls_from_search_result(tool_results)
        return [
            f"POI input snapshot: interests={input_snapshot.get('poi_context', {}).get('interests') or []}, must_have={input_snapshot.get('poi_context', {}).get('must_have') or []}.",
            f"POI tool snapshot: search_tool={tool_results.get('search_tool') or 'none'}, search_query={search_query or 'none'}, crawl_urls={crawl_urls[:4]}, citations={citations[:5]}.",
            f"POI output snapshot: featured_pois={poi_names}.",
            "Full POI snapshots are written to job logs as helloagents_poi_specialist_input_snapshot and helloagents_poi_specialist_output_snapshot.",
        ]

    def _build_poi_research_payload(self, request: PlanningRequest, brief: PlanningBrief) -> dict[str, Any]:
        return {
            "trip_request": self._build_trip_payload(request),
            "planning_brief": brief.model_dump(mode="json"),
            "poi_context": {
                "budget": request.budget,
                "travelers": request.travelers,
                "pace": request.pace,
                "interests": [item for item in request.interests if not self._looks_like_food_interest(str(item))],
                "must_have": [item for item in brief.must_have if not self._looks_like_food_interest(str(item))],
                "avoid": brief.avoid,
            },
        }

    def _build_poi_request_task(
        self,
        *,
        destination: str,
        interests: list[str],
        must_have: list[str],
        food_interests: list[str],
        raw_user_input: str,
        pace: str,
        travelers: int | None,
        budget: float | int | None,
        use_social_context: bool,
    ) -> str:
        normalized_destination = str(destination or "").strip() or "the destination"
        preference_terms = self._normalize_search_query_terms([*must_have, *interests], limit=5)
        focus_terms: list[str] = []
        if preference_terms:
            focus_terms.append(f"Focus on {', '.join(preference_terms)}.")
        if pace:
            focus_terms.append(f"Keep the shortlist suitable for a {str(pace).strip()} pace.")
        if travelers:
            focus_terms.append(f"The plan is for {int(travelers)} traveler(s).")
        if budget is not None:
            focus_terms.append("Stay realistic about budget fit and write unknown when live pricing evidence is missing.")
        social_clause = (
            "Use broad web travel guides and Xiaohongshu-style travel references as inspiration for sightseeing POIs that are genuinely worth visiting."
            if use_social_context
            else "Use broad web travel guides and traveler-oriented references for sightseeing POIs that are genuinely worth visiting."
        )
        user_clause = f"User preference: {raw_user_input.strip()}" if str(raw_user_input or "").strip() else ""
        task_parts = [
            f"Find 6 to 10 named sightseeing POIs actually worth visiting in {normalized_destination}.",
            social_clause,
            "Cover landmarks, scenery, city-walk areas, cultural sites, viewpoints, and distinctive non-food experiences when evidence supports them.",
            "Do not include restaurants, cafes, food streets, night markets, snack shops, or meal stops.",
            *focus_terms,
            user_clause,
            "Return only the POI-grounding JSON object.",
        ]
        return " ".join(part for part in task_parts if part).strip()

    def _build_attraction_research_payload(self, request: PlanningRequest, brief: PlanningBrief) -> dict[str, Any]:
        queries = [*brief.interests, *brief.must_have, request.destination, "local highlights"]
        return {
            "trip_request": self._build_trip_payload(request),
            "planning_brief": brief.model_dump(mode="json"),
            "candidate_attractions": self._collect_poi_candidates(request, queries, limit=8),
        }

    def _build_food_research_payload(self, request: PlanningRequest, brief: PlanningBrief) -> dict[str, Any]:
        food_interests = [
            item
            for item in [*brief.interests, *brief.must_have, *request.interests]
            if self._looks_like_food_interest(str(item))
        ]
        queries = [
            *food_interests,
            f"{request.destination} food",
            f"{request.destination} restaurants",
            "local food",
            "coffee",
            "restaurant",
        ]
        return {
            "trip_request": self._build_trip_payload(request),
            "planning_brief": brief.model_dump(mode="json"),
            "food_context": {
                "budget": request.budget,
                "travelers": request.travelers,
                "pace": request.pace,
                "interests": request.interests,
                "food_interests": food_interests,
            },
            "candidate_food_pois": self._collect_food_candidates(request, queries, limit=8),
        }

    def _build_weather_research_payload(self, request: PlanningRequest, brief: PlanningBrief) -> dict[str, Any]:
        trip_days = max(1, (request.end_date - request.start_date).days + 1)
        expected_dates = [
            (request.start_date + timedelta(days=offset)).isoformat()
            for offset in range(trip_days)
        ]
        return {
            "trip_request": self._build_trip_payload(request),
            "planning_brief": brief.model_dump(mode="json"),
            "weather_segments": self._build_weather_segments(request, brief),
            "season_context": {
                "month": request.start_date.month,
                "season": self._season_for_month(request.start_date.month),
                "days": trip_days,
                "destination": request.destination,
                "weather_focus": self._weather_focus_for_month(request.start_date.month),
            },
            "search_requirements": {
                "expected_dates": expected_dates,
                "prefer_short_range_daily_forecast": True,
                "required_fields": [
                    "condition",
                    "temperature_min_c",
                    "temperature_max_c",
                    "precipitation_probability",
                    "wind",
                    "forecast_updated_at",
                    "checked_at",
                    "source_urls",
                ],
                "monthly_sources_allowed_only_outside_forecast_range": True,
            },
        }

    def _build_hotel_research_payload(self, request: PlanningRequest, brief: PlanningBrief, *, poi_collection: dict[str, Any] | None = None) -> dict[str, Any]:
        poi_areas = self._top_poi_area_names(poi_collection or {}, limit=4)
        queries = [
            brief.accommodation,
            request.accommodation_preference,
            *[f"{request.destination} {area} hotel" for area in poi_areas],
            f"{request.destination} hotel",
            "hotel",
            "stay",
        ]
        return {
            "trip_request": self._build_trip_payload(request),
            "planning_brief": brief.model_dump(mode="json"),
            "poi_collection": poi_collection or {},
            "candidate_hotels": self._collect_hotel_candidates(request, queries, limit=6),
        }

    def _build_transport_research_payload(self, request: PlanningRequest, brief: PlanningBrief, *, poi_collection: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "trip_request": self._build_trip_payload(request),
            "planning_brief": brief.model_dump(mode="json"),
            "poi_collection": poi_collection or {},
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
            "search_requirements": {
                "candidate_count_per_direction": 3,
                "static_timetable_allowed": True,
                "live_availability_required": False,
                "required_fields": [
                    "service_number",
                    "origin",
                    "destination",
                    "departure_date",
                    "departure_time",
                    "arrival_time",
                    "duration_minutes",
                    "fare_amount",
                    "schedule_checked_at",
                    "source_url",
                ],
                "flight_fields_use_same_candidate_contract": True,
            },
        }

    def _build_planner_attractions_payload(self, attraction: AttractionGrounding) -> dict[str, Any]:
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

    def _build_planner_poi_collection_payload(self, poi_collection: dict[str, Any]) -> dict[str, Any]:
        pois = poi_collection.get("pois") if isinstance(poi_collection.get("pois"), list) else []
        areas = poi_collection.get("areas") if isinstance(poi_collection.get("areas"), list) else []
        typed_pois = [item for item in pois if isinstance(item, dict)]
        attraction_pois = [item for item in typed_pois if not self._is_food_poi_dict(item)]
        food_pois = [item for item in typed_pois if self._is_food_poi_dict(item)]
        return {
            "pois": attraction_pois[:20],
            "attraction_pois": attraction_pois[:20],
            "food_pois": [],
            "areas": [item for item in areas if isinstance(item, dict)][:6],
            "top_areas": [str(item).strip() for item in poi_collection.get("top_areas", []) if str(item).strip()][:5],
            "sequencing_hints": [str(item).strip() for item in poi_collection.get("sequencing_hints", []) if str(item).strip()][:5],
            "risks": self._compress_notes(
                [
                    *[str(item).strip() for item in poi_collection.get("risks", []) if str(item).strip()],
                    *([f"Excluded {len(food_pois)} food/cafe/market POIs from planner input."] if food_pois else []),
                ],
                limit=6,
            ),
            "summary": self._compress_notes(
                [
                    *[f"Top area: {area}" for area in poi_collection.get("top_areas", [])[:3]],
                    *poi_collection.get("sequencing_hints", [])[:3],
                ],
                limit=5,
            ),
            "scheduling_policy": {
                "closed_dates_are_date_specific": True,
                "open_dates_remain_eligible": True,
                "selection_remains_planner_discretion": True,
                "do_not_treat_one_closed_date_as_global_exclusion": True,
            },
        }

    @staticmethod
    def _extract_poi_closed_dates(notes: list[str]) -> list[str]:
        """Expose date-specific closure evidence without making a POI globally unavailable."""
        closed_dates: list[str] = []
        for note in notes:
            text = str(note or "").strip()
            if not text or ("闭馆" not in text and "关闭" not in text):
                continue
            for value in re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", text):
                if value not in closed_dates:
                    closed_dates.append(value)
        return closed_dates[:16]

    def _build_planner_weather_payload(self, weather: WeatherGuidance, *, expected_days: int) -> dict[str, Any]:
        return {
            "overall_outlook": self._truncate_planner_text(weather.overall_outlook, 180),
            "source_urls": [str(url).strip() for url in weather.source_urls if str(url).strip()][:5],
            "daily_outlook": self._compact_planner_text_list(weather.daily_outlook, limit=expected_days, text_limit=120),
            "daily_forecasts": [
                {
                    "date": forecast.date.isoformat(),
                    "forecast_type": forecast.forecast_type,
                    "condition": self._truncate_planner_text(forecast.condition, 40),
                    "temperature_min_c": forecast.temperature_min_c,
                    "temperature_max_c": forecast.temperature_max_c,
                    "precipitation_probability": forecast.precipitation_probability or None,
                    "wind": self._truncate_planner_text(forecast.wind, 50),
                    "outlook": self._truncate_planner_text(forecast.outlook, 120),
                    "timing_advice": self._truncate_planner_text(forecast.timing_advice, 80),
                    "risk": self._truncate_planner_text(forecast.risk, 80),
                    "forecast_updated_at": forecast.forecast_updated_at,
                    "checked_at": forecast.checked_at,
                    "source_urls": [str(url).strip() for url in forecast.source_urls if str(url).strip()][:3],
                    "evidence_status": forecast.evidence_status,
                    "evidence_checked_at": forecast.evidence_checked_at,
                    "evidence_reason": self._truncate_planner_text(forecast.evidence_reason, 100),
                    "field_evidence": dict(forecast.field_evidence),
                }
                for forecast in weather.daily_forecasts[:expected_days]
            ],
            "segments": [
                {
                    "name": self._truncate_planner_text(segment.name, 60),
                    "date_range": self._truncate_planner_text(segment.date_range, 80),
                    "outlook": self._truncate_planner_text(segment.outlook, 120),
                    "temperature_range": self._truncate_planner_text(segment.temperature_range, 60),
                    "clothing_advice": self._compact_planner_text_list(segment.clothing_advice, limit=1, text_limit=80),
                    "outdoor_notes": self._compact_planner_text_list(segment.outdoor_notes, limit=1, text_limit=80),
                    "risks": self._compact_planner_text_list(segment.risks, limit=1, text_limit=80),
                }
                for segment in weather.segments[:2]
                if segment.name or segment.outlook or segment.temperature_range
            ],
            "packing_notes": self._compact_planner_text_list(weather.packing_notes, limit=2, text_limit=80),
            "timing_guidance": self._compact_planner_text_list(weather.timing_guidance, limit=2, text_limit=80),
            "weather_risks": self._compact_planner_text_list(weather.weather_risks, limit=2, text_limit=80),
        }

    def _build_planner_hotels_payload(
        self,
        hotel: HotelRecommendation,
        *,
        destination: str = "",
        accommodation_preference: str = "",
    ) -> dict[str, Any]:
        hotel = self._sanitize_hotel_recommendation(
            hotel,
            destination=destination,
            accommodation_preference=accommodation_preference,
        )
        all_candidates = [*hotel.hotel_candidates, *([hotel.final_recommended_hotel] if hotel.final_recommended_hotel else [])]
        conflicting_urls = self._hotel_conflicting_source_urls(all_candidates)
        verified_candidates = [
            candidate
            for candidate in hotel.hotel_candidates
            if self._is_verified_hotel_candidate(candidate, destination=destination, blocked_urls=conflicting_urls)
        ]
        final_hotel = (
            hotel.final_recommended_hotel
            if self._is_verified_hotel_candidate(hotel.final_recommended_hotel, destination=destination, blocked_urls=conflicting_urls)
            else None
        )
        if final_hotel is None and verified_candidates:
            final_hotel = verified_candidates[0]
        hotel_risks = [str(item).strip() for item in hotel.hotel_risks if str(item).strip()]
        if (hotel.final_recommended_hotel or hotel.hotel_candidates) and final_hotel is None:
            hotel_risks.append("Hotel specialist returned concrete hotel names without sufficient identity evidence; planner received area-level stay guidance only.")
        if conflicting_urls:
            hotel_risks.append("Hotel source URL mapped to conflicting hotel names; conflicting candidates were removed.")
        return {
            "recommended_areas": [str(area).strip() for area in hotel.recommended_areas if str(area).strip()][:3],
            "final_recommended_hotel": self._hotel_candidate_to_planner_dict(final_hotel) if final_hotel is not None else None,
            "hotel_candidates": [
                self._hotel_candidate_to_planner_dict(candidate)
                for candidate in verified_candidates[:4]
            ],
            "stay_strategy": [str(item).strip() for item in hotel.stay_strategy if str(item).strip()][:4],
            "budget_notes": [str(item).strip() for item in hotel.budget_notes if str(item).strip()][:4],
            "price_timeliness_notes": [str(item).strip() for item in hotel.price_timeliness_notes if str(item).strip()][:4],
            "review_notes": [str(item).strip() for item in hotel.review_notes if str(item).strip()][:4],
            "preference_match_notes": [str(item).strip() for item in hotel.preference_match_notes if str(item).strip()][:4],
            "hotel_risks": self._compress_notes(hotel_risks, limit=4),
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

    def _sanitize_hotel_recommendation(
        self,
        hotel: HotelRecommendation | None,
        *,
        destination: str,
        accommodation_preference: str = "",
    ) -> HotelRecommendation | None:
        if hotel is None:
            return None
        hotel = hotel.model_copy(deep=True)
        all_candidates = [c for c in [hotel.final_recommended_hotel, *hotel.hotel_candidates] if c]
        blocked = self._hotel_conflicting_source_urls(all_candidates)
        for candidate in all_candidates:
            self._soften_hotel_candidate_claims(candidate)
            pairs = [(url, candidate.source_page_titles[index] if index < len(candidate.source_page_titles) else "")
                     for index, url in enumerate(candidate.source_urls)]
            pairs = [(url, title) for url, title in pairs
                     if not self._is_generic_hotel_source_url(url) and url.casefold() not in blocked
                     and (url in candidate.verified_source_urls or self._hotel_entity_matches_source(candidate.name, title or url))]
            candidate.source_urls = [url for url, _ in pairs]
            candidate.source_page_titles = [title for _, title in pairs]
        verified = [
            candidate for candidate in hotel.hotel_candidates
            if self._is_verified_hotel_candidate(candidate, destination=destination)
            and self._hotel_matches_accommodation_preference(candidate, accommodation_preference)
        ]
        final = hotel.final_recommended_hotel
        original_name = final.name if final else ""
        final_is_compatible = bool(
            final is not None
            and self._is_verified_hotel_candidate(final, destination=destination)
            and self._hotel_matches_accommodation_preference(final, accommodation_preference)
        )
        type_mismatches = [
            candidate.name
            for candidate in all_candidates
            if self._is_verified_hotel_candidate(candidate, destination=destination)
            and not self._hotel_matches_accommodation_preference(candidate, accommodation_preference)
        ]
        if not final_is_compatible:
            final = verified[0] if verified else None
        if final is not None:
            final_identity = self._normalize_hotel_identity(final.name)
            verified = [
                candidate
                for candidate in verified
                if self._normalize_hotel_identity(candidate.name) != final_identity
            ]
        if final is None or final.name != original_name:
            hotel.stay_strategy = [f"住宿以{final.area}为基地，具体路线按已选酒店地址核对。"] if final else ["尚无独立核验通过的酒店；请按住宿区域确认具体酒店。"]
            hotel.hotel_risks = [
                *[str(item).strip() for item in hotel.hotel_risks if str(item).strip()],
                "酒店房价、可订房型及提前入住均需按旅行日期确认。",
            ]
            hotel.preference_match_notes = [
                f"{final.name}：{final.reason}"
            ] if final else []
        verified_count = (1 if final is not None else 0) + len(verified)
        if verified_count < 2:
            hotel.hotel_risks = [
                risk for risk in hotel.hotel_risks
                if not re.search(r"多家.*(?:酒店|住宿).*(?:核验|通过)", str(risk))
            ]
            hotel.hotel_risks.append(
                f"当前仅有{verified_count}家住宿同时通过实体与偏好类型核验，暂不提供缺少同口径证据的横向比较。"
            )
        if type_mismatches:
            hotel.hotel_risks.append(
                f"已核验但住宿类型与用户偏好不一致，未作为最终推荐：{'、'.join(dict.fromkeys(type_mismatches))}。"
            )
        if blocked:
            hotel.hotel_risks.append("不同酒店共用且无法消歧的来源已剔除；保留其他有效来源。")
        hotel.hotel_risks = list(dict.fromkeys(str(item).strip() for item in hotel.hotel_risks if str(item).strip()))
        for field in ("stay_strategy", "budget_notes", "review_notes", "preference_match_notes"):
            setattr(hotel, field, [self._soften_hotel_text(item) for item in getattr(hotel, field)])
        return hotel.model_copy(update={"final_recommended_hotel": final, "hotel_candidates": verified})

    @staticmethod
    def _soften_hotel_text(value: str) -> str:
        text = str(value or "").strip()
        text = re.sub(r"(?:完全|完美|高度)匹配", "整体符合", text)
        text = re.sub(r"步行\s*\d+\s*米内(?:即)?(?:可)?(?:到达|直达|达)", "靠近", text)
        return re.sub(r"(?i)poi", "景点", text)

    @classmethod
    def _soften_hotel_candidate_claims(cls, candidate: HotelCandidate) -> None:
        for field in ("reason", "review_summary", "preference_match"):
            setattr(candidate, field, cls._soften_hotel_text(getattr(candidate, field)))

    @classmethod
    def _hotel_matches_accommodation_preference(
        cls,
        candidate: HotelCandidate,
        accommodation_preference: str,
    ) -> bool:
        preference = str(accommodation_preference or "").casefold()
        candidate_text = f"{candidate.name} {candidate.hotel_type}".casefold()
        explicitly_requests_hotel = any(marker in preference for marker in ("酒店", "hotel", "连锁", "星级"))
        allows_alternative_lodging = any(
            marker in preference
            for marker in ("民宿", "公寓", "客栈", "青旅", "homestay", "apartment", "hostel", "b&b", "bnb")
        )
        is_alternative_lodging = any(
            marker in candidate_text
            for marker in ("民宿", "公寓", "客栈", "青旅", "homestay", "apartment", "hostel", "b&b", "bnb")
        )
        return not (explicitly_requests_hotel and not allows_alternative_lodging and is_alternative_lodging)

    def _hotel_candidate_to_planner_dict(self, candidate: HotelCandidate) -> dict[str, Any]:
        return {
            **{key: getattr(candidate, key) for key in HotelEvidence.model_fields},
            "name": candidate.name,
            "city": candidate.city,
            "area": candidate.area,
            "address": candidate.address,
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
            "source_urls": [str(item).strip() for item in candidate.source_urls if str(item).strip()][:4],
            "source_page_titles": [str(item).strip() for item in candidate.source_page_titles if str(item).strip()][:4],
        }

    def _build_stay_recommendation(
        self,
        hotel: HotelRecommendation | None,
        *,
        destination: str = "",
        accommodation_preference: str = "",
    ) -> StayRecommendation | None:
        if hotel is None:
            return None
        hotel = self._sanitize_hotel_recommendation(
            hotel,
            destination=destination,
            accommodation_preference=accommodation_preference,
        )
        all_candidates = [*hotel.hotel_candidates, *([hotel.final_recommended_hotel] if hotel.final_recommended_hotel else [])]
        conflicting_urls = self._hotel_conflicting_source_urls(all_candidates)
        verified_candidates = [
            candidate
            for candidate in hotel.hotel_candidates
            if self._is_verified_hotel_candidate(candidate, destination=destination, blocked_urls=conflicting_urls)
        ]
        final_hotel = (
            hotel.final_recommended_hotel
            if self._is_verified_hotel_candidate(hotel.final_recommended_hotel, destination=destination, blocked_urls=conflicting_urls)
            else None
        )
        if final_hotel is None and verified_candidates:
            final_hotel = verified_candidates[0]
        hotel_risks = [str(item).strip() for item in hotel.hotel_risks if str(item).strip()]
        if (hotel.final_recommended_hotel or hotel.hotel_candidates) and final_hotel is None:
            hotel_risks.append("酒店专家给出了具体酒店名称，但实体证据不足；最终行程仅保留住宿区域建议。")
        if conflicting_urls:
            hotel_risks.append("同一酒店来源链接对应了冲突的酒店名称，相关候选已移除。")
        candidates = [self._hotel_candidate_to_stay_candidate(candidate) for candidate in verified_candidates[:4]]
        source_urls = list(
            dict.fromkeys(
                url
                for candidate in [final_hotel, *verified_candidates]
                if candidate is not None
                for url in [str(item).strip() for item in candidate.source_urls if str(item).strip()]
            )
        )[:8]
        stay = StayRecommendation(
            recommended_areas=[str(area).strip() for area in hotel.recommended_areas if str(area).strip()][:3],
            final_recommended_hotel=self._hotel_candidate_to_stay_candidate(final_hotel) if final_hotel is not None else None,
            hotel_candidates=candidates,
            stay_strategy=[str(item).strip() for item in hotel.stay_strategy if str(item).strip()][:4],
            budget_notes=[str(item).strip() for item in hotel.budget_notes if str(item).strip()][:4],
            price_timeliness_notes=[str(item).strip() for item in hotel.price_timeliness_notes if str(item).strip()][:4],
            review_notes=[str(item).strip() for item in hotel.review_notes if str(item).strip()][:4],
            preference_match_notes=[str(item).strip() for item in hotel.preference_match_notes if str(item).strip()][:4],
            hotel_risks=self._compress_notes(hotel_risks, limit=4),
            source_urls=source_urls,
        )
        if stay.final_recommended_hotel is None:
            stay.budget_notes = self._compress_notes([
                *stay.budget_notes,
                "尚未核验到具体酒店及对应房价，住宿费用作为待核实项，不计入确定性预算。",
            ], limit=4)
        if not any(
            [
                stay.recommended_areas,
                stay.final_recommended_hotel,
                stay.hotel_candidates,
                stay.stay_strategy,
                stay.budget_notes,
                stay.price_timeliness_notes,
                stay.review_notes,
                stay.preference_match_notes,
                stay.hotel_risks,
                stay.source_urls,
            ]
        ):
            return None
        return stay

    def _hotel_candidate_to_stay_candidate(self, candidate: HotelCandidate) -> StayHotelCandidate:
        display_aliases = {
            "moderate": "中等价位",
            "budget": "经济型",
            "premium": "较高价位",
            "current search snapshot": "本次搜索快照",
            "current-search snapshot": "本次搜索快照",
            "medium": "中等",
            "high": "较高",
            "low": "较低",
            "dynamic": "动态价格",
            "unknown": "待核实",
        }

        def display(value: str) -> str | None:
            normalized = str(value or "").strip()
            return display_aliases.get(normalized.casefold(), normalized) or None

        return StayHotelCandidate(
            **{key: getattr(candidate, key) for key in HotelEvidence.model_fields},
            name=candidate.name,
            area=candidate.area or None,
            hotel_type=candidate.hotel_type or None,
            reason=candidate.reason or None,
            price_hint=display(candidate.price_hint),
            price_checked_at=display(candidate.price_checked_at),
            price_valid_for=candidate.price_valid_for or None,
            review_score=candidate.review_score or None,
            review_count=candidate.review_count or None,
            review_summary=candidate.review_summary or None,
            preference_match=candidate.preference_match or None,
            booking_confidence=display(candidate.booking_confidence),
            caveats=[str(item).strip() for item in candidate.caveats if str(item).strip()][:4],
            source_urls=[str(item).strip() for item in candidate.source_urls if str(item).strip()][:4],
        )

    @staticmethod
    def _normalize_hotel_identity(value: Any) -> str:
        return normalize_identity(str(value or ""))

    @classmethod
    def _hotel_entity_matches_source(cls, name: str, source: str) -> bool:
        normalized_name = cls._normalize_hotel_identity(name)
        normalized_source = cls._normalize_hotel_identity(source)
        if not normalized_name or not normalized_source:
            return False
        if normalized_name in normalized_source:
            return True
        return False

    @staticmethod
    def _is_generic_hotel_source_url(value: str) -> bool:
        try:
            parsed = urlparse(str(value or "").strip())
        except ValueError:
            return True
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return True
        path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/").casefold()
        if not path or path in {"/hotel", "/hotels", "/search", "/list", "/city"}:
            return True
        return any(token in path for token in ("/search", "/searchresult", "/list/", "/city/"))

    @classmethod
    def _hotel_conflicting_source_urls(cls, candidates: list[HotelCandidate | None]) -> set[str]:
        url_names: dict[str, set[str]] = {}
        for candidate in candidates:
            if candidate is None:
                continue
            name_key = cls._normalize_hotel_identity(candidate.name)
            if not name_key:
                continue
            for raw_url in candidate.source_urls:
                url = str(raw_url or "").strip().casefold()
                if url:
                    url_names.setdefault(url, set()).add(name_key)
        return {url for url, names in url_names.items() if len(names) > 1}

    @classmethod
    def _is_verified_hotel_candidate(
        cls,
        candidate: HotelCandidate | None,
        *,
        destination: str = "",
        blocked_urls: set[str] | None = None,
    ) -> bool:
        if candidate is None or not candidate.name.strip() or not candidate.city.strip():
            return False
        if candidate.identity_status not in {"page_verified", "model_reported"}:
            return False
        source_urls = [str(url).strip() for url in candidate.source_urls if str(url).strip()]
        blocked = blocked_urls or set()
        usable = [(url, candidate.source_page_titles[index] if index < len(candidate.source_page_titles) else "")
                  for index, url in enumerate(source_urls)
                  if not cls._is_generic_hotel_source_url(url) and url.casefold() not in blocked]
        if not usable:
            return False
        if destination:
            destination_key = cls._normalize_hotel_identity(destination)
            city_key = cls._normalize_hotel_identity(candidate.city)
            if not destination_key or (destination_key not in city_key and city_key not in destination_key):
                return False
        return any(url in candidate.verified_source_urls or cls._hotel_entity_matches_source(candidate.name, title or url)
                   for url, title in usable)

    def _build_planner_transport_payload(self, transport: TransportGuidance) -> dict[str, Any]:
        minimum_departure_buffer = max(
            transport.minimum_departure_buffer_minutes,
            transport.departure_transfer_minutes + transport.station_buffer_minutes + transport.luggage_buffer_minutes,
        )
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
            "service_candidates": [candidate.model_dump(mode="json") for candidate in transport.service_candidates[:6]],
            "legs": [leg.model_dump(mode="json") for leg in transport.legs[:6]],
            "arrival_strategy": [str(item).strip() for item in transport.arrival_strategy if str(item).strip()][:4],
            "local_mobility_strategy": [str(item).strip() for item in transport.local_mobility_strategy if str(item).strip()][:4],
            "pass_or_ticket_notes": [str(item).strip() for item in transport.pass_or_ticket_notes if str(item).strip()][:4],
            "transport_risks": [str(item).strip() for item in transport.transport_risks if str(item).strip()][:4],
            "sequencing_constraints": [str(item).strip() for item in transport.sequencing_constraints if str(item).strip()][:4],
            "estimated_intercity_cost": transport.estimated_intercity_cost,
            "estimated_local_transport_cost": transport.estimated_local_transport_cost,
            "departure_transfer_minutes": transport.departure_transfer_minutes,
            "station_buffer_minutes": transport.station_buffer_minutes,
            "luggage_buffer_minutes": transport.luggage_buffer_minutes,
            "minimum_departure_buffer_minutes": minimum_departure_buffer,
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

    def _is_food_poi_kind_value(self, value: str) -> bool:
        normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        return normalized in {
            "food",
            "restaurant",
            "cafe",
            "coffee",
            "market",
            "night_market",
            "snack",
            "dining",
            "bar",
            "bakery",
            "tea",
        }

    def _is_food_poi(self, poi: ResearchPoi | FoodPoi | None) -> bool:
        if poi is None:
            return False
        if isinstance(poi, FoodPoi):
            return True
        if self._is_food_poi_kind_value(getattr(poi, "kind", "")):
            return True
        category = getattr(poi, "category", "")
        cuisine = getattr(poi, "cuisine_or_type", "")
        return self._looks_like_food_interest(f"{category} {cuisine}")

    def _is_food_poi_dict(self, poi: dict[str, Any]) -> bool:
        kind = str(poi.get("kind") or "").strip()
        if self._is_food_poi_kind_value(kind):
            return True
        category = str(poi.get("category") or "").strip()
        cuisine = str(poi.get("cuisine_or_type") or "").strip()
        return self._looks_like_food_interest(f"{category} {cuisine}")

    def _normalize_poi_collection_kind(self, poi: ResearchPoi) -> str:
        raw_kind = str(poi.kind or "").strip().lower().replace("-", "_").replace(" ", "_")
        if self._is_food_poi(poi):
            if raw_kind in {"market", "night_market", "cafe", "coffee"}:
                return raw_kind
            return "food"
        if raw_kind in {"experience", "mixed_area", "mixed-area"}:
            return raw_kind.replace("_", "-")
        return "attraction"

    def _build_poi_collection(
        self,
        poi_grounding: PoiGrounding,
    ) -> dict[str, Any]:
        pois: list[dict[str, Any]] = []
        area_stats: dict[str, dict[str, Any]] = {}

        def record_area(area_name: str, kind: str, poi_name: str | None = None) -> None:
            area = str(area_name or "").strip() or "Unspecified area"
            key = area.casefold()
            stats = area_stats.setdefault(
                key,
                {
                    "name": area,
                    "attraction_count": 0,
                    "food_count": 0,
                    "sample_pois": [],
                },
            )
            if kind == "attraction":
                stats["attraction_count"] += 1
            if kind == "food":
                stats["food_count"] += 1
            if poi_name and poi_name not in stats["sample_pois"]:
                stats["sample_pois"].append(poi_name)

        for area in poi_grounding.candidate_areas:
            if str(area).strip():
                record_area(str(area), "attraction")
        for poi in poi_grounding.featured_pois:
            collection_kind = self._normalize_poi_collection_kind(poi)
            area_kind = "food" if self._is_food_poi(poi) else "attraction"
            record_area(poi.area, area_kind, poi.name)
            source_urls = list(
                dict.fromkeys(
                    [
                        *[str(item).strip() for item in poi.source_urls if str(item).strip()],
                        *[str(item).strip() for item in (poi.booking_info.source_urls if poi.booking_info else []) if str(item).strip()],
                    ]
                )
            )
            entry: dict[str, Any] = {
                "kind": collection_kind,
                "name": poi.name,
                "area": poi.area,
                "highlights": [str(item).strip() for item in poi.highlights if str(item).strip()][:4],
                "reason": poi.reason,
                "suggested_time": poi.suggested_time,
                "confidence": poi.confidence or "low",
                "source_url": source_urls[0] if source_urls else "",
                "source_urls": source_urls[:3],
                "evidence_notes": [str(item).strip() for item in poi.evidence_notes if str(item).strip()][:5],
                "caveats": [str(item).strip() for item in poi.caveats if str(item).strip()][:5],
                "booking_info": poi.booking_info.model_dump(mode="json") if poi.booking_info is not None else None,
                "visit_requirements": poi.visit_requirements.model_dump(mode="json") if poi.visit_requirements is not None else None,
            }
            closed_dates = self._extract_poi_closed_dates(
                [
                    *entry["evidence_notes"],
                    *entry["caveats"],
                    *(
                        poi.booking_info.notes
                        if poi.booking_info is not None and poi.booking_info.notes
                        else []
                    ),
                    *(
                        poi.visit_requirements.notes
                        if poi.visit_requirements is not None and poi.visit_requirements.notes
                        else []
                    ),
                ]
            )
            if closed_dates:
                entry["closed_dates"] = closed_dates
                entry["scheduling_note"] = "仅 closed_dates 所列日期不可安排；其他日期仍作为普通候选，由规划器按整体质量决定是否采用。"
            if self._is_food_poi(poi):
                entry["highlights"] = [
                    *[str(item).strip() for item in poi.highlights if str(item).strip()],
                    *[str(item).strip() for item in poi.signature_dishes if str(item).strip()],
                ][:4]
                if poi.reservation_hint:
                    entry["reservation_hint"] = poi.reservation_hint
                if poi.queue_hint:
                    entry["queue_hint"] = poi.queue_hint
            pois.append(entry)

        areas = []
        for stats in area_stats.values():
            area_kind = "mixed-area" if stats["attraction_count"] and stats["food_count"] else "attraction" if stats["attraction_count"] else "food"
            areas.append(
                {
                    "name": stats["name"],
                    "kind": area_kind,
                    "attraction_count": stats["attraction_count"],
                    "food_count": stats["food_count"],
                    "sample_pois": stats["sample_pois"][:5],
                    "score": stats["attraction_count"] * 2 + stats["food_count"] * 2 + (1 if area_kind == "mixed-area" else 0),
                }
            )
        areas.sort(key=lambda item: (-int(item["score"]), str(item["name"]).casefold()))
        return {
            "pois": pois[:20],
            "areas": areas[:8],
            "top_areas": [str(item["name"]) for item in areas[:5]],
            "sequencing_hints": [str(item).strip() for item in poi_grounding.sequencing_hints if str(item).strip()][:6],
            "meal_strategy": [str(item).strip() for item in poi_grounding.meal_strategy if str(item).strip()][:6],
            "food_price_notes": [str(item).strip() for item in poi_grounding.price_notes if str(item).strip()][:5],
            "review_notes": [str(item).strip() for item in poi_grounding.review_notes if str(item).strip()][:5],
            "risks": [str(item).strip() for item in poi_grounding.poi_risks if str(item).strip()][:8],
        }

    def _top_poi_area_names(self, poi_collection: dict[str, Any], *, limit: int) -> list[str]:
        areas = poi_collection.get("areas") if isinstance(poi_collection.get("areas"), list) else []
        names = [
            str(item.get("name") or "").strip()
            for item in areas
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        if not names:
            pois = poi_collection.get("pois") if isinstance(poi_collection.get("pois"), list) else []
            names = [
                str(item.get("area") or "").strip()
                for item in pois
                if isinstance(item, dict) and str(item.get("area") or "").strip()
            ]
        return list(dict.fromkeys(names))[:limit]

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

    def _truncate_planner_text(self, value: Any, limit: int) -> str:
        normalized = " ".join(str(value or "").split())
        if not normalized or limit <= 0:
            return ""
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit].rstrip()}..."

    def _compact_planner_text_list(self, values: list[Any], *, limit: int, text_limit: int) -> list[str]:
        compact: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = self._truncate_planner_text(value, text_limit)
            if not normalized:
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            compact.append(normalized)
            if len(compact) >= limit:
                break
        return compact


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
                _LOGGER.warning("PlanningCore role=%s provider=%s unable_to_list_tools=%s", role_name, config.provider, exc)
                continue
            _LOGGER.debug("PlanningCore role=%s provider=%s available_tools=%s", role_name, config.provider, sorted(available_tools))
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
            candidates = ("answer", "web_search", "search") if allow_answer else ("web_search",)
            return self._pick_mcp_tool(available_tools, *candidates)
        candidates = ("search", "answer") if allow_answer else ("search",)
        return self._pick_mcp_tool(available_tools, *candidates)

    def _pick_fetch_tool(self, client: ConfiguredSearchGateway, available_tools: set[str]) -> str | None:
        if self._is_groksearch_provider(client):
            return self._pick_mcp_tool(available_tools, "web_fetch", "contents")
        return self._pick_mcp_tool(available_tools, "contents", "web_fetch")

    def _should_fetch_grounding_pages(self, client: ConfiguredSearchGateway, search_tool: str | None) -> bool:
        if search_tool == "answer":
            return False
        return not self._is_groksearch_provider(client)

    def _role_uses_direct_grok_search_model(self, role_name: str) -> bool:
        if role_name not in _DIRECT_GROK_SEARCH_ROLES or self._llm_config is None:
            return False
        return self._has_native_search(role_name, self._llm_config.config_for_role(role_name))

    def _augment_payload_with_tool_results(self, role_name: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        if role_name == "poi_specialist":
            poi_config = self._llm_config.config_for_role(role_name) if self._llm_config is not None else None
            if self._has_native_search(role_name, poi_config):
                self._log_event(
                    "helloagents_poi_tool_collection_skipped",
                    message="POI specialist model has native search capability; skipping external MCP tool injection.",
                    role=role_name,
                    external_tool_collection=False,
                    native_search_allowed=True,
                    poi_specialist_uses_search=True,
                )
                input_payload["tool_results"] = {"poi_source": "native_search"}
                return input_payload
            self._log_event(
                "helloagents_poi_tool_collection_enabled",
                message="POI specialist model has no native search capability; collecting MCP search evidence.",
                role=role_name,
                external_tool_collection=True,
                native_search_allowed=False,
            )
        elif self._role_uses_direct_grok_search_model(role_name):
            config = self._llm_config.config_for_role(role_name) if self._llm_config is not None else None
            self._log_event(
                "helloagents_direct_grok_tool_collection_skipped",
                message="Role uses Grok directly as its search-capable model; skipping MCP search tool injection.",
                role=role_name,
                model=getattr(config, "model", None),
            )
            return input_payload
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
                _LOGGER.warning("PlanningCore role=%s provider=%s tool_collection_failed=%s", role_name, self._search_provider(client), exc)
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
            _LOGGER.warning("PlanningCore role=%s tool_collection_failed=%s", role_name, last_error)
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
        if role_name == "poi_specialist":
            return self._collect_poi_tool_results(client, available_tools, input_payload)
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

    def _normalize_search_query_terms(self, values: list[Any], *, limit: int) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            candidate = str(value or "").strip()
            key = candidate.casefold()
            if not candidate or key in seen:
                continue
            seen.add(key)
            normalized.append(candidate)
        return normalized[:limit]

    def _build_poi_search_query(self, input_payload: dict[str, Any]) -> tuple[str, list[str], list[str]]:
        trip_request = input_payload.get("trip_request") if isinstance(input_payload.get("trip_request"), dict) else {}
        brief = input_payload.get("planning_brief") if isinstance(input_payload.get("planning_brief"), dict) else {}
        poi_context = input_payload.get("poi_context") if isinstance(input_payload.get("poi_context"), dict) else {}
        poi_request = input_payload.get("poi_request") if isinstance(input_payload.get("poi_request"), dict) else {}
        candidate_pois = input_payload.get("candidate_pois") if isinstance(input_payload.get("candidate_pois"), list) else []
        destination = str(trip_request.get("destination") or brief.get("destination") or "").strip()
        raw_user_input = str(trip_request.get("raw_user_input") or brief.get("raw_user_input") or "").strip()
        explicit_task = str(poi_request.get("task") or "").strip()
        interests = [
            item
            for item in self._normalize_search_query_terms(
                [
                    *poi_context.get("must_have", []),
                    *poi_context.get("interests", []),
                    *brief.get("interests", []),
                ],
                limit=6,
            )
            if not self._looks_like_food_interest(str(item))
        ]
        candidate_names = self._normalize_search_query_terms(
            [
                item.get("name")
                for item in candidate_pois
                if isinstance(item, dict)
            ],
            limit=6,
        )
        query_terms: list[str] = []
        if destination:
            query_terms.extend([destination, "值得去 POI", "旅行攻略"])
        else:
            query_terms.extend(["目的地", "值得去 POI", "旅行攻略"])
        if self._current_xhs_source_enabled:
            query_terms.append("小红书")
        query_terms.extend(interests[:4])
        query_terms.extend(["city walk", "景点", "自然风景", "文化地标"])
        query_terms.extend(candidate_names)
        if raw_user_input and not candidate_names:
            query_terms.append(raw_user_input)
        elif explicit_task and not (raw_user_input or candidate_names):
            query_terms.append(explicit_task)
        query = " ".join(self._normalize_search_query_terms(query_terms, limit=18)).strip()
        if len(query) > 360:
            query = f"{query[:357].rstrip()}..."
        return query, interests, candidate_names

    def _build_poi_answer_query(self, search_query: str) -> str:
        query = (
            f"{search_query}\n"
            "任务：综合可靠来源，返回不超过 12 个以游玩为主的具名景点 POI。覆盖地标、自然风景、古城/街区、文化场馆、观景点和非餐饮体验；"
            "不要包含餐厅、咖啡馆、夜市、美食街、小吃店、菜市场或饭点。"
            "每项只需要名称、区域、类别、推荐理由、建议时段、票务/开放/预约提示和来源链接。缺少证据写 unknown，不要编造精确数字。"
        ).strip()
        if len(query) > 900:
            query = f"{query[:897].rstrip()}..."
        return query

    def _collect_poi_tool_results(self, client: ConfiguredSearchGateway, available_tools: set[str], input_payload: dict[str, Any]) -> dict[str, Any]:
        destination = str(
            (
                input_payload.get("trip_request", {}).get("destination")
                if isinstance(input_payload.get("trip_request"), dict)
                else ""
            )
            or (
                input_payload.get("planning_brief", {}).get("destination")
                if isinstance(input_payload.get("planning_brief"), dict)
                else ""
            )
            or ""
        ).strip()
        query, interests, _candidate_names = self._build_poi_search_query(input_payload)

        # POI 角色现在由主 LLM 直接做候选筛选与结构化，搜索工具只提供轻量证据和引用。
        is_groksearch = self._is_groksearch_provider(client)
        self._log_event(
            "helloagents_poi_tool_selection_debug",
            message="POI specialist tool selection.",
            role="poi_specialist",
            is_groksearch_provider=is_groksearch,
            available_tools=sorted(available_tools),
            search_provider=self._search_provider(client),
        )
        search_tool = self._pick_search_tool(client, available_tools)
        if search_tool is None and is_groksearch:
            search_tool = self._pick_mcp_tool(available_tools, "answer", "search")
        self._log_event(
            "helloagents_poi_tool_picked",
            message="POI specialist picked tool.",
            role="poi_specialist",
            picked_tool=search_tool,
        )
        if search_tool is None:
            return {}

        search_query = self._build_poi_answer_query(query) if search_tool == "answer" else query
        try:
            search_result = self._call_search_like_tool(client, search_tool, search_query, 10, role_name="poi_specialist")
        except Exception as exc:
            _LOGGER.warning("PlanningCore role=poi_specialist tool=%s failed=%s", search_tool, exc)
            return {}
        payload: dict[str, Any] = {
            "search_tool": search_tool,
            "search_query": search_query,
            "poi_source": "search_evidence",
        }
        if search_tool == "answer":
            payload["research_tool"] = search_tool
            payload["answer"] = search_result
        else:
            payload["search"] = search_result
        citations = self._extract_urls_from_search_result(search_result)
        if citations:
            payload["citations"] = citations

        try:
            grounding_docs = self._collect_grounding_docs(query, destination, interests=interests, social_context="poi")
        except Exception as exc:
            _LOGGER.warning("PlanningCore role=poi_specialist grounding_failed=%s", exc)
        else:
            if grounding_docs:
                payload["grounding_docs"] = grounding_docs
        return payload

    def _collect_weather_tool_results(self, client: ConfiguredSearchGateway, available_tools: set[str], input_payload: dict[str, Any]) -> dict[str, Any]:
        trip_request = input_payload.get("trip_request") if isinstance(input_payload.get("trip_request"), dict) else {}
        segments = input_payload.get("weather_segments") if isinstance(input_payload.get("weather_segments"), list) else []
        destination = str(trip_request.get("destination") or "").strip()
        start_date = str(trip_request.get("start_date") or "").strip()
        end_date = str(trip_request.get("end_date") or "").strip()
        segment_names = [
            str(item.get("name") or "").strip()
            for item in segments
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        segment_focus = f" across {', '.join(segment_names[:3])}" if len(segment_names) > 1 else ""
        search_query = (
            f"Travel weather guidance for {destination}{segment_focus} between {start_date} and {end_date}, "
            "including expected temperatures, rain risk, and packing advice"
        ).strip()
        research_instructions = (
            f"Provide planning-oriented weather guidance for travel in {destination}{segment_focus} from {start_date} to {end_date}. "
            "Summarize likely temperature patterns, rain or storm risk, daylight or timing considerations, "
            "practical packing advice, and city-level or area-level differences when segments are provided. Include source-backed detail."
        ).strip()

        if self._is_groksearch_provider(client):
            search_tool = self._pick_search_tool(client, available_tools, allow_answer=True)
            if search_tool is None:
                return {}
            try:
                search_result = self._call_search_like_tool(client, search_tool, search_query, 5, role_name="weather_specialist")
            except Exception as exc:
                _LOGGER.warning("PlanningCore role=weather_specialist tool=%s failed=%s", search_tool, exc)
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
                _LOGGER.warning("PlanningCore role=weather_specialist tool=%s failed=%s", research_tool, exc)
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
                            _LOGGER.warning("PlanningCore role=weather_specialist tool=%s failed=%s", fallback_tool, exc)
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
            _LOGGER.warning("PlanningCore role=weather_specialist tool=%s failed=%s", answer_tool, exc)
            return {}
        return {"research_tool": answer_tool, "answer": answer_result, "citations": self._extract_urls_from_search_result(answer_result)}

    def _collect_hotel_tool_results(self, client: ConfiguredSearchGateway, available_tools: set[str], input_payload: dict[str, Any]) -> dict[str, Any]:
        trip_request = input_payload.get("trip_request") if isinstance(input_payload.get("trip_request"), dict) else {}
        brief = input_payload.get("planning_brief") if isinstance(input_payload.get("planning_brief"), dict) else {}
        candidate_hotels = input_payload.get("candidate_hotels") if isinstance(input_payload.get("candidate_hotels"), list) else []
        poi_collection = input_payload.get("poi_collection") if isinstance(input_payload.get("poi_collection"), dict) else {}
        destination = str(trip_request.get("destination") or brief.get("destination") or "").strip()
        stay_pref = str(trip_request.get("accommodation_preference") or brief.get("accommodation") or "").strip()
        candidate_names = [
            str(item.get("name") or "").strip()
            for item in candidate_hotels
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        poi_areas = self._top_poi_area_names(poi_collection, limit=4)
        query = (
            f"Travel planning pages about staying in {destination} with a preference for {stay_pref or 'well-located hotels'}, "
            f"near activity and food POI clusters {', '.join(poi_areas) or destination}, "
            f"focusing on transit-friendly areas and hotels such as {', '.join(candidate_names[:2]) or 'well-reviewed stays'}"
        ).strip()
        search_tool = self._pick_search_tool(client, available_tools, allow_answer=True)
        crawl_tool = self._pick_fetch_tool(client, available_tools) if self._should_fetch_grounding_pages(client, search_tool) else None
        if search_tool is None:
            return {}

        payload: dict[str, Any] = {}
        search_result: dict[str, Any] | None = None
        if search_tool is not None:
            try:
                search_result = self._call_search_like_tool(client, search_tool, query, 6, role_name="hotel_specialist")
            except Exception as exc:
                _LOGGER.warning("PlanningCore role=hotel_specialist tool=%s failed=%s", search_tool, exc)
                return {}
            payload["search_tool"] = search_tool
            payload["search_query"] = query
            if search_tool == "answer":
                payload["research_tool"] = search_tool
                payload["answer"] = search_result
            else:
                payload["search"] = search_result
            citations = self._extract_urls_from_search_result(search_result)
            if citations:
                payload["citations"] = citations

        try:
            grounding_docs = self._collect_grounding_docs(query, destination, interests=[], social_context="hotel")
        except Exception as exc:
            _LOGGER.warning("PlanningCore role=hotel_specialist grounding_failed=%s", exc)
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
                    _LOGGER.warning("PlanningCore role=hotel_specialist tool=%s failed=%s", crawl_tool, exc)
                    return payload
                payload["crawl_urls"] = crawl_urls
                return payload

        return payload

    def _collect_transport_tool_results(self, client: ConfiguredSearchGateway, available_tools: set[str], input_payload: dict[str, Any]) -> dict[str, Any]:
        trip_request = input_payload.get("trip_request") if isinstance(input_payload.get("trip_request"), dict) else {}
        brief = input_payload.get("planning_brief") if isinstance(input_payload.get("planning_brief"), dict) else {}
        poi_collection = input_payload.get("poi_collection") if isinstance(input_payload.get("poi_collection"), dict) else {}
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
        poi_areas = self._top_poi_area_names(poi_collection, limit=4)
        if poi_areas:
            query = f"{query}, covering activity and food areas: {', '.join(poi_areas)}"

        search_tool = self._pick_search_tool(client, available_tools, allow_answer=True)
        fetch_tool = self._pick_fetch_tool(client, available_tools) if self._should_fetch_grounding_pages(client, search_tool) else None
        if search_tool is None:
            return {}

        payload: dict[str, Any] = {}
        try:
            search_result = self._call_search_like_tool(client, search_tool, query, 6, role_name="transport_specialist")
        except Exception as exc:
            _LOGGER.warning("PlanningCore role=transport_specialist tool=%s failed=%s", search_tool, exc)
            return {}

        payload["search_tool"] = search_tool
        payload["search_query"] = query
        if search_tool == "answer":
            payload["research_tool"] = search_tool
            payload["answer"] = search_result
        else:
            payload["search"] = search_result
        citations = self._extract_urls_from_search_result(search_result)

        if fetch_tool is not None and citations:
            crawl_urls = citations[:2]
            payload["crawl_tool"] = fetch_tool
            payload["crawl_urls"] = crawl_urls
            try:
                crawl_result = self._call_crawling_tool(client, fetch_tool, crawl_urls, role_name="transport_specialist")
            except Exception as exc:
                _LOGGER.warning("PlanningCore role=transport_specialist tool=%s failed=%s", fetch_tool, exc)
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
            _LOGGER.warning("PlanningCore role=transport_specialist grounding_failed=%s", exc)
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
            f"Travel transport planning {route} for outbound date {start_date} and return date {end_date}, "
            f"focusing on {mode_focus}. Find 2 to 3 named service candidates in each direction with the exact station or airport, "
            f"service number, scheduled departure and arrival times, duration, reference fare, route or date-specific source URL, "
            f"and search timestamp for {travelers} traveler(s). Static timetables are acceptable; live availability may be unknown"
        ).strip()

    def _transport_focus_for_mode(self, transport_mode: str) -> str:
        normalized = (transport_mode or "").strip().lower()
        if normalized in {"rail", "train", "transit", "subway", "bus"}:
            return "high-speed rail schedules, exact train numbers, station identity, station transfers, and local transit"
        if normalized in {"flight", "air", "plane", "aviation"}:
            return "scheduled flights, exact flight numbers, airport identity, planned takeoff and landing times, and airport transfers"
        if normalized in {"car", "drive", "driving"}:
            return "car rental, toll, parking, and airport or station transfer costs"
        if normalized in {"walking", "walk"}:
            return "walkable area clustering with realistic transit backup options"
        if normalized in {"mixed", "any", "flexible", ""}:
            return "a practical comparison of high-speed rail and scheduled flights, including exact stations or airports and local transfers"
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
                max_poll_attempts = 30
                poll_interval_seconds = 5.0
                for attempt in range(max_poll_attempts):
                    latest_result = self._call_mcp_tool(
                        client,
                        "deep_researcher_check",
                        {"researchId": research_id},
                        role_name=role_name,
                    )
                    status = self._research_status(latest_result)
                    if status in {"completed", "complete", "done", "failed", "error"}:
                        break
                    if attempt < max_poll_attempts - 1:
                        time.sleep(poll_interval_seconds)
            final_status = self._research_status(latest_result) or self._research_status(start_result)
            return {
                "tool_name": tool_name,
                "research_id": research_id,
                "status": final_status,
                "deep_research_completed": final_status in {"completed", "complete", "done"},
                "start": start_result,
                "result": latest_result,
            }
        result = self._call_mcp_tool(
            client,
            tool_name,
            {
                "instructions": instructions,
                "wait_for_completion": True,
                "poll_interval_seconds": 5.0,
                "max_wait_seconds": 150.0,
            },
            role_name=role_name,
        )
        status = self._research_status(result)
        return {
            "tool_name": tool_name,
            "status": status,
            "deep_research_completed": status in {"completed", "complete", "done"},
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

    def _build_mcp_tool_response_snapshot(self, result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            compact_result = self._compact_tool_value_for_prompt(result, max_list_items=5, text_limit=800)
            return {"result": compact_result} if compact_result not in (None, "", [], {}) else {}

        snapshot: dict[str, Any] = {"keys": sorted(str(key) for key in result.keys())}
        for key in ("session_id", "sessionId", "request_id", "requestId", "id", "researchId"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                snapshot[key] = value.strip()

        for key in ("answer", "text", "content", "summary", "report"):
            value = result.get(key)
            if value in (None, "", [], {}):
                continue
            snapshot[key] = self._compact_tool_value_for_prompt(value, max_list_items=3, text_limit=1000)

        source_items: list[dict[str, Any]] = []
        for key in ("sources", "results"):
            items = result.get(key)
            if not isinstance(items, list):
                continue
            for item in items[:5]:
                if not isinstance(item, dict):
                    continue
                compact_item = {
                    field: item.get(field)
                    for field in ("title", "name", "url", "link", "source", "snippet", "summary")
                    if item.get(field) not in (None, "", [], {})
                }
                if compact_item:
                    source_items.append(compact_item)
        if source_items:
            snapshot["sources"] = source_items[:5]

        citations = self._extract_urls_from_search_result(result)[:12]
        if citations:
            snapshot["citations"] = citations
        return {key: value for key, value in snapshot.items() if value not in (None, "", [], {})}

    def _call_mcp_tool(self, client: ConfiguredSearchGateway, tool_name: str, arguments: dict[str, Any], *, role_name: str) -> dict[str, Any]:
        _LOGGER.debug("PlanningCore role=%s tool=%s args=%s", role_name, tool_name, json.dumps(arguments, ensure_ascii=False))
        argument_bytes = len(json.dumps(arguments, ensure_ascii=False, default=str).encode("utf-8"))
        self._log_event(
            "helloagents_mcp_tool_request",
            message="MCP tool request prepared.",
            role=role_name,
            tool=tool_name,
            argument_bytes=argument_bytes,
            arguments=self._compact_tool_value_for_prompt(arguments, max_list_items=8, text_limit=1800),
        )
        started = time.perf_counter()
        try:
            result = client.call_operation(tool_name, arguments)
        except Exception as exc:
            self._log_event(
                "helloagents_mcp_tool_failed",
                message="MCP tool request failed.",
                level="ERROR",
                role=role_name,
                tool=tool_name,
                elapsed_seconds=round(max(time.perf_counter() - started, 0.0), 3),
                error=str(exc).strip() or exc.__class__.__name__,
            )
            raise
        response_bytes = len(json.dumps(result, ensure_ascii=False, default=str).encode("utf-8"))
        self._log_event(
            "helloagents_mcp_tool_response",
            message="MCP tool response received.",
            role=role_name,
            tool=tool_name,
            elapsed_seconds=round(max(time.perf_counter() - started, 0.0), 3),
            response_bytes=response_bytes,
            response=self._build_mcp_tool_response_snapshot(result),
        )
        return result

    def _call_search_like_tool(self, client: ConfiguredSearchGateway, tool_name: str, query: str, num_results: int, *, role_name: str) -> dict[str, Any]:
        if tool_name == "web_search":
            return self._call_mcp_tool(client, tool_name, {"query": query}, role_name=role_name)
        if tool_name == "answer":
            return self._call_mcp_tool(client, tool_name, {"query": query, "include_text": True}, role_name=role_name)
        return self._call_mcp_tool(client, tool_name, {"query": query, "num_results": num_results, "include_text": True}, role_name=role_name)

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

    def _collect_food_candidates(self, request: PlanningRequest, queries: list[str], limit: int) -> list[dict[str, Any]]:
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
                payload = self._poi_candidate_to_dict(detail)
                payload["food_query"] = normalized_query
                candidates.append(payload)
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

    def _build_weather_segments(self, request: PlanningRequest, brief: PlanningBrief) -> list[dict[str, Any]]:
        raw_values = [request.destination, brief.destination]
        names: list[str] = []
        for raw_value in raw_values:
            for candidate in self._split_destination_segments(raw_value):
                if candidate and candidate.casefold() not in {name.casefold() for name in names}:
                    names.append(candidate)
        if not names and request.destination:
            names.append(request.destination)
        date_range = f"{request.start_date.isoformat()} to {request.end_date.isoformat()}"
        cross_region = len(names) > 1
        return [
            {
                "name": name,
                "date_range": date_range,
                "role": "destination_segment",
                "cross_region": cross_region,
            }
            for name in names[:3]
        ]

    def _split_destination_segments(self, value: str) -> list[str]:
        raw_value = str(value or "").strip()
        if not raw_value:
            return []
        normalized = re.sub(r"\s+(?:and|to)\s+", ",", raw_value, flags=re.IGNORECASE)
        parts = re.split(r"\s*(?:,|/|;|\||->|=>|\+|&|、|，|；|和|及|到|至)\s*", normalized)
        results: list[str] = []
        for part in parts:
            candidate = part.strip(" -\t\r\n")
            if not candidate:
                continue
            if candidate.casefold() in {item.casefold() for item in results}:
                continue
            results.append(candidate)
        return results or [raw_value]

    def _looks_like_food_interest(self, value: str) -> bool:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return False
        food_keywords = (
            "food",
            "meal",
            "restaurant",
            "cafe",
            "coffee",
            "tea",
            "dessert",
            "snack",
            "market",
            "dining",
            "ramen",
            "sushi",
            "noodle",
            "bar",
            "美食",
            "餐",
            "咖啡",
            "小吃",
            "夜市",
            "甜品",
        )
        return any(keyword in normalized for keyword in food_keywords)

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

    def _weather_guidance_needs_language_repair(self, weather: WeatherGuidance, request: PlanningRequest) -> bool:
        locale = infer_output_locale(request)
        texts = [
            weather.overall_outlook,
            *weather.daily_outlook,
            *[
                " ".join([forecast.outlook, forecast.timing_advice, forecast.risk])
                for forecast in weather.daily_forecasts
            ],
            *[
                " ".join(
                    [
                        segment.name,
                        segment.date_range,
                        segment.outlook,
                        segment.temperature_range,
                        *segment.clothing_advice,
                        *segment.outdoor_notes,
                        *segment.risks,
                    ]
                )
                for segment in weather.segments
            ],
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

    def _validate_weather_date_coverage(self, weather: WeatherGuidance, request: PlanningRequest) -> None:
        if request.planning_generated_at is None:
            return
        expected_dates = {
            request.start_date + timedelta(days=offset)
            for offset in range(max(1, (request.end_date - request.start_date).days + 1))
        }
        actual_dates = [forecast.date for forecast in weather.daily_forecasts]
        if actual_dates:
            if len(actual_dates) != len(set(actual_dates)) or set(actual_dates) != expected_dates:
                missing = sorted(date_value.isoformat() for date_value in expected_dates - set(actual_dates))
                extra = sorted(date_value.isoformat() for date_value in set(actual_dates) - expected_dates)
                raise ValueError(f"天气逐日日期校验失败：缺少 {missing or '无'}；多出 {extra or '无'}")
            return
        raise ValueError("天气逐日日期校验失败：daily_forecasts 必须按行程日期逐日返回，不能缺日或合并日期。")

    def _repair_weather_guidance_language(
        self,
        weather: WeatherGuidance,
        request: PlanningRequest,
        llm_client: OpenAICompatibleClient,
    ) -> WeatherGuidance:
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
                            "daily_forecasts[].outlook",
                            "daily_forecasts[].timing_advice",
                            "daily_forecasts[].risk",
                            "segments[].name",
                            "segments[].outlook",
                            "segments[].clothing_advice[]",
                            "segments[].outdoor_notes[]",
                            "segments[].risks[]",
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
        return self._parse_structured_response(content, WeatherGuidance)

    def _parse_structured_response(self, content: str, model_cls: type[BaseModel]) -> BaseModel:
        payloads = self._extract_json_payloads(content)
        valid_payloads: list[BaseModel] = []
        validation_errors: list[str] = []
        for payload in payloads:
            try:
                valid_payloads.append(model_cls.model_validate(payload))
            except ValidationError as exc:
                validation_errors.append(str(exc))
        if not valid_payloads:
            detail = validation_errors[-1] if validation_errors else "no valid JSON object"
            raise ValueError(detail)
        if len(valid_payloads) > 1:
            signatures = {
                json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
                for item in valid_payloads
            }
            if len(signatures) > 1:
                _LOGGER.warning(
                    "PlanningCore response contained %d conflicting valid JSON objects for %s; using the last complete object as the model's final revision.",
                    len(valid_payloads),
                    model_cls.__name__,
                )
            else:
                _LOGGER.warning(
                    "PlanningCore response contained %d duplicate JSON objects for %s; using the last object.",
                    len(valid_payloads),
                    model_cls.__name__,
                )
        return valid_payloads[-1]

    def _extract_json_payload(self, content: str) -> dict[str, Any]:
        return self._extract_json_payloads(content)[-1]

    def _extract_json_payloads(self, content: str) -> list[dict[str, Any]]:
        candidate = str(content).strip()
        if not candidate:
            raise ValueError("PlanningCore response was empty")

        if candidate.startswith("```"):
            candidate = self._strip_code_fences(candidate)

        decoder = json.JSONDecoder()
        payloads: list[dict[str, Any]] = []
        cursor = 0
        while cursor < len(candidate):
            start = candidate.find("{", cursor)
            if start == -1:
                break
            try:
                payload, end = decoder.raw_decode(candidate[start:])
            except json.JSONDecodeError:
                cursor = start + 1
                continue
            if isinstance(payload, dict):
                payloads.append(payload)
            cursor = start + end

        if not payloads:
            raise ValueError("PlanningCore response did not contain a valid JSON object")
        return payloads

    def _strip_code_fences(self, content: str) -> str:
        lines = content.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()

    def _summarize_brief(self, brief: PlanningBrief) -> str:
        must_have = ", ".join(brief.must_have[:3]) if brief.must_have else "none"
        budget_mode = "hard budget" if brief.budget_is_hard_constraint else "flexible budget"
        priority = brief.budget_priority or "balanced"
        return f"{brief.destination}; {brief.trip_days} days; pace {brief.pace or 'n/a'}; {budget_mode}; priority {priority}; must-have {must_have}."

    def _summarize_attractions(self, attractions: AttractionGrounding) -> str:
        booking_ready = sum(1 for poi in attractions.featured_pois if poi.booking_info is not None or poi.visit_requirements is not None)
        return (
            f"{len(attractions.candidate_areas)} areas, "
            f"{len(attractions.featured_pois)} featured POIs, "
            f"{booking_ready} POIs with ticket or reservation guidance, "
            f"{len(attractions.sequencing_hints)} sequencing hints."
        )

    def _summarize_pois(self, grounding: PoiGrounding) -> str:
        food_count = sum(1 for poi in grounding.featured_pois if self._is_food_poi(poi))
        attraction_count = max(len(grounding.featured_pois) - food_count, 0)
        sourced_count = sum(
            1
            for poi in grounding.featured_pois
            if poi.source_urls or (poi.booking_info is not None and poi.booking_info.source_urls)
        )
        priced_food_count = sum(
            1
            for poi in grounding.featured_pois
            if self._is_food_poi(poi) and poi.price_hint and poi.price_hint.strip().lower() != "unknown"
        )
        reviewed_food_count = sum(
            1
            for poi in grounding.featured_pois
            if self._is_food_poi(poi) and poi.review_score and poi.review_score.strip().lower() != "unknown"
        )
        return (
            f"{len(grounding.candidate_areas)} areas, "
            f"{len(grounding.featured_pois)} POIs "
            f"({attraction_count} attraction/experience, {food_count} food/cafe/market), "
            f"{sourced_count} with source URLs, "
            f"{priced_food_count} food POIs with price evidence, "
            f"{reviewed_food_count} food POIs with review signals, "
            f"{len(grounding.sequencing_hints)} sequencing hints."
        )

    def _summarize_weather(self, weather: WeatherGuidance) -> str:
        return (
            f"{self._truncate_planner_text(weather.overall_outlook, 120)} "
            f"{len(weather.segments)} weather segments, {len(weather.packing_notes)} packing notes, {len(weather.weather_risks)} weather risks."
        )

    def _summarize_foods(self, foods: FoodRecommendation) -> str:
        reliable_prices = sum(1 for poi in foods.featured_pois if poi.price_hint and poi.price_hint.strip().lower() != "unknown")
        reliable_reviews = sum(1 for poi in foods.featured_pois if poi.review_score and poi.review_score.strip().lower() != "unknown")
        return (
            f"{len(foods.candidate_areas)} food areas, "
            f"{len(foods.featured_pois)} food POIs, "
            f"{reliable_prices} with price evidence, "
            f"{reliable_reviews} with review signals."
        )

    def _summarize_hotels(self, hotels: HotelRecommendation, *, destination: str = "") -> str:
        all_candidates = [*hotels.hotel_candidates, *([hotels.final_recommended_hotel] if hotels.final_recommended_hotel else [])]
        conflicting_urls = self._hotel_conflicting_source_urls(all_candidates)
        verified_candidates = [
            candidate for candidate in all_candidates
            if self._is_verified_hotel_candidate(candidate, destination=destination, blocked_urls=conflicting_urls)
        ]
        selected = (
            hotels.final_recommended_hotel.name
            if self._is_verified_hotel_candidate(
                hotels.final_recommended_hotel,
                destination=destination,
                blocked_urls=conflicting_urls,
            )
            else "none"
        )
        return (
            f"selected hotel {selected}, "
            f"{len(hotels.recommended_areas)} stay areas, "
            f"{len(verified_candidates)}/{len(all_candidates)} source-backed hotel candidates, "
            f"{len(hotels.stay_strategy)} stay strategy notes, "
            f"{len(hotels.price_timeliness_notes)} price freshness notes, "
            f"{len(hotels.review_notes)} review notes."
        )

    def _summarize_transport(self, transport: TransportGuidance) -> str:
        verified = sum(row.evidence_status == "verified" for row in transport.service_candidates)
        referenced = sum(row.evidence_status == "referenced" for row in transport.service_candidates)
        return (
            f"{len(transport.intercity_options)} intercity options, {len(transport.service_candidates)} static service candidates, "
            f"{verified} page-verified and {referenced} source-referenced, "
            f"estimated intercity cost {round(float(transport.estimated_intercity_cost or 0.0), 2)}, "
            f"estimated local transport cost {round(float(transport.estimated_local_transport_cost or 0.0), 2)}, "
            f"booking URL {'yes' if transport.official_booking_url else 'no'}."
        )

    def _sanitize_transport_service_candidates(
        self,
        transport: TransportGuidance,
        request: PlanningRequest,
    ) -> TransportGuidance:
        expected = {
            "outbound": (request.origin, request.destination, request.start_date),
            "return": (request.destination, request.origin, request.end_date),
        }
        kept: list[TransportServiceCandidate] = []
        seen: set[tuple[str, str, str, str]] = set()
        per_scope: dict[str, int] = {"outbound": 0, "return": 0, "intercity": 0}
        removed = 0
        for candidate in transport.service_candidates:
            expected_route = expected.get(candidate.scope)
            if expected_route is not None:
                origin, destination, travel_date = expected_route
                candidate_origin = normalize_identity(candidate.origin)
                candidate_destination = normalize_identity(candidate.destination)
                if (
                    normalize_identity(origin) not in candidate_origin
                    or normalize_identity(destination) not in candidate_destination
                    or candidate.departure_date != travel_date
                ):
                    removed += 1
                    continue
            key = (candidate.scope, candidate.service_number.casefold(), candidate.departure_date.isoformat(), candidate.departure_time)
            if key in seen or per_scope[candidate.scope] >= 3:
                removed += 1
                continue
            seen.add(key)
            per_scope[candidate.scope] += 1
            kept.append(candidate)
        normalized = transport.model_copy(update={"service_candidates": kept})
        if removed:
            note = f"已剔除 {removed} 条站点、机场、日期不一致或重复的候选班次。"
            normalized.notes = list(dict.fromkeys([*normalized.notes, note]))
        # Keep a missing time-window signal explicit.  A planner cannot safely
        # select an afternoon return when the specialist only found early
        # services, so surface this as a data-quality note instead of letting
        # the model imply that the candidate set is complete.
        return_candidates = [item for item in kept if item.scope == "return"]
        if return_candidates and not any(
            (self._clock_minutes(item.departure_time) or -1) >= 14 * 60
            for item in return_candidates
        ):
            note = "返程候选目前仅覆盖14:00前时段；如行程需要下午返程，必须重新检索覆盖该时间窗的班次。"
            normalized.notes = list(dict.fromkeys([*normalized.notes, note]))
        return normalized

    def _summarize_itinerary(self, summary: str, days: list[Any], risks: list[str]) -> str:
        compact = summary.strip() or "Draft ready."
        return f"{compact} {len(days)} days, {len(risks)} risks."

    def _mark_unverified_schedules_as_planning_windows(
        self,
        payload: LlmPlanningPayload,
        request: PlanningRequest,
        transport: TransportGuidance | None = None,
    ) -> LlmPlanningPayload:
        normalized = payload.model_copy(deep=True)
        candidates = [
            candidate
            for candidate in (transport.service_candidates if transport else [])
            if candidate.evidence_status in {"verified", "referenced"}
        ]
        zh_output = is_chinese_output(request)
        window_note = (
            "该时间段仅为建议出行预留窗口，不是已核验班次；具体车次和发车时间须以购票结果为准。"
            if zh_output
            else "This is a recommended travel window, not a verified service time; confirm the service and departure time when booking."
        )
        reference_note = (
            "该车次或航班采用有来源的静态参考时刻；实际运行、延误和余票须在出发前确认。"
            if zh_output
            else "This service uses a sourced reference timetable; confirm actual operation, delays, and availability before departure."
        )
        pending_suffix = "（班次待确认）" if zh_output else " (service pending confirmation)"
        for day_offset, day in enumerate(normalized.days):
            item_date = request.start_date + timedelta(days=day_offset)
            for item in day.items:
                if not self._is_scheduled_transport_item(item):
                    continue
                booking = item.booking_info
                # Models occasionally label the hotel-to-station leg as
                # ``return`` because it precedes the return train. It is a
                # local transfer, not a second intercity service; normalize
                # it before matching against the return rail leg's duration.
                item_text = f"{item.name} {item.note}".casefold()
                local_transfer_markers = (
                    "酒店至", "酒店到", "站至酒店", "站到酒店", "前往", "取行李",
                    "进站", "安检", "检票", "候车", "候机", "登机", "虹桥站",
                )
                rail_markers = ("高铁", "动车", "火车", "列车", "航班", "flight", "rail", "train")
                selected_service_key = str(booking.service_number or "").strip().casefold() if booking else ""
                candidate = self._match_transport_candidate(item, booking, candidates, item_date)
                if (
                    booking is not None
                    and candidate is None
                    and not selected_service_key
                    and booking.transport_scope in {"outbound", "return", "intercity"}
                    and any(marker in item_text for marker in local_transfer_markers)
                    and not any(marker in item_text for marker in rail_markers)
                ):
                    booking.transport_scope = "local"
                    continue
                # Treat the specialist's post-verification candidate set as
                # authoritative. The planner may select a candidate, but may
                # not alter its times, source, or evidence state.
                if booking is not None and transport is not None:
                    booking.schedule_verified = False
                    if candidate is not None:
                        item.start_time = candidate.departure_time
                        item.end_time = candidate.arrival_time
                        arrival_date = candidate.arrival_date or candidate.departure_date
                        item.end_day_offset = max(0, (arrival_date - candidate.departure_date).days)
                        booking.transport_scope = candidate.scope
                        booking.duration_minutes_min = candidate.duration_minutes
                        booking.schedule_status = candidate.schedule_status
                        booking.schedule_checked_at = candidate.schedule_checked_at
                        booking.schedule_source_url = candidate.source_url
                        booking.evidence_status = candidate.evidence_status
                        booking.evidence_checked_at = candidate.evidence_checked_at
                        booking.evidence_reason = candidate.evidence_reason
                        booking.source_urls = list(dict.fromkeys([*booking.source_urls, candidate.source_url]))
                    elif selected_service_key:
                        booking.service_number = None
                        booking.schedule_status = "unknown"
                        booking.schedule_checked_at = None
                        booking.schedule_source_url = None
                        booking.evidence_status = "unknown"
                        booking.evidence_checked_at = None
                        booking.evidence_reason = "规划器填写的班次不在交通专家核验后的候选集中。"
                evidence_complete = bool(
                    booking
                    and booking.schedule_verified
                    and str(booking.service_number or "").strip()
                    and str(booking.schedule_checked_at or "").strip()
                    and str(booking.schedule_source_url or "").strip().startswith(("http://", "https://"))
                )
                if evidence_complete:
                    continue
                reference_complete = bool(
                    booking
                    and booking.schedule_status in {"reference", "date_specific"}
                    and str(booking.service_number or "").strip()
                    and str(booking.schedule_checked_at or "").strip()
                    and str(booking.schedule_source_url or "").strip().startswith(("http://", "https://"))
                )
                if reference_complete:
                    booking.schedule_verified = False
                    if reference_note not in booking.notes:
                        booking.notes.insert(0, reference_note)
                    if reference_note not in item.note:
                        item.note = f"{item.note.strip()} {reference_note}".strip()
                    continue
                if booking is None:
                    booking = LlmBookingInfo()
                    item.booking_info = booking
                booking.schedule_verified = False
                if window_note not in booking.notes:
                    booking.notes.insert(0, window_note)
                if window_note not in item.note:
                    item.note = f"{item.note.strip()} {window_note}".strip()
                if pending_suffix.strip() not in item.name:
                    item.name = f"{item.name}{pending_suffix}"
        # An unverified service is only a planning window. If the planner made
        # the final return window spill past the requested trip end, move that
        # window (and one contiguous transfer/preparation block) earlier while
        # preserving their durations. Any resulting overlap still fails the
        # normal execution validator.
        if normalized.days:
            final_day = normalized.days[-1]
            for index, item in enumerate(final_day.items):
                booking = item.booking_info
                if (
                    not booking
                    or booking.schedule_verified
                    or booking.schedule_status in {"reference", "date_specific"}
                    or booking.transport_scope != "return"
                    or item.end_day_offset <= 0
                ):
                    continue
                start = self._clock_minutes(item.start_time)
                end_clock = self._clock_minutes(item.end_time)
                if start is None or end_clock is None:
                    continue
                duration = item.end_day_offset * 1440 + end_clock - start
                target_end = 23 * 60 + 45
                new_start = target_end - duration
                if duration <= 0 or new_start < 0:
                    continue
                shift = new_start - start
                item.start_time = f"{new_start // 60:02d}:{new_start % 60:02d}"
                item.end_time = "23:45"
                item.end_day_offset = 0
                adjustment_note = "未核验返程窗口原会跨出行程结束日，已保持时长并整体前移；实际时刻以出票为准。"
                if adjustment_note not in item.note:
                    item.note = f"{item.note.strip()} {adjustment_note}".strip()
                if index > 0:
                    prior = final_day.items[index - 1]
                    prior_end = self._clock_minutes(prior.end_time)
                    prior_start = self._clock_minutes(prior.start_time)
                    if self._is_transport_item(prior) and not prior.end_day_offset and prior_end == start and prior_start is not None:
                        shifted_start = prior_start + shift
                        shifted_end = prior_end + shift
                        if shifted_start >= 0:
                            prior.start_time = f"{shifted_start // 60:02d}:{shifted_start % 60:02d}"
                            prior.end_time = f"{shifted_end // 60:02d}:{shifted_end % 60:02d}"
        return normalized

    def _normalize_departure_waiting_blocks(
        self,
        payload: LlmPlanningPayload,
        transport: TransportGuidance,
    ) -> LlmPlanningPayload:
        """Cap station waiting without reducing the total return safety buffer."""
        normalized = payload.model_copy(deep=True)
        if not normalized.days:
            return normalized
        final_day = normalized.days[-1]
        waiting_markers = ("候车", "候机", "安检", "检票", "进站", "登机")
        station_buffer = max(int(transport.station_buffer_minutes or 0), 0)
        waiting_cap = max(station_buffer, min(station_buffer + 30, 90))
        for departure_index, departure in enumerate(final_day.items):
            booking = departure.booking_info
            if not booking or booking.transport_scope != "return" or departure_index < 1:
                continue
            departure_start = self._clock_minutes(departure.start_time)
            waiting = final_day.items[departure_index - 1]
            waiting_text = f"{waiting.name} {waiting.note}"
            waiting_start = self._clock_minutes(waiting.start_time)
            waiting_end = self._clock_minutes(waiting.end_time)
            if (
                departure_start is None
                or waiting_start is None
                or waiting_end != departure_start
                or waiting.end_day_offset
                or not any(marker in waiting_text for marker in waiting_markers)
            ):
                continue
            waiting_duration = waiting_end - waiting_start
            if waiting_duration <= 0:
                continue
            # A station/airport security and waiting block is local departure
            # buffer, never the intercity service itself. Reclassify it even
            # when its duration is already within the configured cap so the
            # route-duration validator does not compare a 60-minute wait with
            # a multi-hour rail or flight leg.
            if waiting.booking_info is not None:
                waiting.booking_info.transport_scope = "local"
                waiting.booking_info.duration_minutes_min = min(waiting_duration, waiting_cap)
            if waiting_duration <= waiting_cap:
                continue
            new_waiting_start = departure_start - waiting_cap
            if new_waiting_start < 0:
                continue
            waiting.start_time = f"{new_waiting_start // 60:02d}:{new_waiting_start % 60:02d}"
            note = f"车站候车按{waiting_cap}分钟安全缓冲编排，额外机动时间保留在此前，不计入候车时长。"
            if note not in waiting.note:
                waiting.note = f"{waiting.note.strip()} {note}".strip()

            # Keep the immediately preceding luggage/transfer block adjacent
            # when it can be shifted later without overlapping an activity.
            if departure_index < 2:
                continue
            transfer = final_day.items[departure_index - 2]
            transfer_booking = transfer.booking_info
            transfer_start = self._clock_minutes(transfer.start_time)
            transfer_end = self._clock_minutes(transfer.end_time)
            if (
                not self._is_transport_item(transfer)
                or transfer.end_day_offset
                or transfer_start is None
                or transfer_end is None
                or transfer_end <= transfer_start
                or (transfer_booking is not None and transfer_booking.transport_scope not in {None, "local"})
            ):
                continue
            duration = transfer_end - transfer_start
            shifted_start = new_waiting_start - duration
            prior_end = (
                self._clock_minutes(final_day.items[departure_index - 3].end_time)
                if departure_index >= 3
                else 0
            )
            if shifted_start < 0 or (prior_end is not None and shifted_start < prior_end):
                continue
            transfer.start_time = f"{shifted_start // 60:02d}:{shifted_start % 60:02d}"
            transfer.end_time = waiting.start_time
        return normalized

    @staticmethod
    def _match_transport_candidate(item, booking, candidates, item_date: date):
        if booking is None or not str(booking.service_number or "").strip():
            return None
        service = str(booking.service_number).strip().casefold()
        item_text = normalize_identity(f"{item.name} {item.location} {item.note}")
        expected_scope = booking.transport_scope
        matches = []
        for candidate in candidates:
            if str(candidate.service_number).strip().casefold() != service:
                continue
            if candidate.departure_date != item_date:
                continue
            if expected_scope in {"outbound", "return", "intercity"} and candidate.scope != expected_scope:
                continue
            origin = normalize_identity(candidate.origin)
            destination = normalize_identity(candidate.destination)
            if not origin or origin not in item_text or not destination or destination not in item_text:
                continue
            matches.append(candidate)
        return matches[0] if len(matches) == 1 else None

    def _validate_execution_constraints(
        self,
        payload: LlmPlanningPayload,
        request: PlanningRequest,
        transport: TransportGuidance,
        *,
        available_poi_count: int = 0,
        poi_grounding: PoiGrounding | None = None,
    ) -> None:
        errors: list[str] = validate_timeline(payload, request, transport)
        generated_at = request.planning_generated_at
        if generated_at is not None:
            local_generated_at = generated_at.astimezone() if generated_at.tzinfo is not None else generated_at
            if request.start_date < local_generated_at.date():
                errors.append("行程开始日期已经早于当前日期")
            elif request.start_date == local_generated_at.date() and payload.days:
                earliest_start = local_generated_at.replace(second=0, microsecond=0) + timedelta(minutes=30)
                if earliest_start.date() > request.start_date:
                    errors.append("今天已经没有足够的行程生成与准备时间")
                first_day_starts = [self._clock_minutes(item.start_time) for item in payload.days[0].items]
                valid_starts = [value for value in first_day_starts if value is not None]
                if earliest_start.date() == request.start_date and valid_starts and min(valid_starts) < earliest_start.hour * 60 + earliest_start.minute:
                    errors.append(f"当天首日存在早于可执行时间 {earliest_start.strftime('%H:%M')} 的项目")

        seen_pois: dict[str, int] = {}
        for day_index, day in enumerate(payload.days, start=1):
            for item in day.items:
                if self._is_transport_item(item):
                    continue
                matched_poi = self._find_matching_featured_poi(item.name, poi_grounding)
                if matched_poi is not None:
                    source_constraint_text = " ".join([
                        *matched_poi.evidence_notes,
                        *matched_poi.caveats,
                        *(
                            [
                                str(matched_poi.visit_requirements.advance_booking_note or ""),
                                *matched_poi.visit_requirements.notes,
                            ]
                            if matched_poi.visit_requirements else []
                        ),
                        *(matched_poi.booking_info.notes if matched_poi.booking_info else []),
                    ])
                    target_date = request.start_date + timedelta(days=day_index - 1)
                    if has_closed_weekday_constraint(source_constraint_text, target_date.weekday()):
                        errors.append(
                            f"{item.name} 安排在 {target_date.isoformat()}，但 POI 专家证据注明当天闭馆"
                        )
                key = self._normalize_poi_dedupe_key(item.name)
                if not key:
                    continue
                previous_day = seen_pois.get(key)
                if previous_day is not None and previous_day != day_index:
                    errors.append(f"POI“{item.name}”在第 {previous_day} 天和第 {day_index} 天重复")
                else:
                    seen_pois[key] = day_index

        if payload.days:
            departure_day = payload.days[-1]
            departure_index = next(
                (
                    index
                    for index in range(len(departure_day.items) - 1, -1, -1)
                    if self._is_scheduled_transport_item(departure_day.items[index])
                ),
                None,
            )
            if departure_index is not None and departure_index > 0:
                departure_item = departure_day.items[departure_index]
                # Station/airport transfers and luggage collection are part of
                # the departure buffer, not the activity that starts it. Walk
                # backwards to the last non-transport item so a valid transfer
                # chain ending exactly at the rail/flight window is not
                # incorrectly measured as a zero-minute buffer.
                previous_activity = next(
                    (
                        departure_day.items[index]
                        for index in range(departure_index - 1, -1, -1)
                        if self._is_departure_buffer_anchor_item(departure_day.items[index])
                    ),
                    None,
                )
                previous_end = self._clock_minutes(previous_activity.end_time) if previous_activity is not None else None
                departure_start = self._clock_minutes(departure_item.start_time)
                required_buffer = max(
                    transport.minimum_departure_buffer_minutes,
                    transport.departure_transfer_minutes + transport.station_buffer_minutes + transport.luggage_buffer_minutes,
                )
                if previous_activity is not None and (previous_end is None or departure_start is None):
                    errors.append("返程缓冲无法校验：返程交通或最后一个游玩/用餐项目缺少有效时间")
                elif previous_activity is not None:
                    actual_buffer = departure_start - previous_end
                    if actual_buffer < required_buffer:
                        errors.append(
                            f"返程日最后一个游玩/用餐项目到跨城出发窗口仅 {actual_buffer} 分钟，至少需要 {required_buffer} 分钟"
                        )

        poi_types = {"sight", "museum", "attraction", "landmark", "park", "district", "experience", "nature", "scenic"}
        day_pois = [
            [item for item in day.items if str(getattr(item, "type", "") or "").strip().lower() in poi_types]
            for day in payload.days
        ]
        arrival_evening_available = False
        if payload.days:
            first_day = payload.days[0]
            lodging = next(
                (
                    item for item in first_day.items
                    if str(getattr(item, "type", "") or "").strip().lower() in {"hotel", "stay", "accommodation", "lodging"}
                    and self._clock_minutes(item.end_time) is not None
                    and self._clock_minutes(item.end_time) <= 18 * 60
                ),
                None,
            )
            arrival_evening_available = lodging is not None and not day_pois[0]
            if arrival_evening_available:
                errors.append("内容密度不足：抵达日18:00前已完成入住，但当天没有安排住宿周边的傍晚 POI")

        if available_poi_count >= 8 and len(payload.days) >= 3:
            full_days = sum(
                1
                for day in payload.days
                if not any(self._is_scheduled_transport_item(item) for item in day.items)
            )
            density_target = min(available_poi_count, max(4, min(full_days * 3 + int(arrival_evening_available), len(payload.days) + 2)))
            actual_poi_count = sum(len(items) for items in day_pois)
            if actual_poi_count < density_target:
                errors.append(
                    f"内容密度不足：已有 {available_poi_count} 个候选 POI，但仅安排 {actual_poi_count} 个；当前时段结构至少应安排 {density_target} 个"
                )

        if errors:
            raise ValueError("行程可执行性校验失败：" + "；".join(dict.fromkeys(errors)))

    def _is_transport_item(self, item: Any) -> bool:
        return str(getattr(item, "type", "") or "").strip().lower() in {
            "transport", "transit", "local_transport", "transfer", "rail", "flight", "ferry",
            "metro", "subway", "bus", "taxi", "walk_transfer",
        }

    def _is_departure_buffer_anchor_item(self, item: Any) -> bool:
        if self._is_transport_item(item):
            return False
        text = f"{getattr(item, 'name', '')} {getattr(item, 'note', '')}".casefold()
        logistics_markers = (
            "取行李", "寄存行李", "退房", "行李领取", "安检", "进站", "候车", "候机", "登机",
            "collect luggage", "luggage pickup", "check-out", "checkout", "security", "station waiting", "boarding",
        )
        return not any(marker in text for marker in logistics_markers)

    def _is_scheduled_transport_item(self, item: Any) -> bool:
        if not self._is_transport_item(item):
            return False
        scope = getattr(getattr(item, "booking_info", None), "transport_scope", None)
        if scope:
            return scope in {"outbound", "return", "intercity"}
        text = f"{getattr(item, 'name', '')} {getattr(item, 'note', '')}".casefold()
        return any(
            marker in text
            for marker in (
                "高铁",
                "动车",
                "火车",
                "列车",
                "航班",
                "飞机",
                "轮渡",
                "train",
                "rail",
                "flight",
                "ferry",
            )
        )

    def _clock_minutes(self, value: str) -> int | None:
        match = re.fullmatch(r"(\d{2}):(\d{2})", str(value or "").strip())
        if match is None:
            return None
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            return None
        return hour * 60 + minute

    def _normalize_poi_dedupe_key(self, value: str) -> str:
        """Collapse common presentation-only POI suffixes without merging nearby distinct sights."""
        normalized = self._normalize_match_key(value)
        if not normalized:
            return ""
        for prefix in ("再次游览", "再次前往", "重游", "再访", "二刷"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
        for suffix in (
            "周边漫步",
            "周边游览",
            "深度游览",
            "深度游",
            "夜间游览",
            "夜游",
            "晨间游览",
            "晨游",
            "再次游览",
            "再访",
            "景区",
            "风景区",
            "旅游区",
        ):
            if normalized.endswith(suffix) and len(normalized) > len(suffix) + 1:
                normalized = normalized[: -len(suffix)]
                break
        return normalized

    def _pick_weather_note(self, notes: list[str], day_index: int) -> str:
        normalized = [str(item).strip() for item in notes if str(item).strip()]
        if not normalized:
            return ""
        if day_index - 1 < len(normalized):
            return normalized[day_index - 1]
        return ""

    def _pick_weather_outlook_for_date(
        self,
        weather_guidance: WeatherGuidance,
        *,
        target_date: date,
        trip_start_date: date,
        expected_days: int,
    ) -> tuple[str, list[str]]:
        forecast = next((item for item in weather_guidance.daily_forecasts if item.date == target_date), None)
        if forecast is not None:
            notes = [value for value in (forecast.timing_advice, forecast.risk) if str(value or "").strip()]
            return forecast.outlook.strip(), notes

        legacy = [str(item).strip() for item in weather_guidance.daily_outlook if str(item).strip()]
        offset = (target_date - trip_start_date).days
        if len(legacy) == expected_days and 0 <= offset < len(legacy):
            return legacy[offset], []

        iso_date = target_date.isoformat()
        chinese_date = f"{target_date.month}月{target_date.day}日"
        for item in legacy:
            if iso_date in item or chinese_date in item:
                return item, []
        return "", []

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
        selected_outlook: str,
        weather_guidance: WeatherGuidance,
        weather_tool_results: dict[str, Any] | None,
    ) -> str:
        # Once daily evidence has been normalized, never reintroduce a
        # rejected temperature from role-level prose or raw search output.
        candidates = [selected_outlook]
        if not weather_guidance.daily_forecasts:
            candidates.extend([
                weather_guidance.overall_outlook,
                *self._flatten_text_values(weather_tool_results or {}),
            ])
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

    def _format_weather_segment_note(self, segment: WeatherSegment) -> str:
        parts = [
            segment.outlook,
            segment.temperature_range,
            *(segment.risks[:1]),
        ]
        detail = self._truncate_planner_text("; ".join(str(item).strip() for item in parts if str(item).strip()), 140)
        name = self._truncate_planner_text(segment.name, 40)
        if name and detail:
            return f"{name}: {detail}"
        return detail

    def _normalize_match_key(self, value: str) -> str:
        return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", str(value or "").strip().casefold())

    def _find_matching_featured_poi(
        self,
        item_name: str,
        poi_grounding: PoiGrounding | AttractionGrounding | None,
    ) -> ResearchPoi | None:
        if poi_grounding is None:
            return None
        target = self._normalize_match_key(item_name)
        if not target:
            return None
        best_match: ResearchPoi | None = None
        best_score = -1
        for poi in poi_grounding.featured_pois:
            if self._is_food_poi(poi):
                continue
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

    def _attach_nearby_poi_suggestions(
        self,
        planned_days: list[PlannedDay],
        poi_grounding: PoiGrounding | AttractionGrounding | None,
    ) -> None:
        """Expose researched nearby POIs without forcing them into the timeline."""
        if poi_grounding is None:
            return
        scheduled_names = {
            self._normalize_match_key(item.name)
            for day in planned_days
            for item in day.items
        }
        candidates = [
            poi for poi in poi_grounding.featured_pois
            if not self._is_food_poi(poi) and self._normalize_match_key(poi.name) not in scheduled_names
        ]
        assigned: set[str] = set()
        confidence_rank = {"high": 2, "medium": 1, "low": 0}

        for day in planned_days:
            for item in day.items:
                if str(item.type or "").strip().casefold() not in {
                    "sight", "museum", "attraction", "landmark", "park", "district",
                    "experience", "nature", "scenic", "photo",
                }:
                    continue
                core = self._find_matching_featured_poi(item.name, poi_grounding)
                if core is None:
                    continue
                core_key = self._normalize_match_key(core.name)
                core_area = self._normalize_match_key(core.area)
                core_sources = set(core.source_urls)
                ranked: list[tuple[int, int, bool, ResearchPoi]] = []
                for candidate in candidates:
                    candidate_key = self._normalize_match_key(candidate.name)
                    if not candidate_key or candidate_key in assigned:
                        continue
                    reason_key = self._normalize_match_key(candidate.reason)
                    explicit_relation = bool(core_key and core_key in reason_key)
                    same_area = bool(core_area and core_area == self._normalize_match_key(candidate.area))
                    shared_source = bool(core_sources.intersection(candidate.source_urls))
                    score = (6 if explicit_relation else 0) + (2 if same_area else 0) + (3 if shared_source else 0)
                    if score < 5:
                        continue
                    ranked.append((score, confidence_rank.get(candidate.confidence.casefold(), 0), explicit_relation, candidate))
                ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
                for _, _, explicit_relation, candidate in ranked[:3]:
                    source_urls = list(dict.fromkeys([
                        *candidate.source_urls,
                        *(candidate.booking_info.source_urls if candidate.booking_info else []),
                    ]))[:3]
                    item.nearby_suggestions.append(NearbyPoiSuggestion(
                        name=candidate.name,
                        area=candidate.area,
                        reason=candidate.reason or f"与{core.name}位于同一片区，可按时间和体力顺路增减。",
                        suggested_time=candidate.suggested_time,
                        highlights=candidate.highlights[:4],
                        source_urls=source_urls,
                        confidence=candidate.confidence,
                        relation_type="suggested_pair" if explicit_relation else "same_area",
                        relation_note=(
                            "POI 专家建议与当前景点搭配，实际路线和交通时间待确认。"
                            if explicit_relation
                            else "同片区或同篇攻略中的备选，实际交通时间待地图确认。"
                        ),
                    ))
                    assigned.add(self._normalize_match_key(candidate.name))

    def _find_matching_featured_food(
        self,
        item_name: str,
        poi_grounding: PoiGrounding | FoodRecommendation | None,
    ) -> ResearchPoi | FoodPoi | None:
        if poi_grounding is None:
            return None
        target = self._normalize_match_key(item_name)
        if not target:
            return None
        best_match: ResearchPoi | FoodPoi | None = None
        best_score = -1
        for poi in poi_grounding.featured_pois:
            if not self._is_food_poi(poi):
                continue
            candidate = self._normalize_match_key(poi.name)
            if not candidate:
                continue
            score = 0
            if candidate == target:
                score = 3
            elif candidate in target or target in candidate:
                score = 2
            if score > best_score:
                best_match = poi
                best_score = score
        return best_match if best_score > 0 else None

    def _is_food_item_type(self, value: str) -> bool:
        normalized = str(value or "").strip().lower()
        return normalized in {"meal", "food", "restaurant", "cafe", "dining", "snack"}

    def _should_exclude_food_itinerary_item(self, item: Any) -> bool:
        item_type = str(getattr(item, "type", "") or "").strip()
        if self._is_food_item_type(item_type):
            return True
        name = str(getattr(item, "name", "") or "")
        note = str(getattr(item, "note", "") or "")
        return self._looks_like_food_stop_text(f"{item_type} {name} {note}")

    def _looks_like_food_stop_text(self, value: str) -> bool:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return False
        if any(token in normalized for token in ("美食", "餐厅", "小吃", "夜市", "甜品", "咖啡", "饭点", "吃饭", "菜市场", "美食街")):
            return True
        return bool(
            re.search(
                r"\b(food|meal|restaurant|cafe|coffee|dessert|snack|dining|ramen|sushi|noodle|bar|bakery)\b",
                normalized,
            )
        )

    def _build_attraction_booking_info(self, poi: ResearchPoi | None) -> BookingInfo | None:
        if poi is None:
            return None
        base = (
            BookingInfo.model_validate(poi.booking_info.model_dump(mode="json"))
            if poi.booking_info is not None
            else BookingInfo()
        )
        category_labels = {
            "attraction": "景点", "district": "街区", "experience": "体验",
            "landmark": "地标", "museum": "博物馆", "nature": "自然景观",
        }
        confidence_labels = {"high": "较高", "medium": "中等", "low": "较低"}
        evidence_notes = [
            *([f"类型：{category_labels.get(poi.category.casefold(), poi.category)}"] if poi.category else []),
            *([f"信息置信度：{confidence_labels.get(poi.confidence.casefold(), poi.confidence)}"] if poi.confidence else []),
            *poi.evidence_notes[:4],
            *poi.caveats[:4],
        ]
        base.notes = list(dict.fromkeys([*base.notes, *[str(item).strip() for item in evidence_notes if str(item).strip()]]))
        base.source_urls = list(
            dict.fromkeys(
                [
                    *[str(item).strip() for item in base.source_urls if str(item).strip()],
                    *[str(item).strip() for item in poi.source_urls if str(item).strip()],
                ]
            )
        )
        if not any(
            [
                base.price_label,
                base.estimated_price is not None,
                base.booking_required,
                base.reservation_required,
                base.official_booking_url,
                base.booking_window,
                base.reminder,
                base.notes,
                base.source_urls,
            ]
        ):
            return None
        return base

    def _build_food_booking_info(self, food_poi: ResearchPoi | FoodPoi | None) -> BookingInfo | None:
        if food_poi is None:
            return None
        notes = [
            *([f"Review signal: {food_poi.review_summary}"] if food_poi.review_summary else []),
            *([f"Review score: {food_poi.review_score}"] if food_poi.review_score and food_poi.review_score.strip().lower() != "unknown" else []),
            *([f"Review count: {food_poi.review_count}"] if food_poi.review_count and food_poi.review_count.strip().lower() != "unknown" else []),
            *([f"Price checked at: {food_poi.price_checked_at}"] if food_poi.price_checked_at and food_poi.price_checked_at.strip().lower() != "unknown" else []),
            *([f"Price valid for: {food_poi.price_valid_for}"] if food_poi.price_valid_for else []),
            *([f"Signature dishes: {', '.join(food_poi.signature_dishes[:4])}"] if food_poi.signature_dishes else []),
            *([f"Queue: {food_poi.queue_hint}"] if food_poi.queue_hint else []),
            *food_poi.caveats[:4],
        ]
        price_hint = food_poi.price_hint.strip() if food_poi.price_hint else ""
        reservation_hint = food_poi.reservation_hint.strip()
        has_signal = any([price_hint, reservation_hint, notes, food_poi.source_urls])
        if not has_signal:
            return None
        reservation_hint_lower = reservation_hint.lower()
        negative_reservation_tokens = (
            "无需预约",
            "无须预约",
            "不需要预约",
            "不用预约",
            "免预约",
            "no reservation",
            "not required",
            "walk-in",
            "walk in",
        )
        if any(token in reservation_hint_lower for token in negative_reservation_tokens):
            reservation_required = False
        else:
            reservation_required = any(
                token in reservation_hint_lower for token in ("required", "reserve", "reservation")
            ) or any(token in reservation_hint for token in ("需预约", "需要预约", "建议预约", "预订", "订位"))
        return BookingInfo(
            price_label=price_hint or None,
            booking_required=reservation_required,
            reservation_required=reservation_required,
            reminder=reservation_hint or None,
            notes=list(dict.fromkeys([str(item).strip() for item in notes if str(item).strip()])),
            source_urls=[str(item).strip() for item in food_poi.source_urls if str(item).strip()],
        )

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
            **({key: getattr(primary_info, key) for key in BookingDetails.model_fields} if primary_info else {}),
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
            schedule_verified=bool(primary_info.schedule_verified if primary_info is not None else False),
            service_number=(primary_info.service_number if primary_info and primary_info.service_number else None),
            schedule_checked_at=(primary_info.schedule_checked_at if primary_info and primary_info.schedule_checked_at else None),
            schedule_source_url=(primary_info.schedule_source_url if primary_info and primary_info.schedule_source_url else None),
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
        transport_guidance: TransportGuidance | None,
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
            legs=list(transport_guidance.legs if transport_guidance and transport_guidance.legs else payload_transport.legs if payload_transport else []),
            service_candidates=list(
                transport_guidance.service_candidates
                if transport_guidance is not None
                else payload_transport.service_candidates
                if payload_transport
                else []
            ),
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
                merged.service_candidates,
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
        weather_guidance: WeatherGuidance | None,
        citations: list[str] | None,
        weather_tool_results: dict[str, Any] | None = None,
        *,
        target_date: date | None = None,
        trip_start_date: date | None = None,
        expected_days: int | None = None,
    ) -> PlannedDayWeather | None:
        if weather_guidance is None:
            return None
        resolved_start_date = trip_start_date or target_date or date.today()
        resolved_target_date = target_date or (resolved_start_date + timedelta(days=max(day_index - 1, 0)))
        resolved_expected_days = expected_days or max(len(weather_guidance.daily_forecasts), len(weather_guidance.daily_outlook), 1)
        summary, dated_notes = self._pick_weather_outlook_for_date(
            weather_guidance,
            target_date=resolved_target_date,
            trip_start_date=resolved_start_date,
            expected_days=resolved_expected_days,
        )
        if not summary:
            overall = weather_guidance.overall_outlook.strip()
            summary = (
                f"{resolved_target_date.isoformat()}：暂无对应日期的可靠逐日天气；总体参考：{overall}"
                if re.search(r"[㐀-鿿]", overall)
                else f"{resolved_target_date.isoformat()}: no reliable date-specific forecast; overall context: {overall}"
            )
        notes: list[str] = [self._truncate_planner_text(item, 110) for item in dated_notes if str(item or "").strip()]
        for candidate in (
            self._pick_weather_note(weather_guidance.timing_guidance, day_index),
            self._pick_weather_note(weather_guidance.packing_notes, day_index),
            self._pick_weather_note(weather_guidance.weather_risks, day_index),
        ):
            compact_candidate = self._truncate_planner_text(candidate, 110)
            if compact_candidate and compact_candidate not in notes:
                notes.append(compact_candidate)
        if not notes:
            for segment in weather_guidance.segments[:1]:
                segment_note = self._format_weather_segment_note(segment)
                if segment_note and segment_note not in notes:
                    notes.append(segment_note)
        temperature_hint = self._resolve_weather_temperature_hint(summary, weather_guidance, weather_tool_results)
        if temperature_hint:
            if not self._contains_temperature_signal(summary) and temperature_hint.casefold() not in summary.casefold():
                summary = f"{summary} {temperature_hint}".strip() if summary else temperature_hint
            elif all(temperature_hint.casefold() not in note.casefold() for note in notes):
                notes.insert(0, self._truncate_planner_text(temperature_hint, 80))
        summary = self._truncate_planner_text(summary, 150)
        matching_forecast = next(
            (item for item in weather_guidance.daily_forecasts if item.date == resolved_target_date),
            None,
        )
        all_daily_sources = {
            str(url).strip()
            for forecast in weather_guidance.daily_forecasts
            for url in forecast.source_urls
            if str(url).strip()
        }
        matching_sources = [
            str(url).strip()
            for url in (matching_forecast.source_urls if matching_forecast else [])
            if str(url).strip()
        ]
        shared_sources = [
            str(url).strip()
            for url in weather_guidance.source_urls
            if str(url).strip()
        ]
        fallback_sources = [
            str(item).strip()
            for item in (citations or [])
            if str(item).strip() and str(item).strip() not in all_daily_sources
        ]
        # A single multi-day forecast page may legitimately support several
        # dates. Once the specialist supplied date-bound evidence, avoid
        # polluting the day with unrelated monthly or role-level links.
        citation_list = list(
            dict.fromkeys(
                matching_sources if matching_sources else [*shared_sources, *fallback_sources]
            )
        )
        if matching_forecast is not None and not matching_sources:
            warning = (
                f"{resolved_target_date.isoformat()} 未取得独立逐日天气来源，仅保留城市或月份参考。"
                if re.search(r"[㐀-鿿]", summary)
                else f"No date-specific weather source was captured for {resolved_target_date.isoformat()}; city or monthly context only."
            )
            if warning not in notes:
                notes.append(warning)
        if not summary and not notes and not citation_list:
            return None
        return PlannedDayWeather(
            summary=summary,
            notes=notes[:2],
            citations=citation_list[:3],
            forecast_type=(matching_forecast.forecast_type or None) if matching_forecast else None,
            condition=(matching_forecast.condition or None) if matching_forecast else None,
            temperature_min_c=(matching_forecast.temperature_min_c or None) if matching_forecast else None,
            temperature_max_c=(matching_forecast.temperature_max_c or None) if matching_forecast else None,
            precipitation_probability=(matching_forecast.precipitation_probability or None) if matching_forecast else None,
            wind=(matching_forecast.wind or None) if matching_forecast else None,
            forecast_updated_at=(matching_forecast.forecast_updated_at or None) if matching_forecast else None,
            checked_at=(matching_forecast.checked_at or None) if matching_forecast else None,
            evidence_status=(matching_forecast.evidence_status or None) if matching_forecast else None,
            evidence_checked_at=(matching_forecast.evidence_checked_at or None) if matching_forecast else None,
            evidence_reason=(matching_forecast.evidence_reason or None) if matching_forecast else None,
            field_evidence=dict(matching_forecast.field_evidence) if matching_forecast else {},
        )

    @staticmethod
    def _clear_unverified_lodging_prices(plan: PlanningResult) -> None:
        """Keep area-level stay guidance out of the deterministic ledger."""
        if plan.stay_recommendation and plan.stay_recommendation.final_recommended_hotel:
            return
        warning = "未核验到具体酒店实体与对应房价，住宿费用暂不计入确定性预算。"
        changed = False
        for day in plan.days:
            for item in day.items:
                if str(item.type or "").strip().casefold() not in {"hotel", "stay", "accommodation", "lodging"}:
                    continue
                if item.booking_info is None:
                    item.booking_info = BookingInfo(price_status="unknown", notes=[warning])
                else:
                    item.booking_info.estimated_price = None
                    item.booking_info.unit_price = None
                    item.booking_info.price_status = "unknown"
                    item.booking_info.price_label = "待核实"
                    item.booking_info.notes = list(dict.fromkeys([*item.booking_info.notes, warning]))
                changed = True
        if changed:
            plan.risks = [
                risk for risk in plan.risks
                if not (
                    re.search(r"酒店|住宿", str(risk))
                    and re.search(r"\d+(?:\.\d+)?\s*元", str(risk))
                    and re.search(r"估算|预计|预算", str(risk))
                )
            ]
        if changed and warning not in plan.risks:
            plan.risks.append(warning)

    @staticmethod
    def _downgrade_unverified_reservation_claims(plan: PlanningResult) -> None:
        """Do not present model/guide claims as mandatory booking rules."""
        warning = "未取得场馆官方预约入口支持，预约要求已降级为出发前核对。"
        downgraded_names: list[str] = []
        for day in plan.days:
            for item in day.items:
                if str(item.type or "").strip().casefold() not in {
                    "sight", "museum", "attraction", "landmark", "park", "district", "experience", "nature", "scenic",
                }:
                    continue
                booking = item.booking_info
                requirements = item.visit_requirements
                required = bool(
                    (booking and (booking.booking_required or booking.reservation_required))
                    or (requirements and str(requirements.reservation_policy or "").casefold() == "required")
                )
                if not required or (
                    booking and PlanningCore._looks_like_specific_booking_entry(booking.official_booking_url)
                ):
                    continue
                downgraded_names.append(item.name)
                if booking:
                    booking.booking_required = False
                    booking.reservation_required = False
                    booking.booking_window = None
                    booking.reminder = warning
                    if booking.price_label and "预约" in booking.price_label:
                        booking.price_label = re.split(r"[，,；;]", booking.price_label)[0].strip() or None
                    booking.notes = [
                        note for note in booking.notes
                        if not re.search(r"必须预约|需预约|尽快预约|预约名额|实名预约", str(note))
                    ]
                    booking.notes.append(warning)
                if requirements:
                    requirements.reservation_policy = "check_before_visit"
                    requirements.timed_entry = False
                    requirements.identity_required = False
                    requirements.advance_booking_note = warning
                    requirements.notes = [
                        note for note in requirements.notes
                        if not re.search(r"必须预约|需预约|尽早预约|预约名额|实名预约", str(note))
                    ]
                    requirements.notes.append(warning)
        if downgraded_names:
            plan.risks = [
                risk for risk in plan.risks
                if not (
                    "预约" in str(risk)
                    and any(name in str(risk) for name in downgraded_names)
                )
            ]
            generic_risk = "部分场馆预约规则未取得官方入口支持，出发前应以场馆官网或官方公众号最新公告为准。"
            if generic_risk not in plan.risks:
                plan.risks.append(generic_risk)

    @staticmethod
    def _looks_like_specific_booking_entry(value: str | None) -> bool:
        try:
            parsed = urlparse(str(value or "").strip())
        except ValueError:
            return False
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        target = f"{parsed.netloc}{parsed.path}?{parsed.query}".casefold()
        return any(marker in target for marker in (
            "book", "booking", "reservation", "reserve", "appointment", "ticket", "order", "yuyue", "subscribe",
        ))

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
