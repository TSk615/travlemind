from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import date
from time import perf_counter
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from travelmind_api.agents.helloagents import HelloAgentsOrchestrator, HelloAgentsPoiGrounding
from travelmind_api.api.schemas.common import success_response
from travelmind_api.api.schemas.llm import LlmConnectionTestRequest, LlmConnectionTestResponse, LlmModelsRequest, LlmProxyRequest
from travelmind_api.core.config import get_settings
from travelmind_api.core.deps import get_current_user
from travelmind_api.core.env import get_env
from travelmind_api.core.upstream_urls import UpstreamUrlError, normalize_upstream_base_url
from travelmind_api.db.models import User
from travelmind_api.prompts import build_poi_specialist_prompt
from travelmind_api.services.llm import LlmConfig, OpenAICompatibleClient
from travelmind_api.services.llm.config import default_base_url_for_protocol, normalize_provider_protocol, normalize_wire_api
from travelmind_api.services.llm.models import fetch_llm_models
from travelmind_api.services.llm.user_config import build_user_poi_role_overrides
from travelmind_api.services.search_connector import (
    ConfiguredSearchGateway,
    DEFAULT_IMAGE_INCLUDE_DOMAINS,
    DEFAULT_IMAGE_PER_DOMAIN_LIMIT,
    SearchServiceConfig,
    SearchServiceGatewayError,
    normalize_domain_filter_values,
    normalize_search_service_provider,
)
from travelmind_api.services.xhs_account import load_xhs_search_state, mark_xhs_session_available, mark_xhs_session_expired
from travelmind_api.services.xhs_crawler import XhsCrawlerClient, XhsCrawlerClientError, XhsCrawlerConfig, XhsCrawlerSessionExpiredError

router = APIRouter(prefix="/llm", tags=["llm"])


class SearchProxyRequest(LlmProxyRequest):
    provider: str | None = None
    transport: str | None = None
    timeout_seconds: float | None = None
    query: str


class SearchImageProxyRequest(SearchProxyRequest):
    preferred_tool: str | None = None
    fetch_top_n: int = 3


class PoiSpecialistProbeRequest(LlmProxyRequest):
    search_provider: str | None = Field(default=None, max_length=64)
    search_transport: str | None = Field(default=None, max_length=64)
    search_base_url: str | None = Field(default=None, max_length=512)
    search_api_key: str | None = Field(default=None, max_length=4096)
    search_timeout_seconds: float | None = Field(default=None, gt=0, le=300)
    destination: str = Field(min_length=1, max_length=255)
    origin: str | None = Field(default="", max_length=255)
    start_date: str | None = Field(default="", max_length=32)
    end_date: str | None = Field(default="", max_length=32)
    budget: float | None = Field(default=None, ge=0)
    travelers: int = Field(default=2, ge=1, le=20)
    interests: list[str] = Field(default_factory=list, max_length=20)
    accommodation_preference: str | None = Field(default="", max_length=255)
    pace: str | None = Field(default="balanced", max_length=64)
    transport_mode: str | None = Field(default="", max_length=64)
    user_input: str | None = Field(default="", max_length=4000)
    use_search: bool = True


class TavilyImagesProxyRequest(LlmProxyRequest):
    query: str
    base_url: str | None = None
    api_key: str | None = None
    search_depth: str = "basic"
    max_results: int = 8
    include_image_descriptions: bool = True


class XhsImagesProxyRequest(BaseModel):
    destination: str = Field(min_length=1, max_length=255)
    queries: list[str] = Field(default_factory=list, max_length=4)
    limit_per_query: int = Field(default=5, ge=1, le=10)


_IMAGE_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_IMAGE_EXTENSION_PATTERN = re.compile(r"\.(?:png|jpe?g|webp|gif|bmp|svg)(?:$|[?#])", re.IGNORECASE)
_IMAGE_HINT_PATTERN = re.compile(r"(?:image|photo|thumbnail|hero|cover|poster)", re.IGNORECASE)
_OG_IMAGE_PATTERN = re.compile(r"(?:og:image|twitter:image)[^\"'>]*[\"'](https?://[^\"']+)", re.IGNORECASE)
_TAVILY_IMAGE_RESPONSE_LIMIT = 24


def _validate_upstream_base_url(base_url: str) -> str:
    try:
        normalized = normalize_upstream_base_url(base_url, get_settings())
    except UpstreamUrlError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_upstream_base_url", "message": str(exc)},
        ) from exc
    if normalized is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_upstream_base_url", "message": "base_url must be a valid http or https URL"},
        )
    return normalized


def _build_endpoint(base_url: str, wire_api: str) -> str:
    base = base_url.strip().rstrip("/")
    mode = normalize_wire_api(wire_api, default="responses")
    if mode == "responses":
        return base if base.endswith("/responses") else f"{base}/responses"
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


def _infer_wire_api(payload: dict[str, Any], user: User) -> str:
    explicit = user.llm_wire_api
    if isinstance(payload.get("messages"), list):
        return normalize_wire_api(explicit, default="chat_completions") if explicit else "chat_completions"
    return normalize_wire_api(explicit, default="responses") if explicit else "responses"


