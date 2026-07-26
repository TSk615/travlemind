from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from travelmind_api.agents.base import AgentRunStep, PlannedItem, PlanningRequest, PlanningResult
from travelmind_api.core.env import get_env
from travelmind_api.services.search_connector import ConfiguredSearchGateway, SearchServiceConfig

_logger = logging.getLogger(__name__)

_VISUAL_ITEM_TYPES = {"sight"}
_IMAGE_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_IMAGE_EXTENSION_PATTERN = re.compile(r"\.(?:png|jpe?g|webp|gif|bmp|svg)(?:$|[?#])", re.IGNORECASE)
_IMAGE_HINT_PATTERN = re.compile(r"(?:image|photo|thumbnail|hero|cover|poster)", re.IGNORECASE)
_OG_IMAGE_PATTERN = re.compile(r"(?:og:image|twitter:image)[^\"'>]*[\"'](https?://[^\"']+)", re.IGNORECASE)
_WHITESPACE_PATTERN = re.compile(r"\s+")
_ENGLISH_TOKEN_PATTERN = re.compile(r"[a-z0-9]{3,}", re.IGNORECASE)
_CJK_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,}")
_CJK_CHAR_PATTERN = re.compile(r"[\u4e00-\u9fff]")
_CJK_WEAK_MATCH_CHARS = set("大景区區风風")
_TRADITIONAL_TO_SIMPLIFIED = str.maketrans(
    {
        "聖": "圣",
        "亞": "亚",
        "園": "园",
        "區": "区",
        "風": "风",
        "濱": "滨",
        "爾": "尔",
        "東": "东",
        "歷": "历",
        "史": "史",
        "勝": "胜",
        "紀": "纪",
        "念": "念",
        "塔": "塔",
        "廣": "广",
        "場": "场",
    }
)
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
_DIRECT_IMAGE_ITEM_TIMEOUT_SECONDS = 30.0
_SCENE_HINTS_ZH = {
    "sight": "实景照片",
    "meal": "餐厅 菜品",
    "restaurant": "餐厅 菜品",
    "food": "餐厅 菜品",
    "hotel": "酒店 外观",
    "stay": "酒店 外观",
    "accommodation": "酒店 外观",
}
_SCENE_HINTS_EN = {
    "sight": "landmark photo",
    "meal": "restaurant food",
    "restaurant": "restaurant food",
    "food": "restaurant food",
    "hotel": "hotel exterior",
    "stay": "hotel exterior",
    "accommodation": "hotel exterior",
}
_STRATEGY_SUFFIX_PATTERN = re.compile(
    r"(二刷|再逛|酒店周边|商圈漫步|周边漫步|周边散步|附近漫步|附近散步|walk|stroll|free time|slow walk|nearby.*walk|surrounding.*walk)",
    re.IGNORECASE,
)
_SEPARATOR_PATTERN = re.compile(r"\s*(?:/|／|｜|\||·|•|、|与|和|及| plus | and | or | 或)\s*", re.IGNORECASE)


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


class TavilyImageCandidate(BaseModel):
    url: str
    source_url: str = ""
    source_title: str = ""
    source_snippet: str = ""
    image_description: str = ""
    origin: str = "result"
    result_rank: int = 0
    image_index: int = 0


def enrich_plan_images(
    plan: PlanningResult,
    request: PlanningRequest,
    *,
    search_service: SearchServiceConfig | None,
) -> PlanningResult:
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
            if _is_visual_candidate(item):
                if _has_existing_images(item):
                    # Re-runs keep already attached images instead of clearing them;
                    # such items are not searched again, so a failed re-run cannot drop them.
                    item.image_status = "completed"
                    item.image_failure_reason = None
                    item.image_priority_tier = None
                    item.image_priority_reason = None
                    continue
                item.image_urls = []
                item.image_source_urls = []
                item.image_failure_reason = None
                item.image_status = "pending"
                item.image_priority_tier = None
                item.image_priority_reason = None
                visual_items.append(item)
            else:
                item.image_urls = []
                item.image_source_urls = []
                item.image_failure_reason = None
                item.image_status = "skipped"
                item.image_priority_tier = "skipped"
                item.image_priority_reason = None
    return visual_items


