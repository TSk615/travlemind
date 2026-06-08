from __future__ import annotations

import json
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from travelmind_api.agents.base import AgentRunStep, PlannedItem, PlanningRequest, PlanningResult
from travelmind_api.core.env import get_env
from travelmind_api.prompts.roles.helloagents import (
    IMAGE_CURATOR_PROMPT_VERSION,
    IMAGE_QUERY_PLANNER_PROMPT_VERSION,
    IMAGE_REVIEWER_PROMPT_VERSION,
    build_image_curator_prompt,
    build_image_query_planner_prompt,
    build_image_reviewer_prompt,
)
from travelmind_api.services.llm import LlmConfig, OpenAICompatibleClient
from travelmind_api.services.search_connector import ConfiguredSearchGateway, SearchServiceConfig

_VISUAL_ITEM_TYPES = {"sight", "photo", "explore"}
_TIER_IMAGE_COUNTS = {"high": 3, "medium": 2, "low": 1, "skipped": 0}
_IMAGE_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_IMAGE_EXTENSION_PATTERN = re.compile(r"\.(?:png|jpe?g|webp|gif|bmp|svg)(?:$|[?#])", re.IGNORECASE)
_IMAGE_HINT_PATTERN = re.compile(r"(?:image|photo|thumbnail|hero|cover|poster)", re.IGNORECASE)
_OG_IMAGE_PATTERN = re.compile(r"(?:og:image|twitter:image)[^\"'>]*[\"'](https?://[^\"']+)", re.IGNORECASE)
_WHITESPACE_PATTERN = re.compile(r"\s+")
_ENGLISH_TOKEN_PATTERN = re.compile(r"[a-z0-9]{3,}", re.IGNORECASE)
_CJK_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,}")
_PAGE_CHROME_PATTERN = re.compile(
    r"(logo|favicon|icon|sprite|avatar|banner|header|footer|placeholder|loading|brand|nav|wechat|weixin|qr(?:code)?|小程序|公众号)",
    re.IGNORECASE,
)
_GENERIC_EXPLORE_PATTERN = re.compile(
    r"(walk|stroll|slow walk|free time|neighborhood|wander|散步|漫步|步行|闲逛|自由活动|逛街)",
    re.IGNORECASE,
)
_IMAGE_AGENT_RUN_KEYS = {"image_curator", "attraction_image_specialist", "image_reviewer"}
_DIRECT_IMAGE_COUNT_PER_ITEM = 1
_DIRECT_IMAGE_SEARCH_RESULT_COUNT = 6
_DIRECT_IMAGE_MAX_WORKERS = 3
_HIGH_PRIORITY_IMAGE_MAX_WORKERS = 3
_MAX_REVIEW_CANDIDATES = 5
_STRATEGY_SUFFIX_PATTERN = re.compile(
    r"(二刷|再逛|酒店周边|商圈漫步|周边漫步|周边散步|附近漫步|附近散步|walk|stroll|free time|slow walk|nearby.*walk|surrounding.*walk)",
    re.IGNORECASE,
)
_SEPARATOR_PATTERN = re.compile(r"\s*(?:/|／|｜|\||·|•|、|与|和|及| plus | and | or | 或)\s*", re.IGNORECASE)