def _resolve_proxy_config(payload: LlmProxyRequest, user: User) -> LlmConfig:
    upstream_payload = payload.payload if isinstance(payload.payload, dict) else {}
    provider_protocol = payload.provider_protocol or getattr(user, "llm_provider_protocol", None)
    normalized_protocol = normalize_provider_protocol(provider_protocol)
    merged = {
        "provider_protocol": normalized_protocol,
        "base_url": payload.base_url or user.llm_base_url or default_base_url_for_protocol(normalized_protocol),
        "api_key": payload.api_key or user.llm_api_key,
        "model": upstream_payload.get("model") or user.llm_model,
        "wire_api": payload.wire_api or _infer_wire_api(upstream_payload, user),
        "role_overrides": build_user_poi_role_overrides(user),
    }
    config = LlmConfig.from_mapping(merged)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "llm_proxy_not_configured", "message": "Configure base_url, api_key, model, and API format before using the relay."},
        )
    return config.model_copy(update={"base_url": _validate_upstream_base_url(config.base_url)})


def _normalize_llm_settings_scope(scope: str | None) -> str:
    return "poi" if str(scope or "").strip().lower() == "poi" else "agent"


def _saved_llm_value(user: User, scope: str, field: str) -> Any:
    prefix = "poi_llm" if scope == "poi" else "llm"
    return getattr(user, f"{prefix}_{field}", None)


def _resolve_connection_test_config(payload: LlmConnectionTestRequest, user: User) -> LlmConfig:
    scope = _normalize_llm_settings_scope(payload.scope)
    provider_protocol = normalize_provider_protocol(payload.provider_protocol or _saved_llm_value(user, scope, "provider_protocol"))
    config = LlmConfig.from_mapping(
        {
            "provider_protocol": provider_protocol,
            "base_url": payload.base_url or _saved_llm_value(user, scope, "base_url") or default_base_url_for_protocol(provider_protocol),
            "api_key": payload.api_key or _saved_llm_value(user, scope, "api_key"),
            "model": payload.model or _saved_llm_value(user, scope, "model"),
            "wire_api": payload.wire_api or _saved_llm_value(user, scope, "wire_api"),
            "timeout_seconds": payload.timeout_seconds or 30.0,
        }
    )
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "llm_test_not_configured", "message": "Configure base_url, api_key, model, and API format before testing the model connection."},
        )
    return config.model_copy(update={"base_url": _validate_upstream_base_url(config.base_url)})


def _extract_proxy_messages(upstream_payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_messages = upstream_payload.get("messages")
    if isinstance(raw_messages, list):
        return [
            {"role": str(message.get("role") or "user"), "content": message.get("content", "")}
            for message in raw_messages
            if isinstance(message, dict)
        ]

    raw_input = upstream_payload.get("input")
    if isinstance(raw_input, str):
        return [{"role": "user", "content": raw_input}]
    if isinstance(raw_input, list):
        messages: list[dict[str, Any]] = []
        for item in raw_input:
            if not isinstance(item, dict):
                continue
            messages.append({"role": str(item.get("role") or "user"), "content": item.get("content", "")})
        if messages:
            return messages
    return [{"role": "user", "content": json.dumps(upstream_payload, ensure_ascii=False)}]


def _proxy_native_protocol_request(upstream_payload: dict[str, Any], config: LlmConfig) -> Response:
    messages = _extract_proxy_messages(upstream_payload)
    temperature = upstream_payload.get("temperature")
    try:
        resolved_temperature = float(temperature) if temperature is not None else 0.2
    except (TypeError, ValueError):
        resolved_temperature = 0.2
    max_tokens_raw = upstream_payload.get("max_tokens") or upstream_payload.get("max_output_tokens")
    try:
        max_tokens = int(max_tokens_raw) if max_tokens_raw is not None else None
    except (TypeError, ValueError):
        max_tokens = None
    content = OpenAICompatibleClient(config).create_chat_completion(messages=messages, temperature=resolved_temperature, max_tokens=max_tokens)
    if config.wire_api == "responses":
        body = {"output_text": content}
    else:
        body = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    return Response(content=json.dumps(body, ensure_ascii=False), status_code=200, media_type="application/json")


def _prepare_payload(payload: dict[str, Any], config: LlmConfig) -> dict[str, Any]:
    prepared = dict(payload)
    prepared.setdefault("model", config.model)
    prepared.setdefault("stream", False)
    if config.wire_api == "responses" and "input" not in prepared and isinstance(prepared.get("messages"), list):
        prepared["input"] = [
            {
                "role": str(message.get("role") or "user"),
                "content": [{"type": "input_text", "text": str(message.get("content") or "")}],
            }
            for message in prepared["messages"]
            if isinstance(message, dict)
        ]
        prepared.pop("messages", None)
    return prepared


def _prepare_upstream_headers(upstream: httpx.Response) -> dict[str, str]:
    headers = {
        "Content-Type": upstream.headers.get("content-type", "application/json"),
        "Cache-Control": upstream.headers.get("cache-control", "no-cache"),
    }
    trace_id = upstream.headers.get("trace-id")
    if trace_id:
        headers["x-upstream-trace-id"] = trace_id
    return headers


def _consume_upstream_body(upstream: httpx.Response) -> tuple[bytes, bool]:
    body = bytearray()
    try:
        for chunk in upstream.iter_bytes():
            if chunk:
                body.extend(chunk)
    except httpx.HTTPError:
        if body:
            return bytes(body), True
        raise
    return bytes(body), False


def _stream_upstream_body(client: httpx.Client, upstream: httpx.Response) -> Iterator[bytes]:
    try:
        for chunk in upstream.iter_bytes():
            if chunk:
                yield chunk
    finally:
        upstream.close()
        client.close()


def _resolve_search_proxy_config(payload: SearchProxyRequest, user: User) -> SearchServiceConfig:
    merged = {
        "provider": payload.provider or getattr(user, "search_service_provider", None),
        "transport": payload.transport or getattr(user, "search_service_transport", None),
        "base_url": payload.base_url or getattr(user, "search_service_base_url", None),
        "api_key": payload.api_key or getattr(user, "search_service_api_key", None),
        "timeout_seconds": payload.timeout_seconds or getattr(user, "search_service_timeout_seconds", None),
    }
    config = SearchServiceConfig.from_mapping(merged)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "search_proxy_not_configured",
                "message": "Configure provider, base_url, api_key, and transport before testing the search service.",
            },
        )
    return config.model_copy(update={"base_url": _validate_upstream_base_url(config.base_url)})