def _has_existing_images(item: PlannedItem) -> bool:
    return any(str(url or "").strip() for url in (item.image_urls or []))


def _is_visual_candidate(item: PlannedItem) -> bool:
    item_type = str(item.type or "").strip().lower()
    if item_type not in _VISUAL_ITEM_TYPES:
        return False
    name = str(item.name or "").strip()
    if not name:
        return False
    return True


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
    search_key_by_item_id: dict[str, str] = {}
    representative_by_key: dict[str, PlannedItem] = {}
    unique_search_targets: list[PlannedItem] = []
    for item in search_targets:
        search_key = _image_search_cache_key(item, request)
        search_key_by_item_id[item.id] = search_key
        if search_key in representative_by_key:
            continue
        representative_by_key[search_key] = item
        unique_search_targets.append(item)

    outcomes: list[ImageSearchOutcome] = []
    if unique_search_targets:
        executor = ThreadPoolExecutor(
            max_workers=min(_DIRECT_IMAGE_MAX_WORKERS, len(unique_search_targets)),
            thread_name_prefix="trip-image-direct",
        )
        try:
            futures = [
                (item, executor.submit(_search_item_images_direct, resolved_search_service, request, item))
                for item in unique_search_targets
            ]
            for item, future in futures:
                try:
                    outcomes.append(future.result(timeout=_DIRECT_IMAGE_ITEM_TIMEOUT_SECONDS))
                except FuturesTimeoutError:
                    _logger.warning(
                        "Image search timed out after %.0fs for item %s (%s); skipping this item.",
                        _DIRECT_IMAGE_ITEM_TIMEOUT_SECONDS,
                        item.id,
                        _best_item_name(item),
                    )
                    outcomes.append(
                        ImageSearchOutcome(
                            item_id=item.id,
                            status="failed",
                            failure_reason=f"Image search timed out after {int(_DIRECT_IMAGE_ITEM_TIMEOUT_SECONDS)}s.",
                            review_mode="search_timeout",
                        )
                    )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    all_citations: list[str] = []
    completed = 0
    failed = 0
    total_raw_candidates = 0
    total_selected = 0
    candidate_debug_notes: list[str] = []
    representative_key_by_id = {
        item.id: search_key
        for search_key, item in representative_by_key.items()
    }
    outcomes_by_key = {
        representative_key_by_id[outcome.item_id]: outcome
        for outcome in outcomes
        if outcome.item_id in representative_key_by_id
    }
    counted_outcome_keys: set[str] = set()
    for item in search_targets:
        search_key = search_key_by_item_id[item.id]
        outcome = outcomes_by_key.get(search_key)
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
        if search_key not in counted_outcome_keys:
            total_raw_candidates += outcome.candidate_count_raw
            total_selected += outcome.candidate_count_after_review
            candidate_debug_notes.extend(_build_candidate_debug_notes(item, outcome))
            counted_outcome_keys.add(search_key)
        elif outcome.image_urls:
            representative = representative_by_key[search_key]
            candidate_debug_notes.append(
                f"Image debug [{_best_item_name(item)}] reused images from {_best_item_name(representative)}."
            )
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
            f"Execution strategy: direct pending sight items parallel (max {_DIRECT_IMAGE_MAX_WORKERS} workers); image LLM roles skipped.",
            f"Search targets deduplicated: unique={len(unique_search_targets)}, total={len(search_targets)}.",
            f"Per-item image cap: {_DIRECT_IMAGE_COUNT_PER_ITEM}.",
            *query_previews,
            f"Candidate counts: raw={total_raw_candidates}, selected={total_selected}.",
            *candidate_debug_notes[:12],
        ],
        citations=_dedupe(all_citations),
    )


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
    return _build_direct_sight_image_query(item, request)


