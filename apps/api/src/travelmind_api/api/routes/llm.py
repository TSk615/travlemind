from __future__ import annotations

import json
import re
from collections.abc import Iterator
from time import perf_counter
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from travelmind_api.api.schemas.common import success_response
from travelmind_api.api.schemas.llm import LlmConnectionTestRequest, LlmConnectionTestResponse, LlmModelsRequest, LlmProxyRequest
from travelmind_api.core.deps import get_current_user
from travelmind_api.db.models import User
from travelmind_api.services.llm import LlmConfig, OpenAICompatibleClient
from travelmind_api.services.llm.config import default_base_url_for_protocol, normalize_provider_protocol, normalize_wire_api
from travelmind_api.services.llm.models import fetch_llm_models
from travelmind_api.services.search_connector import (
    ConfiguredSearchGateway,
    SearchServiceConfig,
    SearchServiceGatewayError,
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
    }
    config = LlmConfig.from_mapping(merged)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "llm_proxy_not_configured", "message": "Configure base_url, api_key, model, and API format before using the relay."},
        )
    return config


def _resolve_connection_test_config(payload: LlmConnectionTestRequest, user: User) -> LlmConfig:
    provider_protocol = normalize_provider_protocol(payload.provider_protocol or getattr(user, "llm_provider_protocol", None))
    config = LlmConfig.from_mapping(
        {
            "provider_protocol": provider_protocol,
            "base_url": payload.base_url or getattr(user, "llm_base_url", None) or default_base_url_for_protocol(provider_protocol),
            "api_key": payload.api_key or getattr(user, "llm_api_key", None),
            "model": payload.model or getattr(user, "llm_model", None),
            "wire_api": payload.wire_api or getattr(user, "llm_wire_api", None),
            "timeout_seconds": payload.timeout_seconds or 30.0,
        }
    )
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "llm_test_not_configured", "message": "Configure base_url, api_key, model, and API format before testing the model connection."},
        )
    return config


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
    return config


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
    base = str(payload.base_url or "https://api.tavily.com/search").strip().rstrip("/")
    if base.endswith("/search"):
        return base
    return f"{base}/search"


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
    provider_protocol = normalize_provider_protocol(payload.provider_protocol or getattr(current_user, "llm_provider_protocol", None))
    api_key = str(payload.api_key or getattr(current_user, "llm_api_key", None) or "").strip()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "llm_models_api_key_required", "message": "Provide or save an API key before fetching models."},
        )
    base_url = str(payload.base_url or getattr(current_user, "llm_base_url", None) or default_base_url_for_protocol(provider_protocol)).strip().rstrip("/")
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
    config = _resolve_connection_test_config(payload, current_user)
    started = perf_counter()
    try:
        reply = OpenAICompatibleClient(config).create_chat_completion(
            messages=[{"role": "user", "content": "Reply with exactly: ok"}],
            temperature=0,
            max_tokens=16,
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
    api_key = str(payload.api_key or "").strip() or str(getattr(current_user, "search_service_api_key", None) or "").strip()
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
    upstream_payload = {
        "query": query,
        "search_depth": str(payload.search_depth or "basic").strip() or "basic",
        "max_results": max(1, min(int(payload.max_results or 8), 20)),
        "include_images": True,
        "include_image_descriptions": bool(payload.include_image_descriptions),
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        with httpx.Client(timeout=httpx.Timeout(connect=20.0, read=120.0, write=60.0, pool=60.0), follow_redirects=True) as client:
            response = client.post(endpoint, headers=headers, json=upstream_payload)
            raw = response.json()
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

    top_images = raw.get("images")
    top_image_items = top_images if isinstance(top_images, list) else []
    result_images: list[dict[str, Any]] = []
    for item in raw.get("results") or []:
        if not isinstance(item, dict):
            continue
        item_images = item.get("images")
        if not isinstance(item_images, list):
            continue
        for image in item_images:
            if isinstance(image, dict):
                result_images.append(
                    {
                        "result_title": str(item.get("title") or "").strip(),
                        "result_url": str(item.get("url") or "").strip(),
                        "url": str(image.get("url") or "").strip(),
                        "description": str(image.get("description") or "").strip() or None,
                    }
                )

    return success_response(
        {
            "provider": "tavily",
            "base_url": endpoint,
            "request": upstream_payload,
            "raw_result": raw,
            "top_level_images": top_image_items,
            "result_images": [item for item in result_images if item["url"]],
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