def _pick_search_operation(config: SearchServiceConfig, available_tools: set[str], query: str) -> tuple[str, dict[str, Any]]:
    normalized_query = query.strip()
    if not normalized_query:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "search_query_required", "message": "Provide a search query before testing the search service."},
        )

    if config.provider == "groksearch":
        if "web_search" in available_tools:
            return ("web_search", {"query": normalized_query})
        if "search" in available_tools:
            return ("search", {"query": normalized_query, "num_results": 8, "include_text": True})
        if "answer" in available_tools:
            return ("answer", {"query": normalized_query, "include_text": True})
    else:
        if "search" in available_tools:
            return ("search", {"query": normalized_query, "num_results": 8, "include_text": True})
        if "answer" in available_tools:
            return ("answer", {"query": normalized_query, "include_text": True})

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "code": "search_operation_unavailable",
            "message": "Configured search service does not expose a quick search operation.",
            "details": {"available_tools": sorted(available_tools)},
        },
    )


def _extract_search_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results")
    if isinstance(results, list):
        return [item for item in results if isinstance(item, dict)]

    sources = payload.get("sources")
    if isinstance(sources, list):
        return [item for item in sources if isinstance(item, dict)]

    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]

    nested_result = payload.get("result")
    if isinstance(nested_result, dict):
        return _extract_search_items(nested_result)

    return []


def _extract_search_url(item: dict[str, Any]) -> str:
    for key in ("url", "link", "source", "id", "website", "href"):
        candidate = str(item.get(key) or "").strip()
        if candidate.startswith("http"):
            return candidate
    return ""


def _summarize_search_hits(payload: dict[str, Any]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for item in _extract_search_items(payload):
        url = _extract_search_url(item)
        if not url:
            continue
        title = str(item.get("title") or item.get("name") or url).strip() or url
        snippet = str(
            item.get("snippet")
            or item.get("summary")
            or item.get("text")
            or item.get("highlight")
            or item.get("description")
            or item.get("content")
            or ""
        ).strip()
        hits.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "published_at": str(item.get("published_at") or item.get("publishedDate") or "").strip() or None,
            }
        )
    return hits


def _pick_image_operation(config: SearchServiceConfig, available_tools: set[str], preferred_tool: str | None = None) -> tuple[str, str]:
    preferred = str(preferred_tool or "").strip()
    if preferred and preferred in available_tools:
        return preferred, "preferred"

    ranked_candidates = (
        "image_search",
        "images_search",
        "search_images",
        "search_image",
        "tavily_images",
        "tavily_image_search",
        "web_search",
    )
    for candidate in ranked_candidates:
        if candidate in available_tools:
            return candidate, "built-in-image" if candidate != "web_search" else "search-fallback"

    if config.provider in {"groksearch", "tavily"} and "search" in available_tools:
        return "search", "search-fallback"
    if "answer" in available_tools:
        return "answer", "search-fallback"
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "code": "image_operation_unavailable",
            "message": "Configured search service does not expose an image-capable or search fallback tool.",
            "details": {"available_tools": sorted(available_tools)},
        },
    )


def _build_image_operation_arguments(tool_name: str, query: str) -> dict[str, Any]:
    normalized_query = query.strip()
    if tool_name in {"image_search", "images_search", "search_images", "search_image", "tavily_images", "tavily_image_search"}:
        return {"query": normalized_query, "num_results": 8, "include_images": True}
    if tool_name == "web_search":
        return {"query": normalized_query}
    if tool_name == "search":
        return {"query": normalized_query, "num_results": 8, "include_text": True}
    if tool_name == "answer":
        return {"query": normalized_query, "include_text": True}
    return {"query": normalized_query}


def _extract_image_urls(payload: Any) -> list[str]:
    results: list[str] = []

    def record(value: str) -> None:
        candidate = value.strip()
        if not candidate.startswith("http"):
            return
        if _IMAGE_EXTENSION_PATTERN.search(candidate) or _IMAGE_HINT_PATTERN.search(candidate):
            results.append(candidate)

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
    seen: set[str] = set()
    deduped: list[str] = []
    for url in results:
        key = url.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(url)
    return deduped