def _build_direct_sight_image_query(item: PlannedItem, request: PlanningRequest) -> str:
    subject = _normalize_text(_derive_canonical_item_name(item) or str(item.name or ""))
    destination = _normalize_text(str(request.destination or ""))
    parts = [
        f"\"{subject}\"" if subject else "",
        destination,
        _scene_hint_for_item(item, request, subject=subject, destination=destination),
    ]
    return " ".join(_dedupe_preserve_order([part for part in parts if part]))


def _scene_hint_for_item(item: PlannedItem, request: PlanningRequest, *, subject: str, destination: str) -> str:
    locale_hint = str(request.locale or "").strip().lower()
    zh_output = locale_hint.startswith("zh") or bool(_CJK_TOKEN_PATTERN.search(subject + destination))
    hints = _SCENE_HINTS_ZH if zh_output else _SCENE_HINTS_EN
    return hints.get(str(item.type or "").strip().lower(), "")


def _image_search_cache_key(item: PlannedItem, request: PlanningRequest) -> str:
    destination = _normalize_text(str(request.destination or "")).casefold()
    subject = _normalize_text(_derive_canonical_item_name(item) or str(item.name or "")).casefold()
    return f"{destination}::{subject or item.id}"


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
        ranked_candidates = _rank_tavily_image_candidates(candidates, item, request)
        selected_candidates = ranked_candidates[:_DIRECT_IMAGE_COUNT_PER_ITEM]
        image_urls = _dedupe([candidate.url for candidate in selected_candidates])
        source_urls = _dedupe([candidate.source_url for candidate in selected_candidates if candidate.source_url])
        if not image_urls:
            failure_reason = (
                f"Tavily returned no image candidates for query: {query}"
                if not candidates
                else f"Tavily returned {len(candidates)} image candidates, but none passed sight relevance filters for query: {query}"
            )
            return ImageSearchOutcome(
                item_id=item.id,
                image_urls=[],
                source_urls=[],
                status="failed",
                failure_reason=failure_reason,
                candidate_count_raw=len(candidates),
                candidate_count_after_rules=len(ranked_candidates),
                candidate_count_after_review=0,
                review_mode="rules_only",
                review_summary="Direct Tavily rule ranking found no usable sight image candidates.",
                debug_query=query,
                debug_candidates_raw=[_serialize_tavily_candidate(candidate) for candidate in candidates[:8]],
                debug_candidates_after_rules=[_serialize_tavily_candidate(candidate) for candidate in ranked_candidates[:8]],
                debug_candidates_after_review=[],
            )
        return ImageSearchOutcome(
            item_id=item.id,
            image_urls=image_urls,
            source_urls=source_urls,
            status="completed",
            failure_reason=None,
            candidate_count_raw=len(candidates),
            candidate_count_after_rules=len(ranked_candidates),
            candidate_count_after_review=len(selected_candidates),
            review_mode="rules_only",
            review_summary="Direct Tavily candidate selection with rule ranking; image LLM roles skipped.",
            debug_query=query,
            debug_candidates_raw=[_serialize_tavily_candidate(candidate) for candidate in candidates[:8]],
            debug_candidates_after_rules=[_serialize_tavily_candidate(candidate) for candidate in ranked_candidates[:8]],
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


def _derive_canonical_item_name(item: PlannedItem) -> str:
    source_name = _normalize_text(str(item.name or ""))
    if not source_name:
        if _looks_like_real_location_ref_name(item):
            return _normalize_text(str(item.location_ref.name or ""))
        return ""
    cleaned = _normalize_text(_STRATEGY_SUFFIX_PATTERN.sub(" ", source_name))
    cleaned = _normalize_text(re.sub(r"\b(?:hotel area|area)\b", " ", cleaned, flags=re.IGNORECASE))
    parts = [part for part in _SEPARATOR_PATTERN.split(cleaned) if _normalize_text(part)]
    cleaned_parts = [_normalize_text(_STRATEGY_SUFFIX_PATTERN.sub(" ", part)) for part in parts if _normalize_text(_STRATEGY_SUFFIX_PATTERN.sub(" ", part))]
    if cleaned_parts:
        for part in cleaned_parts:
            if _token_count(part) >= 2:
                return part
        return cleaned_parts[0]
    return cleaned or source_name


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
    item_name = _derive_canonical_item_name(item)
    if item_name:
        return item_name
    if _looks_like_real_location_ref_name(item):
        return str(item.location_ref.name).strip()
    return ""


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

    top_level_images = payload.get("images")
    if isinstance(top_level_images, list):
        for image_index, image in enumerate(top_level_images):
            if isinstance(image, dict):
                url = str(image.get("url") or "").strip()
                image_description = str(image.get("description") or "").strip()
                image_title = str(image.get("title") or "").strip()
            else:
                url = str(image or "").strip()
                image_description = ""
                image_title = ""
            if url:
                candidates.append(
                    TavilyImageCandidate(
                        url=url,
                        source_url="",
                        source_title=image_title,
                        source_snippet="",
                        image_description=image_description,
                        origin="top_level",
                        result_rank=999,
                        image_index=image_index,
                    )
                )

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
    filtered: list[TavilyImageCandidate] = []
    for candidate in candidates:
        if _looks_like_disallowed_image_url(candidate.url):
            continue
        if _looks_like_page_chrome_image(candidate):
            continue
        if _looks_like_generic_page_asset(candidate):
            continue
        if not _candidate_matches_item_subject(candidate, item):
            continue
        filtered.append(candidate)
    scored = [
        (_score_tavily_image_candidate(candidate, item, request), index, candidate)
        for index, candidate in enumerate(filtered)
    ]
    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    return [candidate for _, _, candidate in scored]


def _candidate_matches_item_subject(candidate: TavilyImageCandidate, item: PlannedItem) -> bool:
    source_text = " ".join(
        part
        for part in [
            candidate.source_title,
            candidate.image_description,
            candidate.source_url,
            candidate.url,
        ]
        if part
    )
    normalized_source = _normalize_match_text(source_text)
    source_tokens = set(_tokenize_for_match(normalized_source))
    aliases = _dedupe_preserve_order(
        [
            _normalize_text(_best_item_name(item)),
            _normalize_text(str(item.name or "")),
            _normalize_text(str(item.location_ref.name if item.location_ref is not None and _looks_like_real_location_ref_name(item) else "")),
        ]
    )
    for alias in aliases:
        if not alias:
            continue
        alias_lower = _normalize_match_text(alias)
        if alias_lower and alias_lower in normalized_source:
            return True
        alias_tokens = [token for token in _tokenize_for_match(alias_lower) if token]
        if not alias_tokens:
            if _cjk_fuzzy_match(alias_lower, normalized_source):
                return True
            continue
        required_overlap = 1 if len(alias_tokens) == 1 else 2
        if sum(1 for token in alias_tokens if token in source_tokens) >= required_overlap:
            return True
        if _cjk_fuzzy_match(alias_lower, normalized_source):
            return True
    return False


def _normalize_match_text(value: str) -> str:
    normalized = _normalize_text(value).casefold().translate(_TRADITIONAL_TO_SIMPLIFIED)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", normalized)


def _cjk_fuzzy_match(alias: str, source: str) -> bool:
    alias_chars = [char for char in _CJK_CHAR_PATTERN.findall(alias) if char not in _CJK_WEAK_MATCH_CHARS]
    if len(alias_chars) < 3:
        return False
    source_chars = set(_CJK_CHAR_PATTERN.findall(source))
    overlap = sum(1 for char in alias_chars if char in source_chars)
    return overlap >= max(3, int(len(alias_chars) * 0.75))


def _looks_like_disallowed_image_url(url: str) -> bool:
    path = urlparse(str(url or "")).path.lower()
    return path.endswith(".svg")


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
