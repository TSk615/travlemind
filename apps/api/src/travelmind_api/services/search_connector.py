from __future__ import annotations

import json
import re
import ipaddress
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, field_validator

from travelmind_api.core.config import get_settings
from travelmind_api.core.env import get_env
from travelmind_api.core.upstream_urls import normalize_upstream_base_url
from travelmind_api.services.mcp import McpClientConfig, McpHttpClient

SearchServiceProvider = Literal["groksearch", "tavily"]
SearchServiceTransport = Literal["mcp", "api"]
DEFAULT_IMAGE_INCLUDE_DOMAINS = ("hk.trip.com", "pixabay.com", "pexels.com")
DEFAULT_IMAGE_PER_DOMAIN_LIMIT = 4


def is_public_source_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if parsed.scheme not in {"https", "http"} or parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
            return False
        if "." not in host or host.endswith((".test", ".local", ".localhost", ".internal")) or host == "localhost":
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False
_DOMAIN_TOKEN_SPLIT_PATTERN = re.compile(r"[\s,;\uFF0C\uFF1B]+")
_DOMAIN_PATTERN = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$", re.IGNORECASE)


def normalize_search_service_provider(value: object | None, *, default: SearchServiceProvider = "groksearch") -> SearchServiceProvider:
    candidate = str(value or "").strip().lower()
    if candidate == "":
        return default
    if candidate in {"groksearch", "grok-search", "grok_search", "grok"}:
        return "groksearch"
    if candidate in {"tavily"}:
        return "tavily"
    return default


def normalize_search_service_transport(value: object | None, *, default: SearchServiceTransport = "mcp") -> SearchServiceTransport:
    candidate = str(value or "").strip().lower()
    if candidate in {"api", "rest", "http"}:
        return "api"
    if candidate in {"mcp", ""}:
        return "mcp"
    return default


def normalize_domain_filter_values(
    value: object | None,
    *,
    default: list[str] | tuple[str, ...] | None = None,
    strict: bool = False,
) -> list[str]:
    if value is None:
        return list(default or [])

    if isinstance(value, str):
        raw_items = [item for item in _DOMAIN_TOKEN_SPLIT_PATTERN.split(value) if item.strip()]
    elif isinstance(value, (list, tuple, set)):
        raw_items = [str(item or "").strip() for item in value if str(item or "").strip()]
    else:
        raw_items = [str(value or "").strip()] if str(value or "").strip() else []

    normalized: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        candidate = raw_item.strip().strip("\"'")
        if not candidate:
            continue
        parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
        host = (parsed.hostname or "").strip().lower().rstrip(".")
        if host.startswith("www."):
            host = host[4:]
        if not host or not _DOMAIN_PATTERN.fullmatch(host):
            invalid.append(raw_item)
            continue
        if host in seen:
            continue
        seen.add(host)
        normalized.append(host)

    if strict and invalid:
        raise ValueError(f"Invalid image source domain values: {', '.join(invalid)}")
    return normalized[:20]