def _build_streaming_proxy_response(client: httpx.Client, upstream: httpx.Response) -> StreamingResponse:
    return StreamingResponse(
        _stream_upstream_body(client, upstream),
        status_code=upstream.status_code,
        headers=_prepare_upstream_headers(upstream),
        media_type=upstream.headers.get("content-type", "application/json"),
    )


def _resolve_tavily_endpoint(payload: TavilyImagesProxyRequest) -> str:
    base = _validate_upstream_base_url(str(payload.base_url or "https://api.tavily.com/search").strip().rstrip("/"))
    if base.endswith("/search"):
        return base
    return f"{base}/search"


def _resolve_tavily_image_include_domains() -> list[str]:
    return normalize_domain_filter_values(
        get_env("TRAVELMIND_TAVILY_IMAGE_INCLUDE_DOMAINS") or get_env("TRAVELMIND_IMAGE_SEARCH_INCLUDE_DOMAINS"),
        default=DEFAULT_IMAGE_INCLUDE_DOMAINS,
    )


def _normalize_probe_queries(queries: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in queries:
        candidate = str(item or "").strip()
        key = candidate.casefold()
        if not candidate or key in seen:
            continue
        seen.add(key)
        normalized.append(candidate)
    return normalized[:4]


def _limit_tavily_raw_result_images(raw: dict[str, Any], limit: int = _TAVILY_IMAGE_RESPONSE_LIMIT) -> dict[str, Any]:
    limited = dict(raw)
    top_images = limited.get("images")
    if isinstance(top_images, list):
        limited["images_total_count"] = len(top_images)
        limited["images_truncated"] = len(top_images) > limit
        limited["images"] = top_images[:limit]

    results = limited.get("results")
    if isinstance(results, list):
        limited_results: list[Any] = []
        for item in results:
            if not isinstance(item, dict):
                limited_results.append(item)
                continue
            limited_item = dict(item)
            item_images = limited_item.get("images")
            if isinstance(item_images, list):
                limited_item["images_total_count"] = len(item_images)
                limited_item["images_truncated"] = len(item_images) > limit
                limited_item["images"] = item_images[:limit]
            limited_results.append(limited_item)
        limited["results"] = limited_results
    return limited


def _normalize_poi_probe_interests(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        candidate = str(value or "").strip()
        key = candidate.casefold()
        if not candidate or key in seen:
            continue
        seen.add(key)
        normalized.append(candidate)
    return normalized[:12]


def _parse_probe_date(value: str | None) -> date | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    try:
        return date.fromisoformat(candidate)
    except ValueError:
        return None


def _calculate_probe_trip_days(start_date: str | None, end_date: str | None) -> int:
    start = _parse_probe_date(start_date)
    end = _parse_probe_date(end_date)
    if start is None or end is None or end < start:
        return 3
    return max(1, (end - start).days + 1)


def _build_poi_probe_input_payload(payload: PoiSpecialistProbeRequest) -> dict[str, Any]:
    destination = str(payload.destination or "").strip()
    interests = _normalize_poi_probe_interests(payload.interests)
    trip_days = _calculate_probe_trip_days(payload.start_date, payload.end_date)
    pace = str(payload.pace or "balanced").strip() or "balanced"
    transport = str(payload.transport_mode or "").strip()
    accommodation = str(payload.accommodation_preference or "").strip()
    user_input = str(payload.user_input or "").strip()
    budget_band = "unknown" if payload.budget is None else "user_provided"
    title = f"{destination} POI 专家测试"

    trip_request = {
        "trip_id": "llm-demo-poi-specialist",
        "title": title,
        "origin": str(payload.origin or "").strip(),
        "destination": destination,
        "start_date": str(payload.start_date or "").strip(),
        "end_date": str(payload.end_date or "").strip(),
        "trip_days": trip_days,
        "budget": payload.budget,
        "travelers": payload.travelers,
        "interests": interests,
        "accommodation_preference": accommodation,
        "pace": pace,
        "transport_mode": transport,
        "raw_user_input": user_input,
    }
    planning_brief = {
        "destination": destination,
        "trip_days": trip_days,
        "budget_band": budget_band,
        "budget_is_hard_constraint": False,
        "budget_priority": "POI 测试阶段只记录价格证据，不做最终预算分配。",
        "allow_budget_flex": True,
        "pace": pace,
        "must_have": interests,
        "avoid": [],
        "transport": transport,
        "accommodation": accommodation,
        "interests": interests,
        "planning_constraints": ["这里只测试 POI 发现，不生成最终行程。", "价格、评分、评论数缺少搜索证据时写 unknown。"],
        "raw_user_input": user_input,
    }
    return {
        "trip_request": trip_request,
        "planning_brief": planning_brief,
        "poi_context": {
            "budget": payload.budget,
            "travelers": payload.travelers,
            "pace": pace,
            "interests": interests,
            "must_have": interests,
            "avoid": [],
            "food_interests": interests,
        },
    }


def _resolve_poi_probe_search_config(payload: PoiSpecialistProbeRequest, user: User) -> SearchServiceConfig | None:
    merged = {
        "provider": payload.search_provider or getattr(user, "search_service_provider", None),
        "transport": payload.search_transport or getattr(user, "search_service_transport", None),
        "base_url": payload.search_base_url or getattr(user, "search_service_base_url", None),
        "api_key": payload.search_api_key or getattr(user, "search_service_api_key", None),
        "timeout_seconds": payload.search_timeout_seconds or getattr(user, "search_service_timeout_seconds", None),
    }
    config = SearchServiceConfig.from_mapping(merged)
    if config is None:
        return None
    return config.model_copy(update={"base_url": _validate_upstream_base_url(config.base_url)})


def _parse_probe_json_text(raw_text: str) -> tuple[dict[str, Any] | None, str | None]:
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
            except json.JSONDecodeError as nested_exc:
                return None, str(nested_exc)
        else:
            return None, str(exc)
    if not isinstance(parsed, dict):
        return None, "POI specialist response JSON root was not an object."
    return parsed, None


def _resolve_probe_temperature(payload: dict[str, Any]) -> float:
    try:
        temperature = float(payload.get("temperature", 0.2))
    except (TypeError, ValueError):
        return 0.2
    return min(max(temperature, 0.0), 2.0)


def _resolve_probe_max_tokens(payload: dict[str, Any]) -> int:
    raw = payload.get("max_tokens") or payload.get("max_output_tokens") or 6000
    try:
        max_tokens = int(raw)
    except (TypeError, ValueError):
        return 6000
    return min(max(max_tokens, 512), 16000)


def _collect_poi_probe_tool_results(
    payload: PoiSpecialistProbeRequest,
    current_user: User,
    input_payload: dict[str, Any],
    orchestrator: HelloAgentsOrchestrator,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    del current_user, input_payload, orchestrator
    search_meta: dict[str, Any] = {
        "enabled": False,
        "requested": bool(payload.use_search),
        "configured": False,
        "skipped": True,
        "reason": "POI specialist probe skips external search-service injection; use the configured POI model's native search if it supports it, and return compact evidence only.",
        "native_search_allowed": True,
        "external_tool_collection": False,
        "tool_result_keys": [],
        "citations": [],
    }
    warnings = [search_meta["reason"]] if payload.use_search else []
    return {}, search_meta, warnings


@router.post("/poi-specialist-probe")
def probe_poi_specialist(payload: PoiSpecialistProbeRequest, current_user: User = Depends(get_current_user)):
    llm_config = _resolve_proxy_config(payload, current_user)
    llm_config = llm_config.model_copy(update={"timeout_seconds": max(float(llm_config.timeout_seconds), 300.0)})
    orchestrator = HelloAgentsOrchestrator(None)
    input_payload = _build_poi_probe_input_payload(payload)
    tool_results, search_meta, warnings = _collect_poi_probe_tool_results(payload, current_user, input_payload, orchestrator)
    enriched_payload = dict(input_payload)
    if tool_results:
        enriched_payload["tool_results"] = tool_results
    prompt_payload = orchestrator._build_role_prompt_payload(enriched_payload, role_name="poi_specialist")
    prompt_payload_json = json.dumps(prompt_payload, ensure_ascii=False)

    prompt = build_poi_specialist_prompt()
    system_prompt = f"{prompt.system_prompt} 请使用简体中文输出。Target output locale: zh-CN."
    started = perf_counter()
    try:
        raw_text = OpenAICompatibleClient(llm_config).create_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_payload_json},
            ],
            temperature=_resolve_probe_temperature(payload.payload),
            max_tokens=_resolve_probe_max_tokens(payload.payload),
            stream=True,
        )
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else 502
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "poi_specialist_probe_upstream_failed", "message": f"POI specialist request failed with upstream status {status_code}."},
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "poi_specialist_probe_failed", "message": str(exc) or "POI specialist probe failed."},
        ) from exc

    parsed_json, parse_error = _parse_probe_json_text(raw_text)
    if parsed_json is not None:
        try:
            parsed_json = HelloAgentsPoiGrounding.model_validate(parsed_json).model_dump(mode="json")
        except Exception:
            pass
    return success_response(
        {
            "prompt_version": prompt.version,
            "system_prompt": system_prompt,
            "model": llm_config.model,
            "provider_protocol": llm_config.provider_protocol,
            "wire_api": llm_config.wire_api,
            "latency_ms": int((perf_counter() - started) * 1000),
            "payload_bytes": len(prompt_payload_json.encode("utf-8")),
            "input_snapshot": enriched_payload,
            "prompt_payload": prompt_payload,
            "search": search_meta,
            "warnings": warnings,
            "citations": search_meta.get("citations", []),
            "raw_text": raw_text,
            "parsed_json": parsed_json,
            "parse_error": parse_error,
        }
    )


