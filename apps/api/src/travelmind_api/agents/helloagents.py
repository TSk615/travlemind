from __future__ import annotations

import logging
import json
import re
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
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
    StayHotelCandidate,
    StayRecommendation,
    TransportBookingSummary,
    VisitRequirements,
)
from travelmind_api.agents.stub import StubOrchestrator
from travelmind_api.agents.helloagents_llm import (
    HelloAgentsCompatibleLLM as _HelloAgentsCompatibleLLM,
    HelloAgentsInvokeResult,
)
from travelmind_api.core.logging_utils import log_job_event
from travelmind_api.core.security import generate_identifier, generate_workflow_id
from travelmind_api.services.budgeting import enrich_plan_with_budget
from travelmind_api.services.llm import LlmConfig, LlmEndpointConfig, LlmPlanningPayload, OpenAICompatibleClient, build_planning_messages, parse_planning_response
from travelmind_api.services.llm.localization import build_output_language_instruction, infer_output_locale, is_chinese_output, planning_payload_needs_language_repair
from travelmind_api.prompts.roles.helloagents import (
    build_brief_parser_prompt,
    build_hotel_specialist_prompt,
    build_itinerary_planner_prompt,
    build_poi_specialist_prompt,
    build_transport_specialist_prompt,
    build_weather_specialist_prompt,
)
from travelmind_api.services.llm.prompts import PLANNING_OUTPUT_SCHEMA
from travelmind_api.services.maps import MapsPoiProvider, PoiDetail, PoiSearchResult, poi_to_route_stop
from travelmind_api.services.search_connector import ConfiguredSearchGateway, SearchServiceConfig
from travelmind_api.services.search_service import search_documents


class HelloAgentsCompatibleLLM(_HelloAgentsCompatibleLLM):
    """Keep the legacy module-level client injection seam after extraction."""

    def __init__(self, config: LlmEndpointConfig, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("client_factory", OpenAICompatibleClient)
        super().__init__(config, *args, **kwargs)

_LOGGER = logging.getLogger(__name__)

_LICENSE_NOTICE = "PoC adapter only. Do not ship a commercial release while this adapter remains in production."
_ROLE_SEQUENCE = (
    "brief_parser",
    "poi_specialist",
    "weather_specialist",
    "hotel_specialist",
    "transport_specialist",
    "itinerary_planner",
)
_CHECKPOINT_WORKFLOW = "helloagents_trip_generate"
_CHECKPOINT_VERSION = 1
_INITIAL_PARALLEL_ROLES = ("poi_specialist", "weather_specialist")
_SECONDARY_PARALLEL_ROLES = ("hotel_specialist", "transport_specialist")
_SPECIALIST_PARALLEL_ROLES = (*_INITIAL_PARALLEL_ROLES, *_SECONDARY_PARALLEL_ROLES)
_DIRECT_GROK_SEARCH_ROLES = {"weather_specialist", "hotel_specialist", "transport_specialist"}
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
    kind: str = Field(default="attraction")
    area: str = Field(default="")
    category: str = Field(default="")
    highlights: list[str] = Field(default_factory=list)
    reason: str = Field(default="")
    suggested_time: str = Field(default="")
    confidence: str = Field(default="low")
    source_urls: list[str] = Field(default_factory=list)
    evidence_notes: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    booking_info: BookingInfo | None = None
    visit_requirements: VisitRequirements | None = None
    cuisine_or_type: str = Field(default="")
    price_hint: str = Field(default="unknown")
    price_checked_at: str = Field(default="unknown")
    price_valid_for: str = Field(default="")
    review_score: str = Field(default="unknown")
    review_count: str = Field(default="unknown")
    review_summary: str = Field(default="")
    signature_dishes: list[str] = Field(default_factory=list)
    reservation_hint: str = Field(default="")
    queue_hint: str = Field(default="")


class HelloAgentsTopPoiItem(BaseModel):
    rank: int | None = None
    name: str = Field(default="")
    name_cn: str = Field(default="")
    name_en: str = Field(default="")
    kind: str = Field(default="")
    category: str = Field(default="")
    area: str = Field(default="")
    highlights: list[str] = Field(default_factory=list)
    reason: str = Field(default="")
    description: str = Field(default="")
    why_worth: str = Field(default="")
    suggested_time: str = Field(default="")
    tips: str = Field(default="")
    confidence: str = Field(default="")
    xhs_appeal: str = Field(default="")
    source_url: str = Field(default="")
    source_urls: list[str] = Field(default_factory=list)
    evidence_notes: list[str] = Field(default_factory=list)


class HelloAgentsAttractionGrounding(BaseModel):
    candidate_areas: list[str] = Field(default_factory=list)
    featured_pois: list[HelloAgentsResearchPoi] = Field(default_factory=list)
    sequencing_hints: list[str] = Field(default_factory=list)
    crowd_notes: list[str] = Field(default_factory=list)
    attraction_risks: list[str] = Field(default_factory=list)


class HelloAgentsPoiGrounding(BaseModel):
    title: str = Field(default="")
    update: str = Field(default="")
    best_season: str = Field(default="")
    recommended_duration: str = Field(default="")
    general_tips: str = Field(default="")
    top_pois: list[HelloAgentsTopPoiItem] = Field(default_factory=list)
    candidate_areas: list[str] = Field(default_factory=list)
    featured_pois: list[HelloAgentsResearchPoi] = Field(default_factory=list)
    sequencing_hints: list[str] = Field(default_factory=list)
    crowd_notes: list[str] = Field(default_factory=list)
    meal_strategy: list[str] = Field(default_factory=list)
    price_notes: list[str] = Field(default_factory=list)
    review_notes: list[str] = Field(default_factory=list)
    poi_risks: list[str] = Field(default_factory=list)

    @field_validator("featured_pois", mode="before")
    @classmethod
    def _default_featured_pois(cls, value: Any) -> Any:
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return cls._dedupe_raw_poi_items(value, name_keys=("name", "name_cn", "name_en"))
        return value

    @field_validator("top_pois", mode="before")
    @classmethod
    def _default_top_pois(cls, value: Any) -> Any:
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return cls._dedupe_raw_poi_items(value, name_keys=("name_cn", "name_en", "name"))
        return value

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any):  # type: ignore[override]
        instance = super().model_validate(obj, *args, **kwargs)
        cleaned_featured = cls._dedupe_research_pois(instance.featured_pois)
        if cleaned_featured:
            return instance.model_copy(update={"featured_pois": cleaned_featured[:10]})
        cleaned_top_pois = cls._dedupe_top_pois(instance.top_pois)
        if not cleaned_top_pois:
            return instance.model_copy(update={"featured_pois": [], "top_pois": []})
        mapped = cls._map_top_pois_to_featured_pois(cleaned_top_pois)
        return instance.model_copy(
            update={
                "top_pois": cleaned_top_pois[:10],
                "featured_pois": mapped["featured_pois"],
                "candidate_areas": instance.candidate_areas or mapped["candidate_areas"],
                "sequencing_hints": instance.sequencing_hints or mapped["sequencing_hints"],
                "crowd_notes": instance.crowd_notes or mapped["crowd_notes"],
                "poi_risks": instance.poi_risks or mapped["poi_risks"],
            }
        )

    @staticmethod
    def _poi_name_key(value: Any) -> str:
        normalized = re.sub(r"\s+", " ", str(value or "")).strip()
        if not normalized or len(normalized) > 56:
            return ""
        return normalized.casefold()

    @classmethod
    def _dedupe_raw_poi_items(cls, values: list[Any], *, name_keys: tuple[str, ...]) -> list[Any]:
        deduped: list[Any] = []
        seen: set[str] = set()
        for item in values:
            if isinstance(item, dict):
                raw_name = next((item.get(key) for key in name_keys if cls._poi_name_key(item.get(key))), "")
                key = cls._poi_name_key(raw_name)
                if not key or key in seen:
                    continue
                seen.add(key)
            deduped.append(item)
        return deduped[:10]

    @classmethod
    def _dedupe_top_pois(cls, top_pois: list[HelloAgentsTopPoiItem]) -> list[HelloAgentsTopPoiItem]:
        deduped: list[HelloAgentsTopPoiItem] = []
        seen: set[str] = set()
        for item in top_pois:
            key = cls._poi_name_key(item.name or item.name_cn or item.name_en)
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped[:10]

    @classmethod
    def _dedupe_research_pois(cls, pois: list[HelloAgentsResearchPoi]) -> list[HelloAgentsResearchPoi]:
        deduped: list[HelloAgentsResearchPoi] = []
        seen: set[str] = set()
        for poi in pois:
            key = cls._poi_name_key(poi.name)
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(poi)
        return deduped[:10]

    @staticmethod
    def _map_top_pois_to_featured_pois(top_pois: list[HelloAgentsTopPoiItem]) -> dict[str, Any]:
        featured: list[HelloAgentsResearchPoi] = []
        candidate_areas: list[str] = []
        for item in top_pois:
            name = str(item.name or item.name_cn or item.name_en or "").strip()
            if not name:
                continue
            category = str(item.kind or item.category or "").strip()
            area = str(item.area or "").strip()
            reason = str(item.reason or item.why_worth or item.description or "").strip()
            source_urls = list(
                dict.fromkeys(
                    [
                        *([str(item.source_url).strip()] if str(item.source_url or "").strip() else []),
                        *[str(value).strip() for value in item.source_urls if str(value).strip()],
                    ]
                )
            )[:1]
            evidence_notes = [str(value).strip() for value in item.evidence_notes if str(value).strip()][:2]
            if not evidence_notes:
                evidence_notes = [text for text in [str(item.description or "").strip(), str(item.tips or "").strip()] if text][:2]
            confidence_value = str(item.confidence or item.xhs_appeal or "").strip().lower()
            confidence = confidence_value if confidence_value in {"high", "medium", "low"} else "high" if str(item.xhs_appeal or "").strip() in {"极高", "高", "high"} else "medium"
            kind = HelloAgentsPoiGrounding._infer_kind_from_top_poi(item)
            featured.append(
                HelloAgentsResearchPoi(
                    name=name,
                    kind=kind,
                    category=category,
                    area=area,
                    highlights=[str(value).strip() for value in item.highlights if str(value).strip()][:4],
                    reason=reason,
                    suggested_time=str(item.suggested_time or "").strip(),
                    confidence=confidence,
                    source_urls=source_urls,
                    evidence_notes=evidence_notes,
                    caveats=[],
                    cuisine_or_type=" / ".join(item.highlights[:3]) if kind in {"food", "market", "cafe"} else "",
                    price_hint="unknown",
                    review_score="unknown",
                    review_count="unknown",
                    review_summary=str(item.xhs_appeal or "").strip(),
                    signature_dishes=item.highlights[:3] if kind in {"food", "market", "cafe"} else [],
                    reservation_hint="",
                    queue_hint="",
                )
            )
        sequencing_hints = ["Group nearby POIs into half-day blocks."] if featured else []
        crowd_notes = ["Popular photo spots are better in the morning or around sunset."] if featured else []
        poi_risks = ["Some lightweight POI fields were backfilled from top_pois recommendations and may need later evidence enrichment."] if featured else []
        return {
            "featured_pois": featured,
            "candidate_areas": candidate_areas,
            "sequencing_hints": sequencing_hints,
            "crowd_notes": crowd_notes,
            "poi_risks": poi_risks,
        }

    @staticmethod
    def _infer_kind_from_top_poi(item: HelloAgentsTopPoiItem) -> str:
        raw_kind = str(item.kind or "").strip().lower().replace("-", "_").replace(" ", "_")
        if raw_kind in {"food", "restaurant", "dining", "snack"}:
            return "food"
        if raw_kind in {"market", "night_market"}:
            return "market"
        if raw_kind in {"cafe", "coffee"}:
            return "cafe"
        if raw_kind in {"district", "street", "old_town", "ancient_town", "mixed_area"}:
            return "mixed_area"
        if raw_kind in {"experience", "workshop"}:
            return "experience"
        if raw_kind in {"attraction", "sight", "scenic", "landmark"}:
            return "attraction"
        category = f"{item.category} {' '.join(item.highlights)}".lower()
        if any(token in category for token in ("美食", "cafe", "coffee", "餐", "market", "市集")):
            if "market" in category or "市集" in category:
                return "market"
            if "cafe" in category or "coffee" in category:
                return "cafe"
            return "food"
        if any(token in category for token in ("古城", "古镇", "街区", "town", "city")):
            return "mixed_area"
        return "attraction"