class SearchServiceConfig(BaseModel):
    provider: SearchServiceProvider = "groksearch"
    transport: SearchServiceTransport = "mcp"
    base_url: str
    api_key: str
    timeout_seconds: float = Field(default=30.0, gt=0)
    image_include_domains: list[str] = Field(default_factory=lambda: list(DEFAULT_IMAGE_INCLUDE_DOMAINS))

    @field_validator("image_include_domains", mode="before")
    @classmethod
    def _normalize_image_include_domains(cls, value: object) -> list[str]:
        return normalize_domain_filter_values(value, default=DEFAULT_IMAGE_INCLUDE_DOMAINS)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object] | None) -> SearchServiceConfig | None:
        if payload is None:
            return None

        base_url = str(payload.get("base_url") or "").strip().rstrip("/")
        api_key = str(payload.get("api_key") or "").strip()
        if not base_url or not api_key:
            return None

        timeout_raw = str(payload.get("timeout_seconds") or "30").strip()
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError:
            timeout_seconds = 30.0
        if timeout_seconds <= 0:
            timeout_seconds = 30.0
        raw_image_domains = payload.get("image_include_domains")
        if raw_image_domains is None:
            raw_image_domains = payload.get("image_search_include_domains")
        image_include_domains = normalize_domain_filter_values(raw_image_domains, default=DEFAULT_IMAGE_INCLUDE_DOMAINS)

        raw_provider = str(payload.get("provider") or "").strip().lower()
        if raw_provider and raw_provider not in {"groksearch", "grok-search", "grok_search", "grok", "tavily"}:
            return None
        raw_transport = str(payload.get("transport") or "").strip().lower()
        if raw_transport and raw_transport not in {"mcp", "api", "rest", "http"}:
            return None

        provider = normalize_search_service_provider(payload.get("provider"))
        transport = normalize_search_service_transport(payload.get("transport"))
        if provider == "groksearch" and transport != "mcp":
            return None
        if provider == "tavily" and transport != "api":
            return None

        return cls(
            provider=provider,
            transport=transport,
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            image_include_domains=image_include_domains,
        )

    @classmethod
    def from_env(cls) -> SearchServiceConfig | None:
        configured_provider = normalize_search_service_provider(get_env("TRAVELMIND_SEARCH_SERVICE_PROVIDER"), default="groksearch")
        configured_transport = normalize_search_service_transport(get_env("TRAVELMIND_SEARCH_SERVICE_TRANSPORT"), default="mcp")
        if configured_provider == "groksearch":
            grok_base_url = (
                (get_env("TRAVELMIND_GROKSEARCH_BRIDGE_BASE_URL") or "").strip()
                or (get_env("TRAVELMIND_MCP_BASE_URL") or "").strip()
            )
            grok_api_key = (
                (get_env("TRAVELMIND_GROKSEARCH_BRIDGE_API_KEY") or "").strip()
                or (get_env("TRAVELMIND_MCP_API_KEY") or "").strip()
            )
            grok_timeout_raw = (
                (get_env("TRAVELMIND_GROKSEARCH_BRIDGE_TIMEOUT_SECONDS") or "").strip()
                or (get_env("TRAVELMIND_MCP_TIMEOUT_SECONDS") or "30").strip()
            )
            if not grok_base_url or not grok_api_key or configured_transport != "mcp":
                return None
            try:
                grok_timeout = float(grok_timeout_raw)
            except ValueError:
                grok_timeout = 30.0
            return cls(
                provider="groksearch",
                transport="mcp",
                base_url=grok_base_url.rstrip("/"),
                api_key=grok_api_key,
                timeout_seconds=grok_timeout,
                image_include_domains=normalize_domain_filter_values(get_env("TRAVELMIND_IMAGE_SEARCH_INCLUDE_DOMAINS"), default=DEFAULT_IMAGE_INCLUDE_DOMAINS),
            )
        if configured_provider == "tavily":
            tavily_base_url = (
                get_env("TRAVELMIND_TAVILY_BASE_URL")
                or get_env("TAVILY_API_URL")
                or "https://api.tavily.com/search"
            ).strip()
            tavily_api_key = (
                get_env("TRAVELMIND_TAVILY_API_KEY")
                or get_env("TAVILY_API_KEY")
                or ""
            ).strip()
            tavily_timeout_raw = (
                get_env("TRAVELMIND_TAVILY_TIMEOUT_SECONDS")
                or "30"
            ).strip()
            tavily_image_include_domains = normalize_domain_filter_values(
                get_env("TRAVELMIND_TAVILY_IMAGE_INCLUDE_DOMAINS") or get_env("TRAVELMIND_IMAGE_SEARCH_INCLUDE_DOMAINS"),
                default=DEFAULT_IMAGE_INCLUDE_DOMAINS,
            )
            if not tavily_base_url or not tavily_api_key or configured_transport != "api":
                return None
            try:
                tavily_timeout = float(tavily_timeout_raw)
            except ValueError:
                tavily_timeout = 30.0
            return cls(
                provider="tavily",
                transport="api",
                base_url=tavily_base_url.rstrip("/"),
                api_key=tavily_api_key,
                timeout_seconds=tavily_timeout,
                image_include_domains=tavily_image_include_domains,
            )
        return None


def search_service_config_from_user(user: object | None) -> SearchServiceConfig | None:
    if user is None:
        return None
    return SearchServiceConfig.from_mapping(
        {
            "provider": getattr(user, "search_service_provider", None),
            "transport": getattr(user, "search_service_transport", None),
            "base_url": getattr(user, "search_service_base_url", None),
            "api_key": getattr(user, "search_service_api_key", None),
            "timeout_seconds": getattr(user, "search_service_timeout_seconds", None),
        }
    )