@router.post("/proxy")
def proxy_llm_request(payload: LlmProxyRequest, current_user: User = Depends(get_current_user)):
    config = _resolve_proxy_config(payload, current_user)
    endpoint = _build_endpoint(config.base_url, config.wire_api)
    upstream_payload = _prepare_payload(payload.payload, config)
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    try:
        if normalize_provider_protocol(config.provider_protocol) not in {"openai", "newapi", "neiapi"}:
            return _proxy_native_protocol_request(upstream_payload, config)

        timeout = httpx.Timeout(connect=20.0, read=300.0, write=60.0, pool=60.0)
        should_stream = bool(upstream_payload.get("stream"))

        if should_stream:
            client = httpx.Client(timeout=timeout, follow_redirects=True)
            try:
                request = client.build_request("POST", endpoint, headers=headers, json=upstream_payload)
                upstream = client.send(request, stream=True)
            except Exception:
                client.close()
                raise
            return _build_streaming_proxy_response(client, upstream)

        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("POST", endpoint, headers=headers, json=upstream_payload) as upstream:
                passthrough_headers = _prepare_upstream_headers(upstream)
                raw_body, truncated = _consume_upstream_body(upstream)
                if truncated:
                    passthrough_headers["x-upstream-body-truncated"] = "1"
                return Response(content=raw_body, status_code=upstream.status_code, headers=passthrough_headers)
    except httpx.TimeoutException:
        body = json.dumps({"error": {"message": "Upstream model request timed out"}})
        return Response(content=body, status_code=504, media_type="application/json")
    except httpx.HTTPError as exc:
        body = json.dumps({"error": {"message": str(exc)}})
        return Response(content=body, status_code=502, media_type="application/json")