class ImageCuratorSelection(BaseModel):
    item_id: str
    priority_tier: str = "skipped"
    reason: str = ""
    suggested_image_count: int = 0

    @field_validator("priority_tier", mode="before")
    @classmethod
    def _normalize_priority_tier(cls, value: Any) -> str:
        normalized = str(value or "").strip().lower()
        return normalized if normalized in _TIER_IMAGE_COUNTS else "skipped"

    @field_validator("reason", mode="before")
    @classmethod
    def _normalize_reason(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("suggested_image_count", mode="before")
    @classmethod
    def _normalize_image_count(cls, value: Any) -> int:
        try:
            count = int(value)
        except (TypeError, ValueError):
            count = 0
        return max(0, min(3, count))


class ImageCuratorResponse(BaseModel):
    items: list[ImageCuratorSelection] = Field(default_factory=list)


class ImageSearchOutcome(BaseModel):
    item_id: str
    image_urls: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    status: str = "failed"
    failure_reason: str | None = None
    candidate_count_raw: int = 0
    candidate_count_after_rules: int = 0
    candidate_count_after_review: int = 0
    review_mode: str = "rules_only"
    review_summary: str | None = None
    review_rejection_reasons: list[str] = Field(default_factory=list)
    debug_query: str | None = None
    debug_candidates_raw: list[dict[str, Any]] = Field(default_factory=list)
    debug_candidates_after_rules: list[dict[str, Any]] = Field(default_factory=list)
    debug_candidates_after_review: list[dict[str, Any]] = Field(default_factory=list)


class ImageQueryPlan(BaseModel):
    canonical_name: str = ""
    aliases: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    reason: str = ""
    mode: str = "fallback"


class TavilyImageCandidate(BaseModel):
    url: str
    source_url: str = ""
    source_title: str = ""
    source_snippet: str = ""
    image_description: str = ""
    origin: str = "result"
    result_rank: int = 0
    image_index: int = 0


class ImageReviewerSelectedCandidate(BaseModel):
    candidate_id: str
    reason: str = ""
    confidence: str = "medium"


class ImageReviewerRejectedCandidate(BaseModel):
    candidate_id: str
    reason: str = ""


class ImageReviewerResponse(BaseModel):
    selected_candidates: list[ImageReviewerSelectedCandidate] = Field(default_factory=list)
    rejected_candidates: list[ImageReviewerRejectedCandidate] = Field(default_factory=list)
    summary: str = ""


def enrich_plan_images(
    plan: PlanningResult,
    request: PlanningRequest,
    *,
    llm_config: LlmConfig | None,
    search_service: SearchServiceConfig | None,
) -> PlanningResult:
    _ = llm_config
    visual_items = _collect_and_prepare_visual_items(plan)
    plan.trace.agent_runs = [run for run in plan.trace.agent_runs if run.key not in _IMAGE_AGENT_RUN_KEYS]

    specialist_run = _run_direct_tavily_image_specialist(
        request,
        search_service=search_service,
        visual_items=visual_items,
    )
    plan.trace.agent_runs.append(specialist_run)
    return plan


def prepare_plan_images_for_async_enrichment(plan: PlanningResult) -> PlanningResult:
    _collect_and_prepare_visual_items(plan)
    plan.trace.agent_runs = [run for run in plan.trace.agent_runs if run.key not in _IMAGE_AGENT_RUN_KEYS]
    return plan


def _collect_and_prepare_visual_items(plan: PlanningResult) -> list[PlannedItem]:
    visual_items: list[PlannedItem] = []
    for day in plan.days:
        for item in day.items:
            item.image_urls = []
            item.image_source_urls = []
            item.image_failure_reason = None
            if _is_visual_candidate(item):
                item.image_status = "pending"
                item.image_priority_tier = None
                item.image_priority_reason = None
                visual_items.append(item)
            else:
                item.image_status = "skipped"
                item.image_priority_tier = "skipped"
                item.image_priority_reason = None
    return visual_items


def _is_visual_candidate(item: PlannedItem) -> bool:
    item_type = str(item.type or "").strip().lower()
    if item_type not in _VISUAL_ITEM_TYPES:
        return False
    name = str(item.name or "").strip()
    if not name:
        return False
    if item_type == "explore":
        has_structured_anchor = bool(item.location_ref and ((item.location_ref.name or "").strip() or (item.location_ref.category or "").strip()))
        if not has_structured_anchor and _GENERIC_EXPLORE_PATTERN.search(name):
            return False
    return True


def _run_image_curator(
    plan: PlanningResult,
    request: PlanningRequest,
    *,
    llm_config: LlmConfig | None,
    visual_items: list[PlannedItem],
) -> tuple[AgentRunStep, dict[str, ImageCuratorSelection]]:
    if not visual_items:
        return (
            AgentRunStep(
                key="image_curator",
                title="Image curator",
                description="Ranks which itinerary items deserve visual coverage.",
                prompt_focus="No visual itinerary items were available for curation.",
                output_summary="No image candidates found in the itinerary.",
                prompt_version=IMAGE_CURATOR_PROMPT_VERSION,
                status="completed",
                model=llm_config.config_for_role("image_curator").model if llm_config is not None else None,
                notes=["No itinerary items qualified for image curation."],
                citations=[],
            ),
            {},
        )

    if llm_config is None:
        selections = _fallback_curator_selections(visual_items)
        return _build_curator_run(None, selections, status="failed", extra_notes=["Curator LLM config unavailable; used fallback prioritization."]), selections

    prompt = build_image_curator_prompt()
    curator_config = llm_config.config_for_role("image_curator")
    payload = {
        "trip": {
            "title": request.title,
            "destination": request.destination,
            "origin": request.origin,
            "interests": list(request.interests),
            "budget": request.budget,
            "travelers": request.travelers,
            "pace": request.pace,
            "transport_mode": request.transport_mode,
        },
        "days": [
            {
                "day_index": day.day_index,
                "title": day.title,
                "summary": day.summary,
                "items": [
                    {
                        "item_id": item.id,
                        "name": item.name,
                        "type": item.type,
                        "location": item.location,
                        "note": item.note,
                        "score": item.score,
                        "category": item.location_ref.category if item.location_ref is not None else None,
                        "location_summary": item.location_ref.summary if item.location_ref is not None else None,
                    }
                    for item in day.items
                    if _is_visual_candidate(item)
                ],
            }
            for day in plan.days
        ],
    }

    messages = [
        {"role": "system", "content": prompt.system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        raw = OpenAICompatibleClient(curator_config).create_chat_completion(messages=messages, temperature=0.2)
        parsed = ImageCuratorResponse.model_validate(_load_json_object(raw))
        selections = _normalize_curator_selections(parsed.items, visual_items)
        return _build_curator_run(curator_config.model, selections, status="completed"), selections
    except Exception as exc:
        selections = _fallback_curator_selections(visual_items)
        note = f"Curator parsing failed: {str(exc).strip() or exc.__class__.__name__}."
        return _build_curator_run(curator_config.model, selections, status="failed", extra_notes=[note, "Used fallback prioritization."]), selections


def _normalize_curator_selections(
    items: list[ImageCuratorSelection],
    visual_items: list[PlannedItem],
) -> dict[str, ImageCuratorSelection]:
    by_id = {selection.item_id: selection for selection in items if selection.item_id}
    normalized: dict[str, ImageCuratorSelection] = {}
    for item in visual_items:
        selection = by_id.get(item.id)
        if selection is None:
            selection = ImageCuratorSelection(
                item_id=item.id,
                priority_tier="low",
                reason="Visual stop without an explicit curator decision; assigned a conservative fallback.",
                suggested_image_count=1,
            )
        count_cap = _TIER_IMAGE_COUNTS[selection.priority_tier]
        normalized[item.id] = ImageCuratorSelection(
            item_id=item.id,
            priority_tier=selection.priority_tier,
            reason=selection.reason,
            suggested_image_count=min(selection.suggested_image_count or count_cap, count_cap),
        )
    return normalized


def _fallback_curator_selections(visual_items: list[PlannedItem]) -> dict[str, ImageCuratorSelection]:
    selections: dict[str, ImageCuratorSelection] = {}
    for index, item in enumerate(visual_items):
        tier = "high" if index == 0 else "medium" if index < 3 else "low"
        selections[item.id] = ImageCuratorSelection(
            item_id=item.id,
            priority_tier=tier,
            reason="Fallback visual prioritization favored the most prominent scenic stops.",
            suggested_image_count=_TIER_IMAGE_COUNTS[tier],
        )
    return selections


def _build_curator_run(
    model: str | None,
    selections: dict[str, ImageCuratorSelection],
    *,
    status: str,
    extra_notes: list[str] | None = None,
) -> AgentRunStep:
    counts = {tier: 0 for tier in _TIER_IMAGE_COUNTS}
    for selection in selections.values():
        counts[selection.priority_tier] += 1
    highlighted = [
        f"{selection.item_id}: {selection.reason}"
        for selection in selections.values()
        if selection.priority_tier == "high" and selection.reason
    ][:3]
    notes = [
        f"Priority split: high={counts['high']}, medium={counts['medium']}, low={counts['low']}, skipped={counts['skipped']}.",
        *highlighted,
    ]
    if extra_notes:
        notes.extend(extra_notes)
    return AgentRunStep(
        key="image_curator",
        title="Image curator",
        description="Ranks which itinerary items deserve visual coverage.",
        prompt_focus="Judge landmark value, visual distinctiveness, interest fit, and hero-image potential using itinerary text only.",
        output_summary=f"Curated {len(selections)} visual items across high/medium/low/skipped tiers.",
        prompt_version=IMAGE_CURATOR_PROMPT_VERSION,
        status=status,
        model=model,
        notes=notes,
        citations=[],
    )


def _run_direct_tavily_image_specialist(
    request: PlanningRequest,
    *,
    search_service: SearchServiceConfig | None,
    visual_items: list[PlannedItem],
) -> AgentRunStep:
    if not visual_items:
        return AgentRunStep(
            key="attraction_image_specialist",
            title="Attraction image specialist",
            description="Searches and attaches source images for pending itinerary items.",
            prompt_focus="No pending scenic items were available.",
            output_summary="No image search was necessary.",
            prompt_version="tavily.direct_image_enrichment.v1",
            status="completed",
            model=None,
            notes=["No itinerary items required image search."],
            citations=[],
        )

    resolved_search_service = _resolve_tavily_image_search_config(search_service)
    if resolved_search_service is None:
        for item in visual_items:
            item.image_status = "failed"
            item.image_failure_reason = "Tavily image search is not configured."
        return AgentRunStep(
            key="attraction_image_specialist",
            title="Attraction image specialist",
            description="Searches and attaches source images for pending itinerary items.",
            prompt_focus="Use Tavily only; do not fall back to GrokSearch or other providers.",
            output_summary="Image enrichment was skipped because Tavily was not configured.",
            prompt_version="tavily.direct_image_enrichment.v1",
            status="failed",
            model=None,
            notes=["Tavily is required for image enrichment and was not available."],
            citations=[],
        )

    gateway = ConfiguredSearchGateway(resolved_search_service)
    try:
        available_tools = gateway.available_tools()
    except Exception as exc:
        for item in visual_items:
            item.image_status = "failed"
            item.image_failure_reason = "Tavily tool discovery failed."
        return AgentRunStep(
            key="attraction_image_specialist",
            title="Attraction image specialist",
            description="Searches and attaches source images for pending itinerary items.",
            prompt_focus="Use Tavily only; do not fall back to GrokSearch or other providers.",
            output_summary="Image enrichment could not start because Tavily tool discovery failed.",
            prompt_version="tavily.direct_image_enrichment.v1",
            status="failed",
            model=None,
            notes=[f"Tavily tool discovery failed: {str(exc).strip() or exc.__class__.__name__}."],
            citations=[],
        )
    if "search" not in available_tools:
        for item in visual_items:
            item.image_status = "failed"
            item.image_failure_reason = "Tavily search tool is unavailable."
        return AgentRunStep(
            key="attraction_image_specialist",
            title="Attraction image specialist",
            description="Searches and attaches source images for pending itinerary items.",
            prompt_focus="Use Tavily only; do not fall back to GrokSearch or other providers.",
            output_summary="Image enrichment was skipped because the Tavily search tool was unavailable.",
            prompt_version="tavily.direct_image_enrichment.v1",
            status="failed",
            model=None,
            notes=[f"Available tools: {', '.join(sorted(available_tools)) or 'none'}."],
            citations=[],
        )

    search_targets = [item for item in visual_items if item.image_status == "pending"]
    outcomes: list[ImageSearchOutcome] = []
    if search_targets:
        with ThreadPoolExecutor(
            max_workers=min(_DIRECT_IMAGE_MAX_WORKERS, len(search_targets)),
            thread_name_prefix="trip-image-direct",
        ) as executor:
            futures = [
                executor.submit(_search_item_images_direct, resolved_search_service, request, item)
                for item in search_targets
            ]
            outcomes.extend(future.result() for future in futures)

    all_citations: list[str] = []
    completed = 0
    failed = 0
    total_raw_candidates = 0
    total_selected = 0
    candidate_debug_notes: list[str] = []
    outcomes_by_id = {outcome.item_id: outcome for outcome in outcomes}
    for item in search_targets:
        outcome = outcomes_by_id.get(item.id)
        if outcome is None:
            item.image_status = "failed"
            item.image_failure_reason = "Image search did not return an outcome."
            failed += 1
            continue
        item.image_urls = list(outcome.image_urls)
        item.image_source_urls = list(outcome.source_urls[: max(1, min(len(outcome.source_urls), len(outcome.image_urls) or 1))])
        item.image_status = outcome.status
        item.image_failure_reason = outcome.failure_reason if outcome.status == "failed" else None
        all_citations.extend(outcome.source_urls)
        total_raw_candidates += outcome.candidate_count_raw
        total_selected += outcome.candidate_count_after_review
        candidate_debug_notes.extend(_build_candidate_debug_notes(item, outcome))
        if outcome.image_urls:
            completed += 1
        else:
            failed += 1

    endpoint = urlparse(resolved_search_service.base_url).netloc or resolved_search_service.base_url
    domains = resolved_search_service.image_include_domains
    query_previews = [
        f"Image query [{_best_item_name(item)}]: {_direct_image_query_for_item(item, request)}"
        for item in search_targets[:5]
    ]
    return AgentRunStep(
        key="attraction_image_specialist",
        title="Attraction image specialist",
        description="Searches and attaches source images for pending itinerary items.",
        prompt_focus="Directly search Tavily for pending scenic items, then write selected images back to each item before display.",
        output_summary=f"Attached images for {completed} pending items; {failed} pending items remained without usable images.",
        prompt_version="tavily.direct_image_enrichment.v1",
        status="completed" if failed == 0 else "partial",
        model=None,
        notes=[
            "Provider: tavily.",
            f"Third-party endpoint: {endpoint}.",
            "Wire API: api.",
            "Search tool: search.",
            "Image mode: include_images + include_image_descriptions.",
            f"Image source domains: {', '.join(domains) or 'default Tavily'}.",
            f"Execution strategy: direct pending items parallel (max {_DIRECT_IMAGE_MAX_WORKERS} workers); curator and reviewer skipped.",
            f"Per-item image cap: {_DIRECT_IMAGE_COUNT_PER_ITEM}.",
            *query_previews,
            f"Candidate counts: raw={total_raw_candidates}, selected={total_selected}.",
            *candidate_debug_notes[:12],
        ],
        citations=_dedupe(all_citations),
    )


def _run_image_specialist(
    plan: PlanningResult,
    request: PlanningRequest,
    *,
    llm_config: LlmConfig | None,
    search_service: SearchServiceConfig | None,
    selections: dict[str, ImageCuratorSelection],
    visual_items: list[PlannedItem],
) -> tuple[AgentRunStep, AgentRunStep]:
    if not visual_items:
        specialist_run = AgentRunStep(
            key="attraction_image_specialist",
            title="Attraction image specialist",
            description="Searches and attaches source images for prioritized itinerary items.",
            prompt_focus="No prioritized scenic items were available.",
            output_summary="No image search was necessary.",
            prompt_version="tavily.image_specialist.v1",
            status="completed",
            model=None,
            notes=["No itinerary items required image search."],
            citations=[],
        )
        reviewer_run = AgentRunStep(
            key="image_reviewer",
            title="Image reviewer",
            description="Reviews candidate attraction images and rejects low-confidence visuals.",
            prompt_focus="No candidate images were available for multimodal review.",
            output_summary="No image review was necessary.",
            prompt_version=IMAGE_REVIEWER_PROMPT_VERSION,
            status="completed",
            model=llm_config.config_for_role("image_reviewer").model if llm_config is not None else None,
            notes=["No candidate images reached the image reviewer."],
            citations=[],
        )
        return specialist_run, reviewer_run

    resolved_search_service = _resolve_tavily_image_search_config(search_service)
    if resolved_search_service is None:
        for item in visual_items:
            selection = selections.get(item.id)
            if selection is not None:
                item.image_priority_tier = selection.priority_tier
                item.image_priority_reason = selection.reason or None
                item.image_status = "failed" if selection.priority_tier != "skipped" else "skipped"
                item.image_failure_reason = "Tavily image search is not configured." if selection.priority_tier != "skipped" else None
        specialist_run = AgentRunStep(
            key="attraction_image_specialist",
            title="Attraction image specialist",
            description="Searches and attaches source images for prioritized itinerary items.",
            prompt_focus="Use Tavily only; do not fall back to GrokSearch or other providers.",
            output_summary="Image enrichment was skipped because Tavily was not configured.",
            prompt_version="tavily.image_specialist.v1",
            status="failed",
            model=None,
            notes=["Tavily is required for image enrichment and was not available."],
            citations=[],
        )
        reviewer_run = AgentRunStep(
            key="image_reviewer",
            title="Image reviewer",
            description="Reviews candidate attraction images and rejects low-confidence visuals.",
            prompt_focus="No candidate images were available because Tavily image search was not configured.",
            output_summary="The reviewer did not run because no candidate images were available.",
            prompt_version=IMAGE_REVIEWER_PROMPT_VERSION,
            status="completed",
            model=llm_config.config_for_role("image_reviewer").model if llm_config is not None else None,
            notes=["Image review skipped because Tavily image search was not configured."],
            citations=[],
        )
        return specialist_run, reviewer_run

    gateway = ConfiguredSearchGateway(resolved_search_service)
    try:
        available_tools = gateway.available_tools()
    except Exception as exc:
        specialist_run = AgentRunStep(
            key="attraction_image_specialist",
            title="Attraction image specialist",
            description="Searches and attaches source images for prioritized itinerary items.",
            prompt_focus="Use Tavily only; do not fall back to GrokSearch or other providers.",
            output_summary="Image enrichment could not start because Tavily tool discovery failed.",
            prompt_version="tavily.image_specialist.v1",
            status="failed",
            model=None,
            notes=[f"Tavily tool discovery failed: {str(exc).strip() or exc.__class__.__name__}."],
            citations=[],
        )
        reviewer_run = AgentRunStep(
            key="image_reviewer",
            title="Image reviewer",
            description="Reviews candidate attraction images and rejects low-confidence visuals.",
            prompt_focus="No candidate images were available because Tavily tool discovery failed.",
            output_summary="The reviewer did not run because Tavily did not yield candidate images.",
            prompt_version=IMAGE_REVIEWER_PROMPT_VERSION,
            status="completed",
            model=llm_config.config_for_role("image_reviewer").model if llm_config is not None else None,
            notes=["Image review skipped because Tavily tool discovery failed."],
            citations=[],
        )
        return specialist_run, reviewer_run
    if "search" not in available_tools:
        specialist_run = AgentRunStep(
            key="attraction_image_specialist",
            title="Attraction image specialist",
            description="Searches and attaches source images for prioritized itinerary items.",
            prompt_focus="Use Tavily only; do not fall back to GrokSearch or other providers.",
            output_summary="Image enrichment was skipped because the Tavily search tool was unavailable.",
            prompt_version="tavily.image_specialist.v1",
            status="failed",
            model=None,
            notes=[f"Available tools: {', '.join(sorted(available_tools)) or 'none'}."],
            citations=[],
        )
        reviewer_run = AgentRunStep(
            key="image_reviewer",
            title="Image reviewer",
            description="Reviews candidate attraction images and rejects low-confidence visuals.",
            prompt_focus="No candidate images were available because the Tavily search tool was unavailable.",
            output_summary="The reviewer did not run because no candidate images were available.",
            prompt_version=IMAGE_REVIEWER_PROMPT_VERSION,
            status="completed",
            model=llm_config.config_for_role("image_reviewer").model if llm_config is not None else None,
            notes=["Image review skipped because the Tavily search tool was unavailable."],
            citations=[],
        )
        return specialist_run, reviewer_run

    all_citations: list[str] = []
    completed = 0
    failed = 0
    total_raw_candidates = 0
    total_rule_candidates = 0
    total_review_selected = 0
    reviewer_modes: dict[str, int] = {}
    reviewer_summaries: list[str] = []
    reviewer_rejections: list[str] = []
    candidate_debug_notes: list[str] = []
    prioritized_items: list[tuple[PlannedItem, ImageCuratorSelection]] = []
    for day in plan.days:
        for item in day.items:
            selection = selections.get(item.id)
            if selection is None:
                continue
            item.image_priority_tier = selection.priority_tier
            item.image_priority_reason = selection.reason or None
            if selection.priority_tier == "skipped" or selection.suggested_image_count <= 0:
                item.image_status = "skipped"
                item.image_failure_reason = None
                continue
            prioritized_items.append((item, selection))

    high_priority_items = [(item, selection) for item, selection in prioritized_items if selection.priority_tier == "high"]
    serial_priority_items = [(item, selection) for item, selection in prioritized_items if selection.priority_tier != "high"]
    query_previews = [
        f"Image query [{_best_item_name(item)}]: {_build_image_query(item, request)}"
        for item, _ in prioritized_items[:5]
    ]

    outcomes: list[ImageSearchOutcome] = []
    if high_priority_items:
        with ThreadPoolExecutor(
            max_workers=min(_HIGH_PRIORITY_IMAGE_MAX_WORKERS, len(high_priority_items)),
            thread_name_prefix="trip-image-high",
        ) as executor:
            futures = [
                executor.submit(_search_item_images, resolved_search_service, request, item, selection, llm_config)
                for item, selection in high_priority_items
            ]
            outcomes.extend(future.result() for future in futures)

    for item, selection in serial_priority_items:
        outcomes.append(_search_item_images(resolved_search_service, request, item, selection, llm_config))

    outcomes_by_id = {outcome.item_id: outcome for outcome in outcomes}
    for item, selection in prioritized_items:
        outcome = outcomes_by_id.get(item.id)
        if outcome is None:
            item.image_status = "failed"
            item.image_failure_reason = "Image search did not return an outcome."
            failed += 1
            continue
        item.image_urls = list(outcome.image_urls)
        item.image_source_urls = list(outcome.source_urls[: max(1, min(len(outcome.source_urls), len(outcome.image_urls) or 1))])
        item.image_status = outcome.status
        item.image_failure_reason = outcome.failure_reason if outcome.status == "failed" else None
        all_citations.extend(outcome.source_urls)
        total_raw_candidates += outcome.candidate_count_raw
        total_rule_candidates += outcome.candidate_count_after_rules
        total_review_selected += outcome.candidate_count_after_review
        reviewer_modes[outcome.review_mode] = reviewer_modes.get(outcome.review_mode, 0) + 1
        if outcome.review_summary:
            reviewer_summaries.append(f"{_best_item_name(item)}: {outcome.review_summary}")
        reviewer_rejections.extend(outcome.review_rejection_reasons)
        candidate_debug_notes.extend(_build_candidate_debug_notes(item, outcome))
        if outcome.image_urls:
            completed += 1
        else:
            failed += 1

    endpoint = urlparse(resolved_search_service.base_url).netloc or resolved_search_service.base_url
    specialist_run = AgentRunStep(
        key="attraction_image_specialist",
        title="Attraction image specialist",
        description="Searches and attaches source images for prioritized itinerary items.",
        prompt_focus="Use Tavily image search results to attach sourced visual references for prioritized itinerary items.",
        output_summary=f"Attached images for {completed} prioritized items; {failed} prioritized items remained without usable images.",
        prompt_version="tavily.image_specialist.v1",
        status="completed" if failed == 0 else "partial",
        model=None,
        notes=[
            f"Provider: tavily.",
            f"Third-party endpoint: {endpoint}.",
            "Wire API: api.",
            "Search tool: search.",
            "Image mode: include_images + include_image_descriptions.",
            f"Execution strategy: high tier parallel (max {_HIGH_PRIORITY_IMAGE_MAX_WORKERS} workers); medium and low tiers serial.",
            *query_previews,
            f"Candidate counts: raw={total_raw_candidates}, after_rules={total_rule_candidates}, after_review={total_review_selected}.",
            *candidate_debug_notes[:12],
        ],
        citations=_dedupe(all_citations),
    )
    reviewer_run = AgentRunStep(
        key="image_reviewer",
        title="Image reviewer",
        description="Reviews candidate attraction images and rejects low-confidence visuals.",
        prompt_focus="Review a small set of filtered candidate images and keep only high-confidence attraction visuals.",
        output_summary=(
            f"Reviewed {total_rule_candidates} filtered candidates across {len(prioritized_items)} prioritized items and kept {total_review_selected} high-confidence images."
            if total_rule_candidates > 0
            else "No candidate images reached the image reviewer after rule filtering."
        ),
        prompt_version=IMAGE_REVIEWER_PROMPT_VERSION,
        status="completed",
        model=llm_config.config_for_role("image_reviewer").model if llm_config is not None else None,
        notes=[
            f"Review modes: {', '.join(f'{mode}={count}' for mode, count in sorted(reviewer_modes.items())) or 'none'}.",
            *reviewer_summaries[:6],
            *reviewer_rejections[:6],
        ],
        citations=[],
    )
    return specialist_run, reviewer_run


def _resolve_tavily_image_search_config(search_service: SearchServiceConfig | None) -> SearchServiceConfig | None:
    if search_service is not None and str(search_service.provider).strip().lower() == "tavily":
        return search_service

    tavily_api_key = str(get_env("TRAVELMIND_TAVILY_API_KEY") or get_env("TAVILY_API_KEY") or "").strip()
    if not tavily_api_key:
        return None
    tavily_base_url = str(get_env("TRAVELMIND_TAVILY_BASE_URL") or get_env("TAVILY_API_URL") or "https://api.tavily.com/search").strip()
    tavily_timeout_raw = str(get_env("TRAVELMIND_TAVILY_TIMEOUT_SECONDS") or "30").strip()
    try:
        tavily_timeout = float(tavily_timeout_raw)
    except ValueError:
        tavily_timeout = 30.0
    return SearchServiceConfig(
        provider="tavily",
        transport="api",
        base_url=tavily_base_url.rstrip("/"),
        api_key=tavily_api_key,
        timeout_seconds=tavily_timeout,
    )


def _direct_image_query_for_item(item: PlannedItem, request: PlanningRequest) -> str:
    query_plan = _build_fallback_image_query_plan(item, request)
    return query_plan.search_queries[0] if query_plan.search_queries else _build_image_query(item, request)


def _search_item_images_direct(
    search_service: SearchServiceConfig,
    request: PlanningRequest,
    item: PlannedItem,
) -> ImageSearchOutcome:
    gateway = ConfiguredSearchGateway(search_service)
    query = _direct_image_query_for_item(item, request)
    try:
        search_payload = gateway.call_operation(
            "search",
            {
                "query": query,
                "num_results": _DIRECT_IMAGE_SEARCH_RESULT_COUNT,
                "include_images": True,
                "include_image_descriptions": True,
            },
        )
        candidates = _extract_tavily_image_candidates(search_payload)
        selected_candidates = [candidate for candidate in candidates if candidate.url][:_DIRECT_IMAGE_COUNT_PER_ITEM]
        image_urls = _dedupe([candidate.url for candidate in selected_candidates])
        source_urls = _dedupe([candidate.source_url for candidate in selected_candidates if candidate.source_url])
        if not image_urls:
            return ImageSearchOutcome(
                item_id=item.id,
                image_urls=[],
                source_urls=[],
                status="failed",
                failure_reason=f"Tavily returned no image candidates for query: {query}",
                candidate_count_raw=len(candidates),
                candidate_count_after_rules=len(candidates),
                candidate_count_after_review=0,
                review_mode="direct_tavily",
                review_summary="Direct Tavily selection found no usable image candidates.",
                debug_query=query,
                debug_candidates_raw=[_serialize_tavily_candidate(candidate) for candidate in candidates[:8]],
                debug_candidates_after_rules=[_serialize_tavily_candidate(candidate) for candidate in candidates[:8]],
                debug_candidates_after_review=[],
            )
        return ImageSearchOutcome(
            item_id=item.id,
            image_urls=image_urls,
            source_urls=source_urls,
            status="completed",
            failure_reason=None,
            candidate_count_raw=len(candidates),
            candidate_count_after_rules=len(candidates),
            candidate_count_after_review=len(selected_candidates),
            review_mode="direct_tavily",
            review_summary="Direct Tavily candidate selection; curator and reviewer skipped.",
            debug_query=query,
            debug_candidates_raw=[_serialize_tavily_candidate(candidate) for candidate in candidates[:8]],
            debug_candidates_after_rules=[_serialize_tavily_candidate(candidate) for candidate in candidates[:8]],
            debug_candidates_after_review=[_serialize_tavily_candidate(candidate) for candidate in selected_candidates],
        )
    except Exception as exc:
        return ImageSearchOutcome(
            item_id=item.id,
            image_urls=[],
            source_urls=[],
            status="failed",
            failure_reason=f"Image search failed for query '{query}': {str(exc).strip() or exc.__class__.__name__}",
            review_mode="search_failed",
            debug_query=query,
        )


def _search_item_images(
    search_service: SearchServiceConfig,
    request: PlanningRequest,
    item: PlannedItem,
    selection: ImageCuratorSelection,
    llm_config: LlmConfig | None = None,
) -> ImageSearchOutcome:
    gateway = ConfiguredSearchGateway(search_service)
    query_plan = _plan_image_queries(item=item, request=request, selection=selection, llm_config=llm_config)
    queries = query_plan.search_queries[:3] or [_build_image_query(item, request)]
    all_candidates: list[TavilyImageCandidate] = []
    best_reviewed_candidates: list[TavilyImageCandidate] = []
    best_source_urls: list[str] = []
    best_failure_reason: str | None = None
    best_review_mode = "rules_only"
    best_review_summary: str | None = None
    best_review_rejections: list[str] = []
    best_filtered_candidates: list[TavilyImageCandidate] = []
    successful_query = queries[0]
    try:
        for query in queries:
            search_payload = gateway.call_operation(
                "search",
                {
                    "query": query,
                    "num_results": max(6, selection.suggested_image_count * 3),
                    "include_images": True,
                    "include_image_descriptions": True,
                },
            )
            image_candidates = _extract_tavily_image_candidates(search_payload)
            all_candidates.extend(image_candidates)
            ranked_candidates = _rank_tavily_image_candidates(image_candidates, item, request)
            filtered_candidates = ranked_candidates[: max(_MAX_REVIEW_CANDIDATES, selection.suggested_image_count)]
            reviewed_candidates, review_mode, review_summary, review_rejection_reasons = _review_image_candidates(
                item=item,
                request=request,
                selection=selection,
                candidates=filtered_candidates,
                llm_config=llm_config,
            )
            image_urls = _dedupe([candidate.url for candidate in reviewed_candidates if candidate.url])[: selection.suggested_image_count]
            source_urls = _dedupe([candidate.source_url for candidate in reviewed_candidates if candidate.source_url])
            if image_urls:
                best_reviewed_candidates = reviewed_candidates
                best_source_urls = source_urls
                best_review_mode = review_mode
                best_review_summary = review_summary
                best_review_rejections = review_rejection_reasons
                best_filtered_candidates = filtered_candidates
                successful_query = query
                break
            if not best_filtered_candidates and filtered_candidates:
                best_filtered_candidates = filtered_candidates
                best_review_mode = review_mode
                best_review_summary = review_summary
                best_review_rejections = review_rejection_reasons
                best_failure_reason = (
                    f"Tavily returned {len(image_candidates)} image candidates, but none passed multimodal review for query: {query}"
                    if review_mode == "multimodal"
                    else f"Tavily returned {len(image_candidates)} image candidates, but none passed the relevance and page-chrome filters for query: {query}"
                )
                successful_query = query

        image_urls = _dedupe([candidate.url for candidate in best_reviewed_candidates if candidate.url])[: selection.suggested_image_count]
        source_urls = best_source_urls
        raw_count = len(all_candidates)
        failure_reason = None
        if not image_urls:
            failure_reason = best_failure_reason or (
                f"Tavily returned no closely related image candidates for queries: {' | '.join(queries)}"
                if not all_candidates
                else f"Tavily returned {len(all_candidates)} image candidates across queries, but none passed the current filters."
            )
        return ImageSearchOutcome(
            item_id=item.id,
            image_urls=image_urls,
            source_urls=source_urls,
            status="completed" if image_urls else "failed",
            failure_reason=failure_reason,
            candidate_count_raw=raw_count,
            candidate_count_after_rules=len(best_filtered_candidates),
            candidate_count_after_review=len(best_reviewed_candidates),
            review_mode=best_review_mode,
            review_summary=best_review_summary,
            review_rejection_reasons=best_review_rejections,
            debug_query=successful_query,
            debug_candidates_raw=[_serialize_tavily_candidate(candidate) for candidate in all_candidates[:8]],
            debug_candidates_after_rules=[_serialize_tavily_candidate(candidate) for candidate in best_filtered_candidates],
            debug_candidates_after_review=[_serialize_tavily_candidate(candidate) for candidate in best_reviewed_candidates],
        )
    except Exception as exc:
        return ImageSearchOutcome(
            item_id=item.id,
            image_urls=[],
            source_urls=[],
            status="failed",
            failure_reason=f"Image search failed for queries '{' | '.join(queries)}': {str(exc).strip() or exc.__class__.__name__}",
            review_mode="search_failed",
            debug_query=" | ".join(queries),
        )


def _review_image_candidates(
    *,
    item: PlannedItem,
    request: PlanningRequest,
    selection: ImageCuratorSelection,
    candidates: list[TavilyImageCandidate],
    llm_config: LlmConfig | None,
) -> tuple[list[TavilyImageCandidate], str, str | None, list[str]]:
    if not candidates:
        return [], "rules_only", "No candidate images remained after rule filtering.", []
    if llm_config is None:
        return (
            candidates[: selection.suggested_image_count],
            "rules_only",
            "No LLM config available for multimodal review; used rule-ranked candidates.",
            [],
        )

    reviewer_config = llm_config.config_for_role("image_reviewer")
    prompt = build_image_reviewer_prompt()
    candidate_ids = {f"c{index + 1}": candidate for index, candidate in enumerate(candidates)}
    messages = _build_image_reviewer_messages(
        item=item,
        request=request,
        selection=selection,
        prompt=prompt.system_prompt,
        candidate_ids=candidate_ids,
    )
    try:
        raw = OpenAICompatibleClient(reviewer_config).create_chat_completion(messages=messages, temperature=0.1, max_tokens=1800)
        parsed = ImageReviewerResponse.model_validate(_load_json_object(raw))
    except Exception as exc:
        return (
            candidates[: selection.suggested_image_count],
            "rules_only",
            f"Multimodal review unavailable; used rule-ranked candidates. Reason: {str(exc).strip() or exc.__class__.__name__}.",
            [],
        )

    selected_ids = [entry.candidate_id for entry in parsed.selected_candidates if entry.candidate_id in candidate_ids]
    selected_candidates = [candidate_ids[candidate_id] for candidate_id in selected_ids][: selection.suggested_image_count]
    rejection_notes = [
        f"Rejected {entry.candidate_id}: {entry.reason}"
        for entry in parsed.rejected_candidates
        if entry.candidate_id in candidate_ids and entry.reason
    ]
    review_summary = parsed.summary.strip() or (
        "Multimodal review accepted high-confidence attraction images only."
        if selected_candidates
        else "Multimodal review rejected all candidates as low-confidence or off-topic."
    )
    return selected_candidates, "multimodal", review_summary, rejection_notes


def _build_image_reviewer_messages(
    *,
    item: PlannedItem,
    request: PlanningRequest,
    selection: ImageCuratorSelection,
    prompt: str,
    candidate_ids: dict[str, TavilyImageCandidate],
) -> list[dict[str, Any]]:
    primary_name = _best_item_name(item)
    category = str(item.location_ref.category if item.location_ref is not None else item.type or "").strip()
    location_summary = str(item.location_ref.summary if item.location_ref is not None else "").strip()
    address = str(item.location_ref.address if item.location_ref is not None else item.location or "").strip()
    user_blocks: list[dict[str, Any]] = [
        {"type": "input_text", "text": json.dumps(
            {
                "task": "Review candidate attraction images and keep only high-confidence matches.",
                "attraction": {
                    "name": primary_name,
                    "raw_item_name": item.name,
                    "destination": request.destination,
                    "location": item.location,
                    "address": address,
                    "category": category,
                    "summary": location_summary,
                    "priority_tier": selection.priority_tier,
                    "desired_image_count": selection.suggested_image_count,
                },
                "rules": {
                    "reject_examples": [
                        "site logos",
                        "banners",
                        "UI decorations",
                        "generic skyline covers",
                        "event posters",
                        "ads",
                        "QR codes",
                    ]
                },
            },
            ensure_ascii=False,
        )},
    ]
    for candidate_id, candidate in candidate_ids.items():
        user_blocks.append(
            {
                "type": "input_text",
                "text": json.dumps(
                    {
                        "candidate_id": candidate_id,
                        "source_title": candidate.source_title,
                        "source_url": candidate.source_url,
                        "source_snippet": candidate.source_snippet,
                        "image_description": candidate.image_description,
                        "origin": candidate.origin,
                    },
                    ensure_ascii=False,
                ),
            }
        )
        user_blocks.append({"type": "input_image", "image_url": candidate.url})
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_blocks},
    ]


def _build_image_query(item: PlannedItem, request: PlanningRequest) -> str:
    primary_name = _best_item_name(item)
    category = str(item.location_ref.category if item.location_ref is not None else item.type or "").strip()
    address = str(item.location_ref.address if item.location_ref is not None else "").strip()
    city = str(item.location_ref.city if item.location_ref is not None else "").strip()
    location_text = str(item.location or "").strip()
    destination = str(request.destination or "").strip()
    summary = str(item.location_ref.summary if item.location_ref is not None else "").strip()
    locale_hint = str(request.locale or "").strip().lower()
    zh_output = locale_hint.startswith("zh") or bool(_CJK_TOKEN_PATTERN.search(primary_name + destination + location_text))

    parts = [
        f"\"{primary_name}\"" if primary_name else "",
        destination,
        city,
        address,
        location_text,
        category,
        summary,
    ]
    if zh_output:
        parts.extend(["景点", "官方", "旅游", "图片"])
    else:
        parts.extend(["landmark", "official", "travel", "photos"])
    normalized_parts = [_normalize_text(part) for part in parts if _normalize_text(part)]
    return " ".join(_dedupe_preserve_order(normalized_parts))


def _plan_image_queries(
    *,
    item: PlannedItem,
    request: PlanningRequest,
    selection: ImageCuratorSelection,
    llm_config: LlmConfig | None,
) -> ImageQueryPlan:
    fallback = _build_fallback_image_query_plan(item, request)
    if llm_config is None:
        return fallback

    planner_config = llm_config.config_for_role("image_query_planner")
    prompt = build_image_query_planner_prompt()
    payload = {
        "trip": {
            "destination": request.destination,
            "origin": request.origin,
            "interests": list(request.interests),
            "pace": request.pace,
        },
        "item": {
            "name": item.name,
            "type": item.type,
            "location": item.location,
            "note": item.note,
            "score": item.score,
            "priority_tier": selection.priority_tier,
            "location_ref": {
                "provider": item.location_ref.provider if item.location_ref is not None else None,
                "name": item.location_ref.name if item.location_ref is not None else None,
                "city": item.location_ref.city if item.location_ref is not None else None,
                "category": item.location_ref.category if item.location_ref is not None else None,
                "summary": item.location_ref.summary if item.location_ref is not None else None,
                "address": item.location_ref.address if item.location_ref is not None else None,
            },
        },
        "fallback": fallback.model_dump(mode="json"),
    }
    messages = [
        {"role": "system", "content": prompt.system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        raw = OpenAICompatibleClient(planner_config).create_chat_completion(messages=messages, temperature=0.1, max_tokens=1000)
        parsed = ImageQueryPlan.model_validate(_load_json_object(raw))
    except Exception:
        return fallback

    canonical_name = _normalize_text(parsed.canonical_name) or fallback.canonical_name
    aliases = _dedupe_preserve_order(
        [
            canonical_name,
            *[_normalize_text(alias) for alias in parsed.aliases if _normalize_text(alias)],
            *fallback.aliases,
        ]
    )
    search_queries = _dedupe_preserve_order(
        [
            *[_normalize_text(query) for query in parsed.search_queries if _normalize_text(query)],
            *fallback.search_queries,
        ]
    )[:3]
    return ImageQueryPlan(
        canonical_name=canonical_name,
        aliases=aliases,
        search_queries=search_queries,
        reason=_normalize_text(parsed.reason) or fallback.reason,
        mode="llm",
    )


def _build_fallback_image_query_plan(item: PlannedItem, request: PlanningRequest) -> ImageQueryPlan:
    canonical_name = _derive_canonical_item_name(item)
    aliases = _build_item_aliases(item, canonical_name)
    queries: list[str] = []
    for alias in aliases[:3]:
        alias_query = _build_search_query_from_subject(item, request, alias)
        if alias_query:
            queries.append(alias_query)
    return ImageQueryPlan(
        canonical_name=canonical_name,
        aliases=aliases,
        search_queries=_dedupe_preserve_order(queries),
        reason="Fallback query planner prefers the itinerary attraction name over generic map placeholders.",
        mode="fallback",
    )


def _build_search_query_from_subject(item: PlannedItem, request: PlanningRequest, subject: str) -> str:
    category = str(item.location_ref.category if item.location_ref is not None else item.type or "").strip()
    address = str(item.location_ref.address if item.location_ref is not None else "").strip()
    city = str(item.location_ref.city if item.location_ref is not None else "").strip()
    location_text = str(item.location or "").strip()
    destination = str(request.destination or "").strip()
    summary = str(item.location_ref.summary if item.location_ref is not None else "").strip()
    locale_hint = str(request.locale or "").strip().lower()
    normalized_subject = _normalize_text(subject)
    zh_output = locale_hint.startswith("zh") or bool(_CJK_TOKEN_PATTERN.search(normalized_subject + destination + location_text))
    parts = [
        f"\"{normalized_subject}\"" if normalized_subject else "",
        destination,
        city,
        address,
        location_text,
        category,
        summary,
    ]
    if zh_output:
        parts.extend(["景点", "官方", "旅游", "图片"])
    else:
        parts.extend(["landmark", "official", "travel", "photos"])
    normalized_parts = [_normalize_text(part) for part in parts if _normalize_text(part)]
    return " ".join(_dedupe_preserve_order(normalized_parts))


def _derive_canonical_item_name(item: PlannedItem) -> str:
    source_name = _normalize_text(str(item.name or ""))
    if not source_name:
        if _looks_like_real_location_ref_name(item):
            return _normalize_text(str(item.location_ref.name or ""))
        return ""
    cleaned = _normalize_text(_STRATEGY_SUFFIX_PATTERN.sub(" ", source_name))
    parts = [part for part in _SEPARATOR_PATTERN.split(cleaned) if _normalize_text(part)]
    cleaned_parts = [_normalize_text(_STRATEGY_SUFFIX_PATTERN.sub(" ", part)) for part in parts if _normalize_text(_STRATEGY_SUFFIX_PATTERN.sub(" ", part))]
    if cleaned_parts:
        for part in cleaned_parts:
            if _token_count(part) >= 2:
                return part
        return cleaned_parts[0]
    return cleaned or source_name


def _build_item_aliases(item: PlannedItem, canonical_name: str) -> list[str]:
    aliases = [canonical_name]
    raw_item_name = _normalize_text(str(item.name or ""))
    if raw_item_name and raw_item_name.casefold() != canonical_name.casefold():
        aliases.append(raw_item_name)
    if _looks_like_real_location_ref_name(item):
        ref_name = _normalize_text(str(item.location_ref.name or ""))
        if ref_name and ref_name.casefold() != canonical_name.casefold():
            aliases.append(ref_name)
    parts = [part for part in _SEPARATOR_PATTERN.split(raw_item_name) if _normalize_text(part)]
    aliases.extend(_normalize_text(part) for part in parts if _normalize_text(part))
    return _dedupe_preserve_order([alias for alias in aliases if alias])


def _serialize_tavily_candidate(candidate: TavilyImageCandidate) -> dict[str, Any]:
    return {
        "url": candidate.url,
        "source_url": candidate.source_url,
        "source_title": candidate.source_title,
        "source_snippet": candidate.source_snippet,
        "image_description": candidate.image_description,
        "origin": candidate.origin,
        "result_rank": candidate.result_rank,
        "image_index": candidate.image_index,
    }


def _build_candidate_debug_notes(item: PlannedItem, outcome: ImageSearchOutcome) -> list[str]:
    label = _best_item_name(item)
    notes = [f"Image debug [{label}] query: {outcome.debug_query or 'n/a'}"]
    for index, candidate in enumerate(outcome.debug_candidates_raw[:3], start=1):
        notes.append(
            f"Image debug [{label}] raw#{index}: title={candidate.get('source_title') or '-'} | origin={candidate.get('origin') or '-'} | image={candidate.get('url') or '-'} | source={candidate.get('source_url') or '-'}"
        )
    for index, candidate in enumerate(outcome.debug_candidates_after_rules[:2], start=1):
        notes.append(
            f"Image debug [{label}] after_rules#{index}: title={candidate.get('source_title') or '-'} | image={candidate.get('url') or '-'}"
        )
    for index, candidate in enumerate(outcome.debug_candidates_after_review[:2], start=1):
        notes.append(
            f"Image debug [{label}] after_review#{index}: title={candidate.get('source_title') or '-'} | image={candidate.get('url') or '-'}"
        )
    return notes


def _best_item_name(item: PlannedItem) -> str:
    if _looks_like_real_location_ref_name(item):
        return str(item.location_ref.name).strip()
    return _derive_canonical_item_name(item)


def _looks_like_real_location_ref_name(item: PlannedItem) -> bool:
    if item.location_ref is None:
        return False
    name = str(item.location_ref.name or "").strip()
    provider = str(item.location_ref.provider or "").strip().lower()
    summary = str(item.location_ref.summary or "").strip().lower()
    if not name:
        return False
    if "stub" in provider or "stub poi" in summary:
        return False
    return True


def _normalize_text(value: str) -> str:
    return _WHITESPACE_PATTERN.sub(" ", str(value or "").strip())


def _token_count(value: str) -> int:
    return len(_tokenize_for_match(value))


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        results.append(value)
    return results


def _fetch_source_payload(gateway: ConfiguredSearchGateway, fetch_tool: str, url: str) -> dict[str, Any]:
    if fetch_tool == "web_fetch":
        return gateway.call_operation(fetch_tool, {"url": url})
    return gateway.call_operation(fetch_tool, {"urls": [url], "include_text": True, "include_html": True})


def _extract_tavily_image_candidates(payload: dict[str, Any]) -> list[TavilyImageCandidate]:
    candidates: list[TavilyImageCandidate] = []

    results = payload.get("results")
    if isinstance(results, list):
        for result_rank, result in enumerate(results):
            if not isinstance(result, dict):
                continue
            source_url = str(result.get("url") or "").strip()
            source_title = str(result.get("title") or "").strip()
            source_snippet = str(
                result.get("content")
                or result.get("snippet")
                or result.get("summary")
                or result.get("description")
                or ""
            ).strip()
            result_images = result.get("images")
            if not isinstance(result_images, list):
                continue
            for image_index, image in enumerate(result_images):
                if isinstance(image, dict):
                    url = str(image.get("url") or "").strip()
                    image_description = str(image.get("description") or "").strip()
                else:
                    url = str(image or "").strip()
                    image_description = ""
                if url:
                    candidates.append(
                        TavilyImageCandidate(
                            url=url,
                            source_url=source_url,
                            source_title=source_title,
                            source_snippet=source_snippet,
                            image_description=image_description,
                            origin="result",
                            result_rank=result_rank,
                            image_index=image_index,
                        )
                    )

    top_level_images = payload.get("images")
    if isinstance(top_level_images, list):
        for image_index, image in enumerate(top_level_images):
            if isinstance(image, dict):
                url = str(image.get("url") or "").strip()
                image_description = str(image.get("description") or "").strip()
            else:
                url = str(image or "").strip()
                image_description = ""
            if url:
                candidates.append(
                    TavilyImageCandidate(
                        url=url,
                        source_url="",
                        source_title="",
                        source_snippet="",
                        image_description=image_description,
                        origin="top_level",
                        result_rank=999,
                        image_index=image_index,
                    )
                )

    deduped: list[TavilyImageCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.url.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _rank_tavily_image_candidates(
    candidates: list[TavilyImageCandidate],
    item: PlannedItem,
    request: PlanningRequest,
) -> list[TavilyImageCandidate]:
    scored: list[tuple[int, TavilyImageCandidate]] = []
    strong_match_found = False
    for candidate in candidates:
        score = _score_tavily_image_candidate(candidate, item, request)
        if score >= 90:
            strong_match_found = True
        if score <= 0:
            continue
        scored.append((score, candidate))

    if strong_match_found:
        scored = [(score, candidate) for score, candidate in scored if candidate.origin == "result" or score >= 90]

    scored.sort(
        key=lambda entry: (
            -entry[0],
            0 if entry[1].origin == "result" else 1,
            len(entry[1].source_title or entry[1].source_snippet or ""),
        )
    )
    return [candidate for _, candidate in scored]


def _score_tavily_image_candidate(candidate: TavilyImageCandidate, item: PlannedItem, request: PlanningRequest) -> int:
    source_text = " ".join(
        part
        for part in [
            candidate.source_title,
            candidate.source_snippet,
            candidate.image_description,
            candidate.source_url,
            candidate.url,
        ]
        if part
    )
    normalized_source = _normalize_text(source_text).casefold()
    primary_name = _normalize_text(_best_item_name(item))
    destination = _normalize_text(str(request.destination or ""))
    category = _normalize_text(str(item.location_ref.category if item.location_ref is not None else item.type or ""))
    aliases = _dedupe_preserve_order(
        [
            primary_name,
            _normalize_text(str(item.name or "")),
            _normalize_text(str(item.location_ref.name if item.location_ref is not None else "")),
        ]
    )
    score = 0
    if candidate.origin == "result":
        score += 20
    else:
        score -= 10
    if candidate.origin == "result":
        score += max(0, 12 - (candidate.result_rank * 3))
        score += min(candidate.image_index, 4) * 4

    for alias in aliases:
        if not alias:
            continue
        alias_lower = alias.casefold()
        if alias_lower and alias_lower in normalized_source:
            score += 90 if alias == primary_name else 55

    if destination and destination.casefold() in normalized_source:
        score += 20
    if category and category.casefold() in normalized_source:
        score += 10

    if _looks_like_official_or_travel_source(candidate.source_url):
        score += 18

    source_tokens = set(_tokenize_for_match(normalized_source))
    for alias in aliases:
        alias_tokens = [token for token in _tokenize_for_match(alias) if token]
        if not alias_tokens:
            continue
        overlap = sum(1 for token in alias_tokens if token in source_tokens)
        score += overlap * 12

    if not candidate.source_url and not candidate.image_description:
        score -= 25
    if _looks_like_page_chrome_image(candidate):
        score -= 140 if candidate.image_index <= 1 else 100
    if _looks_like_generic_page_asset(candidate):
        score -= 50
    if candidate.origin == "top_level" and not candidate.source_url:
        score -= 15

    return score


def _tokenize_for_match(value: str) -> list[str]:
    normalized = _normalize_text(value).casefold()
    return _ENGLISH_TOKEN_PATTERN.findall(normalized) + _CJK_TOKEN_PATTERN.findall(normalized)


def _looks_like_official_or_travel_source(url: str) -> bool:
    normalized = str(url or "").strip().lower()
    if not normalized:
        return False
    markers = ("official", "tourism", "travel", "gov", "visit", "wikipedia", "tripadvisor")
    return any(marker in normalized for marker in markers)


def _looks_like_page_chrome_image(candidate: TavilyImageCandidate) -> bool:
    text = " ".join(
        part
        for part in [
            candidate.url,
            candidate.image_description,
            candidate.source_title,
        ]
        if part
    )
    return bool(_PAGE_CHROME_PATTERN.search(text))


def _looks_like_generic_page_asset(candidate: TavilyImageCandidate) -> bool:
    normalized = " ".join(
        _normalize_text(part).casefold()
        for part in [candidate.url, candidate.image_description, candidate.source_title]
        if part
    )
    generic_markers = ("cover", "thumb", "thumbnail", "default", "placeholder", "share", "social")
    return any(marker in normalized for marker in generic_markers)


def _extract_source_urls(payload: dict[str, Any]) -> list[str]:
    sources = payload.get("sources")
    if not isinstance(sources, list):
        return []
    urls: list[str] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "").strip()
        if url:
            urls.append(url)
    return _dedupe(urls)


def _extract_image_urls(payload: Any) -> list[str]:
    urls: list[str] = []

    def record(value: str) -> None:
        normalized = value.strip()
        if not normalized.startswith("http"):
            return
        if _IMAGE_EXTENSION_PATTERN.search(normalized) or _IMAGE_HINT_PATTERN.search(normalized):
            urls.append(normalized)

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_text = str(key).strip().lower()
                if isinstance(value, str):
                    if key_text in {"image", "image_url", "imageurl", "thumbnail", "thumbnail_url", "thumbnailurl", "og_image"}:
                        record(value)
                    for match in _IMAGE_URL_PATTERN.findall(value):
                        record(match)
                    for match in _OG_IMAGE_PATTERN.findall(value):
                        record(match)
                else:
                    visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, str):
            for match in _IMAGE_URL_PATTERN.findall(node):
                record(match)
            for match in _OG_IMAGE_PATTERN.findall(node):
                record(match)

    visit(payload)
    return _dedupe(urls)


def _dedupe(values: Iterable[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def _load_json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("empty LLM response")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("expected JSON object")
    return parsed