class HelloAgentsWeatherGuidance(BaseModel):
    overall_outlook: str = Field(min_length=1)
    daily_outlook: list[str] = Field(default_factory=list)
    segments: list["HelloAgentsWeatherSegment"] = Field(default_factory=list)
    packing_notes: list[str] = Field(default_factory=list)
    timing_guidance: list[str] = Field(default_factory=list)
    weather_risks: list[str] = Field(default_factory=list)


class HelloAgentsWeatherSegment(BaseModel):
    name: str = Field(default="")
    date_range: str = Field(default="")
    outlook: str = Field(default="")
    temperature_range: str = Field(default="")
    clothing_advice: list[str] = Field(default_factory=list)
    outdoor_notes: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class HelloAgentsFoodPoi(BaseModel):
    name: str = Field(min_length=1)
    area: str = Field(default="")
    cuisine_or_type: str = Field(default="")
    reason: str = Field(default="")
    suggested_time: str = Field(default="")
    price_hint: str = Field(default="unknown")
    price_checked_at: str = Field(default="unknown")
    price_valid_for: str = Field(default="")
    review_score: str = Field(default="unknown")
    review_count: str = Field(default="unknown")
    review_summary: str = Field(default="")
    signature_dishes: list[str] = Field(default_factory=list)
    reservation_hint: str = Field(default="")
    queue_hint: str = Field(default="")
    confidence: str = Field(default="low")
    caveats: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)


class HelloAgentsFoodRecommendation(BaseModel):
    candidate_areas: list[str] = Field(default_factory=list)
    featured_pois: list[HelloAgentsFoodPoi] = Field(default_factory=list)
    meal_strategy: list[str] = Field(default_factory=list)
    price_notes: list[str] = Field(default_factory=list)
    review_notes: list[str] = Field(default_factory=list)
    food_risks: list[str] = Field(default_factory=list)