def resolve_search_service_config(user: object | None) -> SearchServiceConfig | None:
    config = search_service_config_from_user(user) or SearchServiceConfig.from_env()
    if config is None:
        return None
    normalized_base_url = normalize_upstream_base_url(config.base_url, get_settings())
    if normalized_base_url is None:
        return None
    return config.model_copy(update={"base_url": normalized_base_url})


class SearchServiceGatewayError(RuntimeError):
    pass


class ConfiguredSearchGateway:
    def __init__(self, config: SearchServiceConfig) -> None:
        self._config = config
        self._mcp_client = (
            McpHttpClient(
                McpClientConfig(
                    base_url=config.base_url,
                    api_key=config.api_key,
                    timeout_seconds=config.timeout_seconds,
                )
            )
            if config.transport == "mcp"
            else None
        )
        self._available_tools: set[str] | None = None

    @property
    def config(self) -> SearchServiceConfig:
        return self._config

    def available_tools(self) -> set[str]:
        if self._available_tools is not None:
            return self._available_tools
        if self._config.transport == "api" and self._config.provider == "tavily":
            self._available_tools = {"search", "extract"}
            return self._available_tools
        if self._mcp_client is None:
            self._available_tools = set()
            return self._available_tools
        try:
            tools = self._mcp_client.list_tools()
        except Exception as exc:  # pragma: no cover - network/runtime path
            raise SearchServiceGatewayError(f"Unable to list configured MCP tools: {exc}") from exc
        self._available_tools = {
            str(tool.get("name") or "").strip()
            for tool in tools
            if isinstance(tool, dict) and str(tool.get("name") or "").strip()
        }
        return self._available_tools

    def call_operation(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._config.transport == "api":
            return self._call_api_operation(name, arguments)
        if self._mcp_client is None:
            raise SearchServiceGatewayError("Search service client is not configured")
        return self._call_mcp_operation(name, arguments)

    def research_status(self, payload: dict[str, Any]) -> str:
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

    def _call_api_operation(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._config.provider == "tavily":
            if name == "extract":
                urls = [str(url) for url in arguments.get("urls", []) if is_public_source_url(str(url))][:8]
                if not urls:
                    return {"results": [], "failed_results": []}
                root = self._config.base_url.rstrip("/")
                if root.endswith("/search"):
                    root = root[:-7]
                with httpx.Client(timeout=self._config.timeout_seconds, follow_redirects=False) as client:
                    response = client.post(f"{root}/extract", headers={"Authorization": f"Bearer {self._config.api_key}"},
                                           json={"urls": urls, "include_images": bool(arguments.get("include_images", False)),
                                                 "extract_depth": "basic", "timeout": 10})
                    response.raise_for_status()
                    return response.json()
            if name not in {"search", "answer"}:
                raise SearchServiceGatewayError(f"Tavily API transport does not support operation {name}")
            query = str(arguments.get("query") or arguments.get("objective") or "").strip()
            num_results = int(arguments.get("num_results", arguments.get("numResults", 10)))
            include_images = bool(arguments.get("include_images", False))
            include_image_descriptions = bool(arguments.get("include_image_descriptions", False))
            include_domains = normalize_domain_filter_values(
                arguments.get("include_domains") if arguments.get("include_domains") is not None else self._config.image_include_domains,
                default=[],
            )
            return self._call_tavily_search(
                query=query,
                max_results=num_results,
                include_images=include_images,
                include_image_descriptions=include_image_descriptions,
                include_domains=include_domains,
                split_domains=bool(arguments.get("split_domains", True)),
            )
        raise SearchServiceGatewayError("GrokSearch currently only supports MCP transport")

    def _call_tavily_search(
        self,
        *,
        query: str,
        max_results: int,
        include_images: bool,
        include_image_descriptions: bool,
        include_domains: list[str],
        split_domains: bool = True,
    ) -> dict[str, Any]:
        endpoint = self._config.base_url if self._config.base_url.endswith("/search") else f"{self._config.base_url}/search"
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "query": query,
            "search_depth": "basic",
            "max_results": max(1, min(max_results, 20)),
            "include_images": include_images,
            "include_image_descriptions": include_image_descriptions,
        }
        try:
            with httpx.Client(timeout=self._config.timeout_seconds, follow_redirects=True) as client:
                if split_domains and include_images and len(include_domains) > 1:
                    domain_payloads: list[tuple[str, dict[str, Any]]] = []
                    for domain in include_domains:
                        domain_payload = {**payload, "include_domains": [domain]}
                        response = client.post(endpoint, headers=headers, json=domain_payload)
                        response.raise_for_status()
                        parsed = response.json()
                        domain_payloads.append((domain, parsed if isinstance(parsed, dict) else {"data": parsed}))
                    return self._merge_tavily_domain_payloads(domain_payloads)
                if include_images and include_domains:
                    payload["include_domains"] = include_domains
                response = client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()
                parsed = response.json()
        except httpx.HTTPError as exc:
            raise SearchServiceGatewayError(str(exc)) from exc
        return parsed if isinstance(parsed, dict) else {"data": parsed}

    def _merge_tavily_domain_payloads(self, domain_payloads: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
        merged: dict[str, Any] = {
            "request_mode": "per_domain",
            "domain_results": [],
            "results": [],
            "images": [],
        }
        seen_images: set[str] = set()
        total_image_count = 0

        for domain, payload in domain_payloads:
            images = payload.get("images")
            image_items = images if isinstance(images, list) else []
            returned_for_domain = 0
            for image in image_items:
                if returned_for_domain >= DEFAULT_IMAGE_PER_DOMAIN_LIMIT:
                    break
                if isinstance(image, dict):
                    image_url = str(image.get("url") or "").strip()
                    image_payload = dict(image)
                else:
                    image_url = str(image or "").strip()
                    image_payload = {"url": image_url}
                if not image_url:
                    continue
                key = image_url.casefold()
                if key in seen_images:
                    continue
                seen_images.add(key)
                image_payload["url"] = image_url
                image_payload["source_domain"] = domain
                merged["images"].append(image_payload)
                returned_for_domain += 1

            results = payload.get("results")
            result_items = results if isinstance(results, list) else []
            for result in result_items:
                if not isinstance(result, dict):
                    continue
                result_payload = dict(result)
                result_payload["source_domain"] = domain
                result_images = result_payload.get("images")
                if isinstance(result_images, list):
                    result_payload["images_total_count"] = len(result_images)
                    result_payload["images_truncated"] = len(result_images) > DEFAULT_IMAGE_PER_DOMAIN_LIMIT
                    result_payload["images"] = result_images[:DEFAULT_IMAGE_PER_DOMAIN_LIMIT]
                merged["results"].append(result_payload)

            total_image_count += len(image_items)
            merged["domain_results"].append(
                {
                    "domain": domain,
                    "images_total_count": len(image_items),
                    "images_returned_count": returned_for_domain,
                    "images_truncated": len(image_items) > returned_for_domain,
                    "results_count": len(result_items),
                    "response_time": payload.get("response_time"),
                    "request_id": payload.get("request_id"),
                }
            )

        merged["images_total_count"] = total_image_count
        merged["images_returned_count"] = len(merged["images"])
        merged["images_truncated"] = total_image_count > len(merged["images"])
        return merged

    def _call_mcp_operation(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert self._mcp_client is not None
        try:
            result = self._mcp_client.call_tool(name, arguments)
        except Exception as exc:  # pragma: no cover - network/runtime path
            raise SearchServiceGatewayError(str(exc)) from exc
        parsed = self._parse_mcp_result(result)
        if self._config.provider == "groksearch" and name == "web_search":
            return self._maybe_enrich_groksearch_search_payload(parsed)
        return parsed

    def _parse_mcp_result(self, result: dict[str, Any] | Any) -> dict[str, Any]:
        content = result.get("content") if isinstance(result, dict) else None
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    text = item["text"].strip()
                    if not text:
                        continue
                    try:
                        parsed = json.loads(text)
                    except json.JSONDecodeError:
                        return {"text": text}
                    if isinstance(parsed, dict):
                        return parsed
                    return {"data": parsed}
        return result if isinstance(result, dict) else {"result": result}

    def _maybe_enrich_groksearch_search_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("sources"):
            return payload
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        if not session_id:
            return payload
        if "get_sources" not in self.available_tools():
            return payload
        try:
            sources_payload = self._call_mcp_operation("get_sources", {"session_id": session_id})
        except Exception:
            return payload
        sources = sources_payload.get("sources")
        if isinstance(sources, list):
            payload = dict(payload)
            payload["sources"] = [item for item in sources if isinstance(item, dict)]
            payload["sources_count"] = payload.get("sources_count") or len(payload["sources"])
        return payload