@router.post("/models")
def list_llm_models(payload: LlmModelsRequest, current_user: User = Depends(get_current_user)):
    scope = _normalize_llm_settings_scope(payload.scope)
    provider_protocol = normalize_provider_protocol(payload.provider_protocol or _saved_llm_value(current_user, scope, "provider_protocol"))
    api_key = str(payload.api_key or _saved_llm_value(current_user, scope, "api_key") or "").strip()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "llm_models_api_key_required", "message": "Provide or save an API key before fetching models."},
        )
    base_url = _validate_upstream_base_url(
        str(payload.base_url or _saved_llm_value(current_user, scope, "base_url") or default_base_url_for_protocol(provider_protocol)).strip().rstrip("/")
    )
    timeout_seconds = float(payload.timeout_seconds or 30.0)
    try:
        result = fetch_llm_models(
            provider_protocol=provider_protocol,
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else 502
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "llm_models_upstream_failed", "message": f"Model list request failed with upstream status {status_code}."},
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "llm_models_request_failed", "message": str(exc) or "Model list request failed."},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "llm_models_invalid_response", "message": str(exc) or "Model list response was invalid."},
        ) from exc
    return success_response(result.model_dump(mode="json"))


@router.post("/test")
def test_llm_connection(payload: LlmConnectionTestRequest, current_user: User = Depends(get_current_user)):
    scope = _normalize_llm_settings_scope(payload.scope)
    config = _resolve_connection_test_config(payload, current_user)
    started = perf_counter()
    try:
        reply = OpenAICompatibleClient(config).create_chat_completion(
            messages=[{"role": "user", "content": "Reply with exactly: ok"}],
            temperature=0,
            max_tokens=16,
            stream=scope == "poi",
        )
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else 502
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "llm_test_upstream_failed", "message": f"Model test request failed with upstream status {status_code}."},
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "llm_test_request_failed", "message": str(exc) or "Model test request failed."},
        ) from exc

    result = LlmConnectionTestResponse(
        provider_protocol=config.provider_protocol,
        base_url=config.base_url,
        model=config.model,
        wire_api=config.wire_api,
        ok=bool(reply.strip()),
        reply=reply.strip(),
        latency_ms=int((perf_counter() - started) * 1000),
    )
    return success_response(result.model_dump(mode="json"))


@router.post("/search-proxy")
def proxy_search_request(payload: SearchProxyRequest, current_user: User = Depends(get_current_user)):
    config = _resolve_search_proxy_config(payload, current_user)
    gateway = ConfiguredSearchGateway(config)
    try:
        available_tools = gateway.available_tools()
        operation, arguments = _pick_search_operation(config, available_tools, payload.query)
        result = gateway.call_operation(operation, arguments)
    except SearchServiceGatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "search_proxy_upstream_failed", "message": str(exc)},
        ) from exc

    return success_response(
        {
            "provider": config.provider,
            "transport": config.transport,
            "base_url": config.base_url,
            "available_tools": sorted(available_tools),
            "operation": operation,
            "arguments": arguments,
            "result": result,
            "hits": _summarize_search_hits(result),
        }
    )