HelloAgentsWeatherGuidance.model_rebuild()


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
    source_urls: list[str] = Field(default_factory=list)


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
    max_tokens: int | None = None
    retry_attempts: int = 2
    min_timeout_seconds: float = 120.0
    timeout_cap_seconds: float | None = None
    stream: bool = False


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
        self._resume_checkpoint: dict[str, Any] | None = None
        self._last_checkpoint: dict[str, Any] | None = None

    def set_resume_checkpoint(self, checkpoint: dict[str, Any] | None) -> None:
        self._resume_checkpoint = deepcopy(checkpoint) if isinstance(checkpoint, dict) else None

    def get_resume_checkpoint(self) -> dict[str, Any] | None:
        return deepcopy(self._last_checkpoint) if isinstance(self._last_checkpoint, dict) else None

    def plan_trip(self, request: PlanningRequest) -> PlanningResult:
        self._role_search_gateway_cache = {}
        self._current_xhs_source_enabled = bool(getattr(request, "xhs_source_enabled", False))
        self._current_user_id = getattr(request, "user_id", None)
        self._current_search_service = getattr(request, "search_service", None) or SearchServiceConfig.from_env()
        try:
            self._log_event("helloagents_plan_trip_started", message="HelloAgents trip planning started.", destination=request.destination)
            payload, pipeline_notes, agent_runs, poi_grounding, weather, weather_citations, weather_tool_results, grounding_documents, hotel, transport = self._run_helloagents_pipeline(request)
            result = self._build_result_from_payload(
                payload,
                request,
                pipeline_notes,
                agent_runs,
                poi_grounding=poi_grounding,
                weather_guidance=weather,
                weather_citations=weather_citations,
                weather_tool_results=weather_tool_results,
                grounding_documents=grounding_documents,
                hotel_recommendation=hotel,
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

    def _start_resume_checkpoint(self, request: PlanningRequest, trip_payload: dict[str, Any]) -> None:
        source = self._resume_checkpoint if isinstance(self._resume_checkpoint, dict) else {}
        if source and (source.get("workflow") != _CHECKPOINT_WORKFLOW or source.get("trip_id") != request.trip_id):
            source = {}
        roles = source.get("roles") if isinstance(source.get("roles"), dict) else {}
        self._last_checkpoint = {
            "version": _CHECKPOINT_VERSION,
            "workflow": _CHECKPOINT_WORKFLOW,
            "trip_id": request.trip_id,
            "job_id": self._current_job_id,
            "trip_request": trip_payload,
            "roles": deepcopy(roles),
            "completed_roles": [role for role in _ROLE_SEQUENCE if isinstance(roles.get(role), dict) and roles[role].get("status") == "completed"],
            "resumed_from_checkpoint": bool(roles),
        }
        if source.get("source_job_id"):
            self._last_checkpoint["source_job_id"] = source.get("source_job_id")

    def _record_checkpoint_role(self, role_name: str, parsed_payload: BaseModel, **metadata: Any) -> None:
        if self._last_checkpoint is None:
            return
        roles = self._last_checkpoint.setdefault("roles", {})
        roles[role_name] = {
            "status": "completed",
            "parsed": parsed_payload.model_dump(mode="json"),
            **{key: value for key, value in metadata.items() if value not in (None, "", [], {})},
        }
        self._last_checkpoint["completed_roles"] = [role for role in _ROLE_SEQUENCE if isinstance(roles.get(role), dict) and roles[role].get("status") == "completed"]

    def _record_checkpoint_failure(self, role_name: str, exc: Exception) -> None:
        if self._last_checkpoint is None:
            return
        message = str(exc).strip() or exc.__class__.__name__
        self._last_checkpoint["failed_role"] = role_name
        self._last_checkpoint["failure_message"] = message
        self._last_checkpoint["completed_roles"] = [
            role
            for role in _ROLE_SEQUENCE
            if isinstance(self._last_checkpoint.get("roles", {}).get(role), dict)
            and self._last_checkpoint["roles"][role].get("status") == "completed"
        ]

    def _load_checkpoint_model(self, role_name: str, model_type: type[BaseModel]) -> Any | None:
        checkpoint = self._last_checkpoint if isinstance(self._last_checkpoint, dict) else None
        roles = checkpoint.get("roles") if isinstance(checkpoint, dict) and isinstance(checkpoint.get("roles"), dict) else {}
        entry = roles.get(role_name) if isinstance(roles, dict) else None
        if role_name == "poi_specialist" and isinstance(entry, dict) and entry.get("fallback_used"):
            self._log_event(
                "helloagents_resume_checkpoint_skipped",
                message="Stored POI checkpoint came from deterministic fallback; role will be rerun.",
                level="WARNING",
                role=role_name,
                reason=entry.get("fallback_reason"),
            )
            roles.pop(role_name, None)
            checkpoint["completed_roles"] = [
                role
                for role in _ROLE_SEQUENCE
                if isinstance(roles.get(role), dict) and roles[role].get("status") == "completed"
            ]
            return None
        parsed = entry.get("parsed") if isinstance(entry, dict) and entry.get("status") == "completed" else None
        if not isinstance(parsed, dict):
            return None
        try:
            model = model_type.model_validate(parsed)
        except ValidationError as exc:
            self._log_event(
                "helloagents_resume_checkpoint_invalid",
                message="Stored role checkpoint could not be validated; role will be rerun.",
                level="WARNING",
                role=role_name,
                error=str(exc),
            )
            return None
        self._log_event(
            "helloagents_role_resumed_from_checkpoint",
            message="Reusing completed role output from failed job checkpoint.",
            role=role_name,
        )
        return model

    def _run_helloagents_pipeline(
        self,
        request: PlanningRequest,
    ) -> tuple[
        Any,
        list[str],
        list[AgentRunStep],
        HelloAgentsPoiGrounding,
        HelloAgentsWeatherGuidance,
        list[str],
        dict[str, Any],
        list[dict[str, Any]],
        HelloAgentsHotelRecommendation,
        HelloAgentsTransportGuidance,
    ]:
        if self._llm_config is None:
            raise RuntimeError("HelloAgents requires configured LLM settings")

        module = import_module("hello_agents")
        trip_payload = self._build_trip_payload(request)
        role_configs = self._build_role_configs(request)
        role_llm_configs = self._build_role_llm_configs()
        agent_runs: list[AgentRunStep] = []
        self._start_resume_checkpoint(request, trip_payload)

        brief_role = role_configs["brief_parser"]
        brief = self._load_checkpoint_model(brief_role.role_name, HelloAgentsBrief)
        if brief is None:
            self._emit_role_progress(brief_role)
            try:
                brief_response = self._run_role(
                    module=module,
                    role_config=brief_role,
                    llm_config=role_llm_configs[brief_role.role_name],
                    input_payload={"trip_request": trip_payload},
                )
                brief = self._parse_structured_response(brief_response, HelloAgentsBrief)
                self._record_checkpoint_role(brief_role.role_name, brief)
            except Exception as exc:
                self._record_checkpoint_failure(brief_role.role_name, exc)
                raise
        agent_runs.append(self._build_agent_run(brief_role, role_llm_configs[brief_role.role_name], self._summarize_brief(brief)))

        poi_payload = self._build_poi_research_payload(request, brief)
        weather_payload = self._build_weather_research_payload(request, brief)

        poi_role = role_configs["poi_specialist"]
        weather_role = role_configs["weather_specialist"]

        poi_fallback_reason: str | None = None
        poi_grounding = self._load_checkpoint_model(poi_role.role_name, HelloAgentsPoiGrounding)
        weather = self._load_checkpoint_model(weather_role.role_name, HelloAgentsWeatherGuidance)
        initial_roles_to_run: dict[str, HelloAgentsRoleConfig] = {}
        if poi_grounding is None:
            initial_roles_to_run[poi_role.role_name] = poi_role
        if weather is None:
            initial_roles_to_run[weather_role.role_name] = weather_role

        for role in initial_roles_to_run.values():
            self._emit_role_progress(role)

        if initial_roles_to_run:
            initial_execution_mode = (
                "sequential"
                if self._should_serialize_role_batch_for_endpoint_limit(initial_roles_to_run, role_llm_configs)
                else "parallel"
            )
            self._log_event(
                "helloagents_initial_specialists_parallel_started",
                message="Running missing POI discovery and weather roles.",
                roles=list(initial_roles_to_run.keys()),
                execution_mode=initial_execution_mode,
            )
            futures = self._run_role_batch(
                module=module,
                roles_to_run=initial_roles_to_run,
                role_llm_configs=role_llm_configs,
                payloads_by_role={
                    poi_role.role_name: poi_payload,
                    weather_role.role_name: weather_payload,
                },
                thread_name_prefix="helloagents-initial-specialists",
            )

            if poi_grounding is None:
                try:
                    poi_grounding = self._parse_structured_response(futures[poi_role.role_name].result(), HelloAgentsPoiGrounding)
                    self._record_checkpoint_role(poi_role.role_name, poi_grounding)
                except Exception as exc:
                    self._record_checkpoint_failure(poi_role.role_name, exc)
                    self._log_event(
                        "helloagents_poi_specialist_failed_no_fallback",
                        message="POI specialist role failed; deterministic fallback is disabled to avoid low-quality itinerary generation.",
                        level="ERROR",
                        role=poi_role.role_name,
                        reason=str(exc).strip() or exc.__class__.__name__,
                    )
                    raise
            if weather is None:
                try:
                    weather = self._parse_structured_response(futures[weather_role.role_name].result(), HelloAgentsWeatherGuidance)
                    self._record_checkpoint_role(weather_role.role_name, weather)
                except Exception as exc:
                    self._record_checkpoint_failure(weather_role.role_name, exc)
                    raise
        self._log_event("helloagents_initial_specialists_parallel_completed", message="Initial specialist roles completed.")
        weather_language_warning = self._weather_guidance_needs_language_repair(weather, request)
        poi_tool_source = (
            poi_payload.get("tool_results", {}).get("poi_source")
            if isinstance(poi_payload.get("tool_results"), dict)
            else None
        )
        self._log_event(
            "helloagents_poi_specialist_output_snapshot",
            message="POI specialist structured output snapshot parsed.",
            role=poi_role.role_name,
            poi_source=poi_tool_source,
            fallback_used=bool(poi_fallback_reason),
            fallback_reason=poi_fallback_reason,
            featured_poi_count=len(poi_grounding.featured_pois),
            candidate_area_count=len(poi_grounding.candidate_areas),
            snapshot=self._build_poi_output_snapshot(poi_grounding),
        )

        poi_collection = self._build_poi_collection(poi_grounding)
        hotel_payload = self._build_hotel_research_payload(request, brief, poi_collection=poi_collection)
        transport_payload = self._build_transport_research_payload(request, brief, poi_collection=poi_collection)

        hotel_role = role_configs["hotel_specialist"]
        transport_role = role_configs["transport_specialist"]

        hotel = self._load_checkpoint_model(hotel_role.role_name, HelloAgentsHotelRecommendation)
        transport = self._load_checkpoint_model(transport_role.role_name, HelloAgentsTransportGuidance)
        secondary_roles_to_run: dict[str, HelloAgentsRoleConfig] = {}
        if hotel is None:
            secondary_roles_to_run[hotel_role.role_name] = hotel_role
        if transport is None:
            secondary_roles_to_run[transport_role.role_name] = transport_role

        for role in secondary_roles_to_run.values():
            self._emit_role_progress(role)

        if secondary_roles_to_run:
            secondary_execution_mode = (
                "sequential"
                if self._should_serialize_role_batch_for_endpoint_limit(secondary_roles_to_run, role_llm_configs)
                else "parallel"
            )
            self._log_event(
                "helloagents_secondary_specialists_parallel_started",
                message="Running missing stay and transport roles after POI collection.",
                roles=list(secondary_roles_to_run.keys()),
                poi_count=len(poi_collection.get("pois", [])),
                area_count=len(poi_collection.get("areas", [])),
                execution_mode=secondary_execution_mode,
            )
            futures = self._run_role_batch(
                module=module,
                roles_to_run=secondary_roles_to_run,
                role_llm_configs=role_llm_configs,
                payloads_by_role={
                    hotel_role.role_name: hotel_payload,
                    transport_role.role_name: transport_payload,
                },
                thread_name_prefix="helloagents-secondary-specialists",
            )
            if hotel is None:
                try:
                    hotel = self._parse_structured_response(futures[hotel_role.role_name].result(), HelloAgentsHotelRecommendation)
                    self._record_checkpoint_role(hotel_role.role_name, hotel)
                except Exception as exc:
                    self._record_checkpoint_failure(hotel_role.role_name, exc)
                    raise
            if transport is None:
                try:
                    transport = self._parse_structured_response(futures[transport_role.role_name].result(), HelloAgentsTransportGuidance)
                    self._record_checkpoint_role(transport_role.role_name, transport)
                except Exception as exc:
                    self._record_checkpoint_failure(transport_role.role_name, exc)
                    raise
        self._log_event("helloagents_secondary_specialists_parallel_completed", message="Secondary specialist roles completed.")

        poi_tool_results = poi_payload.get("tool_results") if isinstance(poi_payload.get("tool_results"), dict) else {}
        weather_tool_results = weather_payload.get("tool_results") if isinstance(weather_payload.get("tool_results"), dict) else {}
        hotel_tool_results = hotel_payload.get("tool_results") if isinstance(hotel_payload.get("tool_results"), dict) else {}
        transport_tool_results = transport_payload.get("tool_results") if isinstance(transport_payload.get("tool_results"), dict) else {}
        poi_citations = self._extract_urls_from_search_result(poi_tool_results)
        weather_citations = [str(item).strip() for item in weather_tool_results.get("citations", []) if str(item).strip()]
        hotel_citations = self._extract_urls_from_search_result(hotel_tool_results)
        transport_citations = [str(item).strip() for item in transport_tool_results.get("citations", []) if str(item).strip()]
        if not transport_citations:
            transport_citations = self._extract_urls_from_search_result(transport_tool_results)
        grounding_documents = self._merge_grounding_documents(
            poi_tool_results.get("grounding_docs"),
            weather_tool_results.get("grounding_docs"),
            hotel_tool_results.get("grounding_docs"),
            transport_tool_results.get("grounding_docs"),
        )

        poi_extra_notes = self._build_poi_debug_notes(poi_payload, poi_grounding, poi_tool_results)
        if poi_fallback_reason:
            poi_extra_notes.insert(0, f"POI specialist fallback used after role failure: {poi_fallback_reason}")
        agent_runs.append(
            self._build_agent_run(
                poi_role,
                role_llm_configs[poi_role.role_name],
                self._summarize_pois(poi_grounding),
                extra_notes=poi_extra_notes,
                extra_citations=poi_citations,
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
        final_payload = self._load_checkpoint_model(planner_role.role_name, LlmPlanningPayload)
        planner_response = ""
        if final_payload is None:
            self._emit_role_progress(planner_role)
            planner_poi_collection = self._build_planner_poi_collection_payload(poi_collection)
            planner_weather = self._build_planner_weather_payload(weather, expected_days=max(1, (request.end_date - request.start_date).days + 1))
            planner_hotels = self._build_planner_hotels_payload(hotel)
            planner_transport = self._build_planner_transport_payload(transport)
            planner_payload = {
                "trip_request": trip_payload,
                "planning_brief": brief.model_dump(mode="json"),
                "poi_collection": planner_poi_collection,
                "weather": planner_weather,
                "hotels": planner_hotels,
                "transport": planner_transport,
                "output_schema": PLANNING_OUTPUT_SCHEMA,
            }
            self._log_event(
                "helloagents_planner_payload_ready",
                message="Planner payload assembled.",
                payload_keys=["trip_request", "planning_brief", "poi_collection", "weather", "hotels", "transport", "output_schema"],
                planner_payload_bytes=len(json.dumps(planner_payload, ensure_ascii=False)),
            )
            try:
                planner_response = self._run_role(
                    module=module,
                    role_config=planner_role,
                    llm_config=role_llm_configs[planner_role.role_name],
                    input_payload=planner_payload,
                )
                self._log_event("helloagents_planner_response_received", message="Planner response received.", response_chars=len(planner_response))
                final_payload = parse_planning_response(planner_response)
                self._record_checkpoint_role(planner_role.role_name, final_payload)
            except Exception as exc:
                self._record_checkpoint_failure(planner_role.role_name, exc)
                raise
        self._log_event("helloagents_planner_response_parsed", message="Planner response parsed into structured payload.", day_count=len(final_payload.days))
        repair_needed = planning_payload_needs_language_repair(final_payload, request)
        agent_runs.append(self._build_agent_run(planner_role, role_llm_configs[planner_role.role_name], self._summarize_itinerary(final_payload.summary, final_payload.days, final_payload.risks)))

        role_model_summary = ", ".join(f"{role_name}={role_llm_configs[role_name].model}" for role_name in _ROLE_SEQUENCE)
        role_endpoint_summary = ", ".join(
            f"{role_name}@{self._describe_endpoint(role_llm_configs[role_name])}" for role_name in _ROLE_SEQUENCE
        )
        pipeline_notes = [
            "Generated the itinerary with HelloAgents business-specialist multi-agent pipeline.",
            "Roles executed: brief_parser -> (poi_specialist || weather_specialist) -> poi_collection -> (hotel_specialist || transport_specialist) -> itinerary_planner.",
            f"Role models: {role_model_summary}.",
            f"Role endpoints: {role_endpoint_summary}.",
            "POI collection deterministically normalizes the unified POI specialist output before stay and route planning.",
            "Weather guidance is currently planning-oriented city or area segment output, not a live forecast feed.",
            "Hotel recommendations use POI cluster distribution plus configured search grounding, not a dedicated booking inventory API.",
            "Transport guidance uses POI cluster distribution and the configured search provider to ground transfer, fare, and sequencing assumptions before final planning.",
            "Executed through the HelloAgents PoC adapter boundary with third-party-only role execution.",
        ]
        if poi_fallback_reason:
            pipeline_notes.append(
                "POI specialist role failed or timed out; continued with deterministic POI grounding from trip context."
            )
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
        return final_payload, pipeline_notes, agent_runs, poi_grounding, weather, weather_citations, weather_tool_results, grounding_documents, hotel, transport

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
            # poi_specialist:
            # 中文注释：统一负责景点、街区、自然风景与非餐饮体验类 POI grounding，不生成日程顺序。
            "poi_specialist": HelloAgentsRoleConfig(
                role_name="poi_specialist",
                title="POI specialist",
                description="Discovers core attraction, district, scenery, and non-food experience POIs with compact evidence.",
                prompt_focus="Use trip_request, planning_brief, poi_context, and native search when the configured POI model supports it; do not call external tools, plan the final itinerary, include food/cafe stops, or pass long evidence.",
                agent_class_name="SimpleAgent",
                system_prompt=f"{poi_prompt.system_prompt} {language_instruction}{locale_clause}",
                prompt_version=poi_prompt.version,
                progress_percent=44,
                max_tokens=3200,
                retry_attempts=1,
                min_timeout_seconds=120.0,
                timeout_cap_seconds=180.0,
                stream=True,
            ),
            # weather_specialist:
            # 中文注释：负责天气 planning guidance，强调季节性和可执行建议，不伪装成实时预报。
            "weather_specialist": HelloAgentsRoleConfig(
                role_name="weather_specialist",
                title="Weather specialist",
                description="Produces city or area weather guidance, timing advice, and packing notes.",
                prompt_focus="Use Grok's native search context when this role runs on Grok; otherwise use MCP tool results. Return weather guidance JSON only.",
                agent_class_name="SimpleAgent",
                system_prompt=f"{weather_prompt.system_prompt} {language_instruction}{locale_clause}",
                prompt_version=weather_prompt.version,
                progress_percent=52,
                stream=True,
            ),
            # hotel_specialist:
            # 中文注释：负责住宿区域与候选酒店建议，目标是降低转场成本并匹配预算。
            "hotel_specialist": HelloAgentsRoleConfig(
                role_name="hotel_specialist",
                title="Hotel specialist",
                description="Recommends stay areas and hotels based on POI clusters, budget, and pace.",
                prompt_focus="Use poi_collection, stay preference, budget, candidate hotels, and Grok native search context when this role runs on Grok; otherwise use MCP tool results. Return hotel recommendation JSON only.",
                agent_class_name="SimpleAgent",
                system_prompt=f"{hotel_prompt.system_prompt} {language_instruction}{locale_clause}",
                prompt_version=hotel_prompt.version,
                progress_percent=62,
                max_tokens=1800,
                stream=True,
            ),
            # transport_specialist:
            # 中文注释：负责交通票价、换乘约束和到离程策略，把交通价格与时效从最终 planner 里拆出来单独 grounding。
            "transport_specialist": HelloAgentsRoleConfig(
                role_name="transport_specialist",
                title="Transport specialist",
                description="Builds grounded transport options, pricing constraints, and transfer strategy.",
                prompt_focus="Use poi_collection, the trip brief, and Grok native search context when this role runs on Grok; otherwise use MCP tool results. Return transport guidance JSON only, including grounded cost estimates.",
                agent_class_name="SimpleAgent",
                system_prompt=f"{transport_prompt.system_prompt} {language_instruction}{locale_clause}",
                prompt_version=transport_prompt.version,
                progress_percent=68,
                max_tokens=1600,
                stream=True,
            ),
            # itinerary_planner:
            # 中文注释：最终总控角色，复用主 planner prompt，再消费四份结构化中间结果生成最终 itinerary。
            "itinerary_planner": HelloAgentsRoleConfig(
                role_name="itinerary_planner",
                title="Itinerary planner",
                description="Combines the POI collection, weather, hotel strategy, and transport constraints into the final itinerary draft.",
                prompt_focus="Return the final itinerary JSON using the brief, poi_collection, weather guidance, hotel strategy, and transport guidance.",
                agent_class_name="SimpleAgent",
                system_prompt=f"{planner_prompt.system_prompt} {language_instruction}{locale_clause}",
                prompt_version=planner_prompt.version,
                progress_percent=82,
                stream=True,
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

    def _run_role_batch(
        self,
        *,
        module: Any,
        roles_to_run: dict[str, HelloAgentsRoleConfig],
        role_llm_configs: dict[str, LlmEndpointConfig],
        payloads_by_role: dict[str, dict[str, Any]],
        thread_name_prefix: str,
    ) -> dict[str, Future]:
        if self._should_serialize_role_batch_for_endpoint_limit(roles_to_run, role_llm_configs):
            self._log_event(
                "helloagents_specialist_batch_serialized",
                message="Serializing streaming search roles that share the same upstream endpoint to reduce 429 rate-limit failures.",
                roles=list(roles_to_run.keys()),
                thread_name_prefix=thread_name_prefix,
            )
            futures: dict[str, Future] = {}
            for role_name, role_config in roles_to_run.items():
                future: Future = Future()
                try:
                    future.set_result(
                        self._run_role(
                            module=module,
                            role_config=role_config,
                            llm_config=role_llm_configs[role_name],
                            input_payload=payloads_by_role[role_name],
                        )
                    )
                except Exception as exc:
                    future.set_exception(exc)
                futures[role_name] = future
            return futures

        with ThreadPoolExecutor(max_workers=max(1, len(roles_to_run)), thread_name_prefix=thread_name_prefix) as executor:
            return {
                role_name: executor.submit(
                    self._run_role,
                    module=module,
                    role_config=role_config,
                    llm_config=role_llm_configs[role_name],
                    input_payload=payloads_by_role[role_name],
                )
                for role_name, role_config in roles_to_run.items()
            }

    def _should_serialize_role_batch_for_endpoint_limit(
        self,
        roles_to_run: dict[str, HelloAgentsRoleConfig],
        role_llm_configs: dict[str, LlmEndpointConfig],
    ) -> bool:
        if len(roles_to_run) < 2:
            return False
        shared_streaming_search_roles: dict[tuple[str, str, str], list[str]] = {}
        for role_name, role_config in roles_to_run.items():
            llm_config = role_llm_configs[role_name]
            if not role_config.stream or not self._role_config_uses_search_capable_grok(role_name, llm_config):
                continue
            identity = self._rate_limit_identity(llm_config)
            shared_streaming_search_roles.setdefault(identity, []).append(role_name)
        return any(len(role_names) > 1 for role_names in shared_streaming_search_roles.values())

    def _has_native_search(self, role_name: str, llm_config: LlmEndpointConfig | None) -> bool:
        """Single source of truth for whether a role's configured model can search the web natively.

        A model is treated as natively search-capable when it is a Grok model (direct x.ai or by
        model name) or when a search-eligible role is routed through the rainflow proxy channel.
        """
        if llm_config is None:
            return False
        model = str(getattr(llm_config, "model", "") or "").strip().lower()
        base_url = str(getattr(llm_config, "base_url", "") or "").strip().lower()
        if "grok" in model or "x.ai" in base_url:
            return True
        return role_name in {"poi_specialist", *_DIRECT_GROK_SEARCH_ROLES} and "rainflow" in base_url

    def _role_config_uses_search_capable_grok(self, role_name: str, llm_config: LlmEndpointConfig) -> bool:
        return self._has_native_search(role_name, llm_config)

    def _rate_limit_identity(self, llm_config: LlmEndpointConfig) -> tuple[str, str, str]:
        protocol = str(getattr(llm_config, "provider_protocol", "") or "").strip().lower()
        base_url = str(getattr(llm_config, "base_url", "") or "").strip().rstrip("/").lower()
        api_key = str(getattr(llm_config, "api_key", "") or "").strip()
        return protocol, base_url, api_key

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

        effective_llm_config = llm_config
        if role_config.timeout_cap_seconds is not None:
            capped_timeout = min(float(llm_config.timeout_seconds), float(role_config.timeout_cap_seconds))
            effective_llm_config = llm_config.model_copy(update={"timeout_seconds": capped_timeout})
        llm = HelloAgentsCompatibleLLM(
            effective_llm_config,
            temperature=role_config.temperature,
            max_tokens=role_config.max_tokens,
            retry_attempts=role_config.retry_attempts,
            min_timeout_seconds=role_config.min_timeout_seconds,
            stream=role_config.stream,
        )
        enriched_payload = self._augment_payload_with_tool_results(role_config.role_name, input_payload)
        prompt_payload = self._build_role_prompt_payload(enriched_payload, role_name=role_config.role_name)
        prompt_payload_json = json.dumps(prompt_payload, ensure_ascii=False)
        if role_config.role_name == "poi_specialist":
            self._log_event(
                "helloagents_poi_specialist_input_snapshot",
                message="POI specialist input snapshot prepared.",
                role=role_config.role_name,
                snapshot=self._build_poi_input_snapshot(enriched_payload),
            )
        agent_config = None
        config_class = getattr(module, "Config", None)
        if config_class is not None:
            try:
                # Disable third-party trace files/console output. Our own job logs already
                # capture the execution trace, and the upstream package's finalize() path
                # prints emoji markers that can crash under GBK terminals on Windows.
                agent_config = config_class(trace_enabled=False)
            except Exception:
                agent_config = None
        agent = agent_class(
            name=role_config.role_name,
            llm=llm,
            system_prompt=role_config.system_prompt,
            config=agent_config,
            enable_tool_calling=False,
        )
        started = time.perf_counter()
        self._log_event(
            "helloagents_role_started",
            message=f"Role {role_config.role_name} started.",
            role=role_config.role_name,
            endpoint=self._describe_endpoint(effective_llm_config),
            model=effective_llm_config.model,
            payload_keys=sorted(prompt_payload.keys()),
            payload_bytes=len(prompt_payload_json.encode("utf-8")),
            max_tokens=role_config.max_tokens,
            retry_attempts=role_config.retry_attempts,
            timeout_seconds=llm.kwargs["timeout"],
            stream=llm.kwargs["stream"],
        )
        try:
            response = agent.run(prompt_payload_json)
        except Exception as exc:
            endpoint = self._describe_endpoint(effective_llm_config)
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
                model=effective_llm_config.model,
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
            endpoint=self._describe_endpoint(effective_llm_config),
            model=effective_llm_config.model,
            elapsed_seconds=round(max(time.perf_counter() - started, 0.0), 3),
            response_chars=len(content),
        )
        return content

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

    def _build_poi_output_snapshot(self, grounding: HelloAgentsPoiGrounding) -> dict[str, Any]:
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
        grounding: HelloAgentsPoiGrounding,
        tool_results: dict[str, Any],
    ) -> list[str]:
        input_snapshot = self._build_poi_input_snapshot(input_payload)
        poi_names = [
            f"{self._normalize_poi_collection_kind(poi)}:{poi.name}@{poi.area or 'unknown'}({poi.confidence or 'low'})"
            for poi in grounding.featured_pois[:12]
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

    def _build_role_prompt_payload(self, enriched_payload: dict[str, Any], *, role_name: str = "") -> dict[str, Any]:
        prompt_payload = deepcopy(enriched_payload)
        tool_results = prompt_payload.get("tool_results")
        if isinstance(tool_results, dict):
            if role_name == "poi_specialist":
                prompt_payload["tool_results"] = self._compact_poi_tool_results_for_prompt(tool_results)
            elif role_name in {"hotel_specialist", "transport_specialist"}:
                prompt_payload["tool_results"] = self._compact_grounding_tool_results_for_prompt(tool_results)
            else:
                prompt_payload["tool_results"] = self._strip_tool_url_metadata(tool_results)
        return prompt_payload

    def _compact_grounding_tool_results_for_prompt(self, tool_results: dict[str, Any]) -> dict[str, Any]:
        crawl_urls = tool_results.get("crawl_urls") if isinstance(tool_results.get("crawl_urls"), list) else []
        compact: dict[str, Any] = {
            "research_tool": tool_results.get("research_tool"),
            "search_tool": tool_results.get("search_tool"),
            "search_query": tool_results.get("search_query"),
            "fallback_search_tool": tool_results.get("fallback_search_tool"),
            "crawl_tool": tool_results.get("crawl_tool"),
            "crawl_urls": [str(item).strip() for item in crawl_urls if str(item).strip()][:3],
            "citations": self._extract_urls_from_search_result(tool_results)[:12],
            "evidence_brief": self._build_poi_evidence_brief(tool_results, limit=10),
        }
        return {key: value for key, value in compact.items() if value not in (None, "", [], {})}

    def _compact_poi_tool_results_for_prompt(self, tool_results: dict[str, Any]) -> dict[str, Any]:
        crawl_urls = tool_results.get("crawl_urls") if isinstance(tool_results.get("crawl_urls"), list) else []
        citations = self._extract_urls_from_search_result(tool_results)[:10]
        compact: dict[str, Any] = {
            "poi_source": tool_results.get("poi_source"),
            "research_tool": tool_results.get("research_tool"),
            "search_tool": tool_results.get("search_tool"),
            "search_query": tool_results.get("search_query"),
            "answer": self._compact_tool_value_for_prompt(tool_results.get("answer"), max_list_items=4, text_limit=700),
            "crawl_tool": tool_results.get("crawl_tool"),
            "crawl_urls": [str(item).strip() for item in crawl_urls if str(item).strip()][:3],
            "citations": citations,
            "evidence_brief": self._build_poi_evidence_brief(tool_results, limit=12),
        }
        return {key: value for key, value in compact.items() if value not in (None, "", [], {})}

    def _build_poi_evidence_brief(self, tool_results: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        def clean_text(value: Any, *, text_limit: int = 320) -> str:
            normalized = re.sub(r"\s+", " ", str(value or "")).strip()
            if len(normalized) <= text_limit:
                return normalized
            return f"{normalized[:text_limit].rstrip()}..."

        def add_record(*, title: Any = "", url: Any = "", summary: Any = "", source_type: str = "", place_name: Any = "", category: Any = "") -> None:
            if len(records) >= limit:
                return
            title_text = clean_text(title, text_limit=90)
            url_text = str(url or "").strip()
            summary_text = clean_text(summary, text_limit=360)
            place_text = clean_text(place_name, text_limit=60)
            category_text = clean_text(category, text_limit=60)
            if not any((title_text, url_text, summary_text, place_text, category_text)):
                return
            key = ((url_text or title_text).casefold(), summary_text[:80].casefold())
            if key in seen:
                return
            seen.add(key)
            record = {
                "source_type": source_type,
                "title": title_text,
                "url": url_text,
                "place_name": place_text,
                "category": category_text,
                "summary": summary_text,
            }
            records.append({key: value for key, value in record.items() if value not in (None, "", [], {})})

        grounding_docs = tool_results.get("grounding_docs") if isinstance(tool_results.get("grounding_docs"), list) else []
        for doc in grounding_docs:
            if not isinstance(doc, dict):
                continue
            add_record(
                title=doc.get("title") or doc.get("name"),
                url=doc.get("url") or doc.get("source_url"),
                summary=doc.get("summary") or doc.get("snippet") or doc.get("description"),
                source_type=str(doc.get("source_type") or doc.get("platform") or "grounding_doc"),
                place_name=doc.get("place_name"),
                category=doc.get("category"),
            )

        def visit_source_items(value: Any, *, source_type: str) -> None:
            if len(records) >= limit:
                return
            if isinstance(value, dict):
                sources = value.get("sources") or value.get("results")
                if isinstance(sources, list):
                    for item in sources[:8]:
                        visit_source_items(item, source_type=source_type)
                    return
                add_record(
                    title=value.get("title") or value.get("name") or value.get("source"),
                    url=value.get("url") or value.get("link") or value.get("website") or value.get("source_url"),
                    summary=value.get("snippet") or value.get("summary") or value.get("description") or value.get("content") or value.get("text"),
                    source_type=source_type,
                    place_name=value.get("place_name"),
                    category=value.get("category"),
                )
                return
            if isinstance(value, list):
                for item in value[:8]:
                    visit_source_items(item, source_type=source_type)

        visit_source_items(tool_results.get("answer"), source_type="answer_source")
        visit_source_items(tool_results.get("search"), source_type="search_source")

        crawl_value = tool_results.get("crawl")
        if isinstance(crawl_value, dict) and isinstance(crawl_value.get("results"), list):
            crawl_items = crawl_value.get("results") or []
        else:
            crawl_items = crawl_value if isinstance(crawl_value, list) else [crawl_value]
        for item in crawl_items[:3]:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or item.get("markdown") or item.get("raw_content")
                add_record(
                    title=item.get("title") or item.get("name") or "Fetched page excerpt",
                    url=item.get("url") or item.get("source_url"),
                    summary=text,
                    source_type="crawl_excerpt",
                )
            elif isinstance(item, str):
                add_record(title="Fetched page excerpt", summary=item, source_type="crawl_excerpt")

        if not records:
            for key in ("answer", "search", "crawl"):
                value = tool_results.get(key)
                if value is not None:
                    add_record(title=key, summary=json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value, source_type=key)
        return records

    def _compact_tool_value_for_prompt(self, value: Any, *, max_list_items: int, text_limit: int) -> Any:
        if isinstance(value, dict):
            compact: dict[str, Any] = {}
            preferred_keys = (
                "url",
                "link",
                "website",
                "source_url",
                "title",
                "name",
                "source",
                "snippet",
                "summary",
                "description",
                "answer",
                "text",
                "content",
                "markdown",
                "raw_content",
                "published_date",
                "score",
                "results",
                "sources",
            )
            for key in preferred_keys:
                if key not in value:
                    continue
                item = value.get(key)
                compact_value = self._compact_tool_value_for_prompt(item, max_list_items=max_list_items, text_limit=text_limit)
                if compact_value not in (None, "", [], {}):
                    compact[key] = compact_value
            if compact:
                return compact
            for key, item in list(value.items())[:8]:
                compact_value = self._compact_tool_value_for_prompt(item, max_list_items=max_list_items, text_limit=text_limit)
                if compact_value not in (None, "", [], {}):
                    compact[str(key)] = compact_value
            return compact
        if isinstance(value, list):
            return [
                compact_item
                for compact_item in (
                    self._compact_tool_value_for_prompt(item, max_list_items=max_list_items, text_limit=text_limit)
                    for item in value[:max_list_items]
                )
                if compact_item not in (None, "", [], {})
            ]
        if isinstance(value, str):
            normalized = re.sub(r"\s+", " ", value).strip()
            if len(normalized) <= text_limit:
                return normalized
            return f"{normalized[:text_limit].rstrip()} ... [truncated {len(normalized) - text_limit} chars]"
        return value

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

    def _build_poi_research_payload(self, request: PlanningRequest, brief: HelloAgentsBrief) -> dict[str, Any]:
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

    def _build_attraction_research_payload(self, request: PlanningRequest, brief: HelloAgentsBrief) -> dict[str, Any]:
        queries = [*brief.interests, *brief.must_have, request.destination, "local highlights"]
        return {
            "trip_request": self._build_trip_payload(request),
            "planning_brief": brief.model_dump(mode="json"),
            "candidate_attractions": self._collect_poi_candidates(request, queries, limit=8),
        }

    def _build_food_research_payload(self, request: PlanningRequest, brief: HelloAgentsBrief) -> dict[str, Any]:
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

    def _build_weather_research_payload(self, request: PlanningRequest, brief: HelloAgentsBrief) -> dict[str, Any]:
        trip_days = max(1, (request.end_date - request.start_date).days + 1)
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
        }

    def _build_hotel_research_payload(self, request: PlanningRequest, brief: HelloAgentsBrief, *, poi_collection: dict[str, Any] | None = None) -> dict[str, Any]:
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

    def _build_transport_research_payload(self, request: PlanningRequest, brief: HelloAgentsBrief, *, poi_collection: dict[str, Any] | None = None) -> dict[str, Any]:
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

    def _build_planner_poi_collection_payload(self, poi_collection: dict[str, Any]) -> dict[str, Any]:
        pois = poi_collection.get("pois") if isinstance(poi_collection.get("pois"), list) else []
        areas = poi_collection.get("areas") if isinstance(poi_collection.get("areas"), list) else []
        typed_pois = [item for item in pois if isinstance(item, dict)]
        attraction_pois = [item for item in typed_pois if not self._is_food_poi_dict(item)]
        food_pois = [item for item in typed_pois if self._is_food_poi_dict(item)]
        return {
            "pois": attraction_pois[:12],
            "attraction_pois": attraction_pois[:10],
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
        }

    def _build_planner_weather_payload(self, weather: HelloAgentsWeatherGuidance, *, expected_days: int) -> dict[str, Any]:
        return {
            "overall_outlook": self._truncate_planner_text(weather.overall_outlook, 180),
            "daily_outlook": self._compact_planner_text_list(weather.daily_outlook, limit=expected_days, text_limit=120),
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

    def _build_planner_hotels_payload(self, hotel: HelloAgentsHotelRecommendation) -> dict[str, Any]:
        verified_candidates = [candidate for candidate in hotel.hotel_candidates if self._is_verified_hotel_candidate(candidate)]
        final_hotel = hotel.final_recommended_hotel if self._is_verified_hotel_candidate(hotel.final_recommended_hotel) else None
        if final_hotel is None and verified_candidates:
            final_hotel = verified_candidates[0]
        hotel_risks = [str(item).strip() for item in hotel.hotel_risks if str(item).strip()]
        if (hotel.final_recommended_hotel or hotel.hotel_candidates) and final_hotel is None:
            hotel_risks.append("Hotel specialist returned concrete hotel names without source URLs; planner received area-level stay guidance only.")
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
            "source_urls": [str(item).strip() for item in candidate.source_urls if str(item).strip()][:4],
        }

    def _build_stay_recommendation(self, hotel: HelloAgentsHotelRecommendation | None) -> StayRecommendation | None:
        if hotel is None:
            return None
        verified_candidates = [candidate for candidate in hotel.hotel_candidates if self._is_verified_hotel_candidate(candidate)]
        final_hotel = hotel.final_recommended_hotel if self._is_verified_hotel_candidate(hotel.final_recommended_hotel) else None
        if final_hotel is None and verified_candidates:
            final_hotel = verified_candidates[0]
        hotel_risks = [str(item).strip() for item in hotel.hotel_risks if str(item).strip()]
        if (hotel.final_recommended_hotel or hotel.hotel_candidates) and final_hotel is None:
            hotel_risks.append("Hotel specialist returned concrete hotel names without source URLs; final itinerary keeps area-level stay guidance only.")
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

    def _hotel_candidate_to_stay_candidate(self, candidate: HelloAgentsHotelCandidate) -> StayHotelCandidate:
        return StayHotelCandidate(
            name=candidate.name,
            area=candidate.area or None,
            hotel_type=candidate.hotel_type or None,
            reason=candidate.reason or None,
            price_hint=candidate.price_hint or None,
            price_checked_at=candidate.price_checked_at or None,
            price_valid_for=candidate.price_valid_for or None,
            review_score=candidate.review_score or None,
            review_count=candidate.review_count or None,
            review_summary=candidate.review_summary or None,
            preference_match=candidate.preference_match or None,
            booking_confidence=candidate.booking_confidence or None,
            caveats=[str(item).strip() for item in candidate.caveats if str(item).strip()][:4],
            source_urls=[str(item).strip() for item in candidate.source_urls if str(item).strip()][:4],
        )

    def _is_verified_hotel_candidate(self, candidate: HelloAgentsHotelCandidate | None) -> bool:
        if candidate is None:
            return False
        if not candidate.name.strip():
            return False
        return any(str(url).strip() for url in candidate.source_urls)

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

    def _is_food_poi(self, poi: HelloAgentsResearchPoi | HelloAgentsFoodPoi | None) -> bool:
        if poi is None:
            return False
        if isinstance(poi, HelloAgentsFoodPoi):
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

    def _normalize_poi_collection_kind(self, poi: HelloAgentsResearchPoi) -> str:
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
        poi_grounding: HelloAgentsPoiGrounding,
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
            }
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
            "pois": pois[:16],
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
            _LOGGER.warning("HelloAgents role=poi_specialist tool=%s failed=%s", search_tool, exc)
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
            _LOGGER.warning("HelloAgents role=poi_specialist grounding_failed=%s", exc)
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
                _LOGGER.warning("HelloAgents role=hotel_specialist tool=%s failed=%s", search_tool, exc)
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
            _LOGGER.warning("HelloAgents role=transport_specialist tool=%s failed=%s", search_tool, exc)
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
        _LOGGER.debug("HelloAgents role=%s tool=%s args=%s", role_name, tool_name, json.dumps(arguments, ensure_ascii=False))
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

    def _build_weather_segments(self, request: PlanningRequest, brief: HelloAgentsBrief) -> list[dict[str, Any]]:
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

    def _weather_guidance_needs_language_repair(self, weather: HelloAgentsWeatherGuidance, request: PlanningRequest) -> bool:
        locale = infer_output_locale(request)
        texts = [
            weather.overall_outlook,
            *weather.daily_outlook,
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

    def _summarize_pois(self, grounding: HelloAgentsPoiGrounding) -> str:
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

    def _summarize_weather(self, weather: HelloAgentsWeatherGuidance) -> str:
        return (
            f"{self._truncate_planner_text(weather.overall_outlook, 120)} "
            f"{len(weather.segments)} weather segments, {len(weather.packing_notes)} packing notes, {len(weather.weather_risks)} weather risks."
        )

    def _summarize_foods(self, foods: HelloAgentsFoodRecommendation) -> str:
        reliable_prices = sum(1 for poi in foods.featured_pois if poi.price_hint and poi.price_hint.strip().lower() != "unknown")
        reliable_reviews = sum(1 for poi in foods.featured_pois if poi.review_score and poi.review_score.strip().lower() != "unknown")
        return (
            f"{len(foods.candidate_areas)} food areas, "
            f"{len(foods.featured_pois)} food POIs, "
            f"{reliable_prices} with price evidence, "
            f"{reliable_reviews} with review signals."
        )

    def _summarize_hotels(self, hotels: HelloAgentsHotelRecommendation) -> str:
        verified_candidates = [candidate for candidate in hotels.hotel_candidates if self._is_verified_hotel_candidate(candidate)]
        selected = (
            hotels.final_recommended_hotel.name
            if self._is_verified_hotel_candidate(hotels.final_recommended_hotel)
            else "none"
        )
        return (
            f"selected hotel {selected}, "
            f"{len(hotels.recommended_areas)} stay areas, "
            f"{len(verified_candidates)}/{len(hotels.hotel_candidates)} source-backed hotel candidates, "
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

    def _format_weather_segment_note(self, segment: HelloAgentsWeatherSegment) -> str:
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
        poi_grounding: HelloAgentsPoiGrounding | HelloAgentsAttractionGrounding | None,
    ) -> HelloAgentsResearchPoi | None:
        if poi_grounding is None:
            return None
        target = self._normalize_match_key(item_name)
        if not target:
            return None
        best_match: HelloAgentsResearchPoi | None = None
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

    def _find_matching_featured_food(
        self,
        item_name: str,
        poi_grounding: HelloAgentsPoiGrounding | HelloAgentsFoodRecommendation | None,
    ) -> HelloAgentsResearchPoi | HelloAgentsFoodPoi | None:
        if poi_grounding is None:
            return None
        target = self._normalize_match_key(item_name)
        if not target:
            return None
        best_match: HelloAgentsResearchPoi | HelloAgentsFoodPoi | None = None
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

    def _build_attraction_booking_info(self, poi: HelloAgentsResearchPoi | None) -> BookingInfo | None:
        if poi is None:
            return None
        base = (
            BookingInfo.model_validate(poi.booking_info.model_dump(mode="json"))
            if poi.booking_info is not None
            else BookingInfo()
        )
        evidence_notes = [
            *([f"Category: {poi.category}"] if poi.category else []),
            *([f"Confidence: {poi.confidence}"] if poi.confidence else []),
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

    def _build_food_booking_info(self, food_poi: HelloAgentsResearchPoi | HelloAgentsFoodPoi | None) -> BookingInfo | None:
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
            compact_candidate = self._truncate_planner_text(candidate, 110)
            if compact_candidate and compact_candidate not in notes:
                notes.append(compact_candidate)
        if not notes:
            for segment in weather_guidance.segments[:1]:
                segment_note = self._format_weather_segment_note(segment)
                if segment_note and segment_note not in notes:
                    notes.append(segment_note)
        temperature_hint = self._resolve_weather_temperature_hint(day_index, weather_guidance, weather_tool_results)
        if temperature_hint:
            if not self._contains_temperature_signal(summary) and temperature_hint.casefold() not in summary.casefold():
                summary = f"{summary} {temperature_hint}".strip() if summary else temperature_hint
            elif all(temperature_hint.casefold() not in note.casefold() for note in notes):
                notes.insert(0, self._truncate_planner_text(temperature_hint, 80))
        summary = self._truncate_planner_text(summary, 150)
        citation_list = [str(item).strip() for item in (citations or []) if str(item).strip()]
        if not summary and not notes and not citation_list:
            return None
        return PlannedDayWeather(summary=summary, notes=notes[:2], citations=citation_list[:3])
    def _build_result_from_payload(
        self,
        payload: Any,
        request: PlanningRequest,
        pipeline_notes: list[str],
        agent_runs: list[AgentRunStep],
        *,
        poi_grounding: HelloAgentsPoiGrounding | None = None,
        weather_guidance: HelloAgentsWeatherGuidance | None = None,
        weather_citations: list[str] | None = None,
        weather_tool_results: dict[str, Any] | None = None,
        grounding_documents: list[dict[str, Any]] | None = None,
        hotel_recommendation: HelloAgentsHotelRecommendation | None = None,
        transport_guidance: HelloAgentsTransportGuidance | None = None,
    ) -> PlanningResult:
        expected_days = max(1, (request.end_date - request.start_date).days + 1)
        if len(payload.days) != expected_days:
            raise ValueError(f"Expected {expected_days} day entries but received {len(payload.days)}")

        zh_output = is_chinese_output(request)
        route_mode = self._resolve_route_mode(request.transport_mode)
        planned_days: list[PlannedDay] = []
        filtered_food_item_count = 0

        for day_index, day in enumerate(payload.days, start=1):
            day_items = [item for item in day.items if not self._should_exclude_food_itinerary_item(item)]
            filtered_food_item_count += max(0, len(day.items) - len(day_items))
            poi_details = [self._resolve_item_poi(item, request, preferred_index=day_index + item_index) for item_index, item in enumerate(day_items)]
            route_stops = [poi_to_route_stop(poi) for poi in poi_details]
            route_matrix = self._maps_provider.batch_route_matrix(route_stops, mode=route_mode) if route_stops else None
            matrix_lookup = {
                (cell.origin_stop_id, cell.destination_stop_id): cell
                for cell in (route_matrix.cells if route_matrix is not None else [])
            }

            planned_items: list[PlannedItem] = []
            previous_stop = None
            for item_index, item in enumerate(day_items):
                poi = poi_details[item_index]
                current_stop = route_stops[item_index]
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
                    if isinstance(matched_food, HelloAgentsResearchPoi)
                    else None
                )
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
                            fallback_booking_info,
                            item_name=item.name,
                            grounding_documents=grounding_documents,
                        ),
                        visit_requirements=self._merge_visit_requirements(
                            getattr(item, "visit_requirements", None),
                            fallback_visit_requirements,
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

        if filtered_food_item_count:
            pipeline_notes.append(
                f"Filtered {filtered_food_item_count} food/cafe/restaurant itinerary item(s) from the final guide."
            )

        host = urlparse(self._llm_config.base_url).netloc or self._llm_config.base_url
        total_budget = payload.total_budget_estimate if payload.total_budget_estimate and payload.total_budget_estimate > 0 else request.budget
        plan = PlanningResult(
            summary=payload.summary,
            total_budget_estimate=total_budget,
            days=planned_days,
            risks=payload.risks,
            stay_recommendation=self._build_stay_recommendation(hotel_recommendation),
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