@router.post("/search-images-proxy")
def proxy_search_images_request(payload: SearchImageProxyRequest, current_user: User = Depends(get_current_user)):
    config = _resolve_search_proxy_config(payload, current_user)
    gateway = ConfiguredSearchGateway(config)
    try:
        available_tools = gateway.available_tools()
        operation, strategy = _pick_image_operation(config, available_tools, payload.preferred_tool)
        arguments = _build_image_operation_arguments(operation, payload.query)
        if config.provider == "tavily" and operation == "search":
            arguments["include_images"] = True
            arguments["include_image_descriptions"] = True
            arguments["include_domains"] = config.image_include_domains
        result = gateway.call_operation(operation, arguments)
        hits = _summarize_search_hits(result)
        image_urls = _extract_image_urls(result)
        fetch_payloads: list[dict[str, Any]] = []

        fetch_tool = "web_fetch" if "web_fetch" in available_tools else "contents" if "contents" in available_tools else None
        if fetch_tool and hits and len(image_urls) < 6:
            top_n = max(1, min(int(payload.fetch_top_n or 3), 5))
            for hit in hits[:top_n]:
                try:
                    if fetch_tool == "web_fetch":
                        fetched = gateway.call_operation(fetch_tool, {"url": hit["url"]})
                    else:
                        fetched = gateway.call_operation(fetch_tool, {"urls": [hit["url"]], "include_text": True, "include_html": True})
                except SearchServiceGatewayError:
                    continue
                fetch_payloads.append({"url": hit["url"], "payload": fetched})
                image_urls.extend(_extract_image_urls(fetched))
    except SearchServiceGatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "search_images_proxy_upstream_failed", "message": str(exc)},
        ) from exc

    deduped_images: list[str] = []
    seen: set[str] = set()
    for url in image_urls:
        key = url.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped_images.append(url)

    return success_response(
        {
            "provider": config.provider,
            "transport": config.transport,
            "base_url": config.base_url,
            "available_tools": sorted(available_tools),
            "operation": operation,
            "strategy": strategy,
            "arguments": arguments,
            "result": result,
            "hits": hits,
            "image_urls": deduped_images[:12],
            "fetch_payloads": fetch_payloads,
        }
    )


@router.post("/tavily-images-proxy")
def proxy_tavily_images_request(payload: TavilyImagesProxyRequest, current_user: User = Depends(get_current_user)):
    api_key = str(payload.api_key or "").strip()
    saved_search_provider = normalize_search_service_provider(getattr(current_user, "search_service_provider", None), default="groksearch")
    if not api_key and saved_search_provider == "tavily":
        api_key = str(getattr(current_user, "search_service_api_key", None) or "").strip()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "tavily_api_key_required", "message": "Provide a Tavily API key before testing image search."},
        )

    query = str(payload.query or "").strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "tavily_query_required", "message": "Provide a query before testing Tavily image search."},
        )

    endpoint = _resolve_tavily_endpoint(payload)
    include_domains = _resolve_tavily_image_include_domains()
    upstream_payload = {
        "query": query,
        "search_depth": str(payload.search_depth or "basic").strip() or "basic",
        "max_results": max(1, min(int(payload.max_results or 8), 20)),
        "include_images": True,
        "include_image_descriptions": bool(payload.include_image_descriptions),
    }
    if include_domains:
        upstream_payload["include_domains"] = include_domains
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    raw_payloads: list[tuple[str | None, dict[str, Any], dict[str, Any]]] = []
    try:
        with httpx.Client(timeout=httpx.Timeout(connect=20.0, read=120.0, write=60.0, pool=60.0), follow_redirects=True) as client:
            domain_batch = include_domains or [None]
            for domain in domain_batch:
                request_payload = dict(upstream_payload)
                if domain is not None:
                    request_payload["include_domains"] = [domain]
                response = client.post(endpoint, headers=headers, json=request_payload)
                raw = response.json()
                raw_payloads.append((domain, raw if isinstance(raw, dict) else {"data": raw}, request_payload))
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={"code": "tavily_timeout", "message": str(exc) or "Tavily request timed out"},
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "tavily_request_failed", "message": str(exc) or "Tavily request failed"},
        ) from exc

    top_image_items: list[Any] = []
    top_level_images_total = 0
    image_candidates: list[dict[str, Any]] = []
    image_candidates_total = 0
    image_candidates_by_domain: dict[str, int] = {}
    seen_image_urls: set[str] = set()
    domain_results: list[dict[str, Any]] = []
    per_source_limit = DEFAULT_IMAGE_PER_DOMAIN_LIMIT if include_domains else _TAVILY_IMAGE_RESPONSE_LIMIT

    def add_image_candidate(candidate: dict[str, Any]) -> None:
        nonlocal image_candidates_total
        image_url = str(candidate.get("url") or "").strip()
        if not image_url:
            return
        key = image_url.casefold()
        if key in seen_image_urls:
            return
        seen_image_urls.add(key)
        image_candidates_total += 1
        domain_key = str(candidate.get("source_domain") or "all").strip() or "all"
        current_domain_count = image_candidates_by_domain.get(domain_key, 0)
        if current_domain_count < per_source_limit:
            image_candidates.append({**candidate, "url": image_url})
            image_candidates_by_domain[domain_key] = current_domain_count + 1

    result_images: list[dict[str, Any]] = []
    result_images_total = 0
    result_images_by_domain: dict[str, int] = {}
    raw_result: dict[str, Any]

    for domain, raw, _request_payload in raw_payloads:
        domain_key = domain or "all"
        top_images = raw.get("images")
        top_image_items_raw = top_images if isinstance(top_images, list) else []
        top_level_images_total += len(top_image_items_raw)
        top_level_returned_for_domain = 0
        for image in top_image_items_raw:
            if top_level_returned_for_domain < per_source_limit:
                if isinstance(image, dict):
                    top_image = dict(image)
                    top_image["source_domain"] = domain
                    top_image_items.append(top_image)
                    image_url = str(image.get("url") or "").strip()
                    image_title = str(image.get("title") or "").strip() or None
                    image_description = str(image.get("description") or "").strip() or None
                else:
                    image_url = str(image or "").strip()
                    top_image_items.append({"url": image_url, "source_domain": domain})
                    image_title = None
                    image_description = None
                top_level_returned_for_domain += 1
            else:
                if isinstance(image, dict):
                    image_url = str(image.get("url") or "").strip()
                    image_title = str(image.get("title") or "").strip() or None
                    image_description = str(image.get("description") or "").strip() or None
                else:
                    image_url = str(image or "").strip()
                    image_title = None
                    image_description = None
            add_image_candidate(
                {
                    "source": "top_level",
                    "source_domain": domain,
                    "url": image_url,
                    "title": image_title,
                    "description": image_description,
                    "result_title": None,
                    "result_url": None,
                }
            )

        results = raw.get("results")
        result_items = results if isinstance(results, list) else []
        result_returned_for_domain = 0
        for item in result_items:
            if not isinstance(item, dict):
                continue
            item_images = item.get("images")
            if not isinstance(item_images, list):
                continue
            for image in item_images:
                if not isinstance(image, dict):
                    continue
                image_url = str(image.get("url") or "").strip()
                if image_url:
                    result_images_total += 1
                    current_domain_count = result_images_by_domain.get(domain_key, 0)
                    if current_domain_count < per_source_limit:
                        result_images.append(
                            {
                                "result_title": str(item.get("title") or "").strip(),
                                "result_url": str(item.get("url") or "").strip(),
                                "source_domain": domain,
                                "url": image_url,
                                "description": str(image.get("description") or "").strip() or None,
                            }
                        )
                        result_images_by_domain[domain_key] = current_domain_count + 1
                        result_returned_for_domain += 1
                add_image_candidate(
                    {
                        "source": "result",
                        "source_domain": domain,
                        "url": image_url,
                        "title": None,
                        "description": str(image.get("description") or "").strip() or None,
                        "result_title": str(item.get("title") or "").strip() or None,
                        "result_url": str(item.get("url") or "").strip() or None,
                    }
                )

        domain_results.append(
            {
                "domain": domain,
                "images_total_count": len(top_image_items_raw),
                "images_returned_count": top_level_returned_for_domain,
                "images_truncated": len(top_image_items_raw) > top_level_returned_for_domain,
                "result_images_returned_count": result_returned_for_domain,
                "results_count": len(result_items),
                "response_time": raw.get("response_time"),
                "request_id": raw.get("request_id"),
            }
        )

    if len(raw_payloads) == 1:
        raw_result = _limit_tavily_raw_result_images(raw_payloads[0][1], DEFAULT_IMAGE_PER_DOMAIN_LIMIT if include_domains else _TAVILY_IMAGE_RESPONSE_LIMIT)
    else:
        raw_result = {
            "request_mode": "per_domain",
            "domains": include_domains,
            "domain_results": [
                {
                    "domain": domain,
                    "request": request_payload,
                    "result": _limit_tavily_raw_result_images(raw, DEFAULT_IMAGE_PER_DOMAIN_LIMIT),
                }
                for domain, raw, request_payload in raw_payloads
            ],
        }

    return success_response(
        {
            "provider": "tavily",
            "base_url": endpoint,
            "request": upstream_payload,
            "request_mode": "per_domain" if include_domains else "single",
            "domain_results": domain_results,
            "raw_result": raw_result,
            "image_candidates": image_candidates,
            "image_candidates_total": image_candidates_total,
            "image_candidates_truncated": image_candidates_total > len(image_candidates),
            "top_level_images": top_image_items,
            "top_level_images_total": top_level_images_total,
            "top_level_images_truncated": top_level_images_total > len(top_image_items),
            "result_images": result_images,
            "result_images_total": result_images_total,
            "result_images_truncated": result_images_total > len(result_images),
        }
    )


@router.post("/xhs-images-proxy")
def proxy_xhs_images_request(payload: XhsImagesProxyRequest, current_user: User = Depends(get_current_user)):
    config = XhsCrawlerConfig.from_env()
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "xhs_crawler_unavailable", "message": "XHS browser node is not configured."},
        )

    destination = str(payload.destination or "").strip()
    queries = _normalize_probe_queries(payload.queries)
    if not destination:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "xhs_destination_required", "message": "Provide a destination before testing Xiaohongshu images."},
        )
    if not queries:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "xhs_queries_required", "message": "Provide at least one Xiaohongshu query before testing images."},
        )

    search_state = load_xhs_search_state(current_user.id)
    if not search_state.session_payload:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "xhs_binding_required",
                "message": search_state.xhs_message or "Bind Xiaohongshu in Settings before testing XHS image scraping.",
            },
        )

    try:
        result = XhsCrawlerClient(config).search_posts_debug(
            user_id=current_user.id,
            session_payload=search_state.session_payload,
            destination=destination,
            queries=queries,
            limit_per_query=payload.limit_per_query,
        )
    except XhsCrawlerSessionExpiredError as exc:
        mark_xhs_session_expired(current_user.id, str(exc))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "xhs_session_expired", "message": str(exc) or "XHS session expired. Rebind and try again."},
        ) from exc
    except XhsCrawlerClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "xhs_debug_proxy_failed", "message": str(exc)},
        ) from exc

    mark_xhs_session_available(current_user.id)
    return success_response(
        {
            "base_url": config.base_url,
            "destination": destination,
            "queries": queries,
            "limit_per_query": payload.limit_per_query,
            **result,
        }
    )
