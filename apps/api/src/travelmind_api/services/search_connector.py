from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from travelmind_api.core.env import get_env
from travelmind_api.services.mcp import McpClientConfig, McpHttpClient

SearchServiceProvider = Literal["groksearch", "tavily"]
SearchServiceTransport = Literal["mcp", "api"]


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


class SearchServiceConfig(BaseModel):
    provider: SearchServiceProvider = "groksearch"
    transport: SearchServiceTransport = "mcp"
    base_url: str
    api_key: str
    timeout_seconds: float = Field(default=30.0, gt=0)

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
    return search_service_config_from_user(user) or SearchServiceConfig.from_env()


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
            self._available_tools = {"search"}
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
            if name not in {"search", "answer"}:
                raise SearchServiceGatewayError(f"Tavily API transport does not support operation {name}")
            query = str(arguments.get("query") or arguments.get("objective") or "").strip()
            num_results = int(arguments.get("num_results", arguments.get("numResults", 10)))
            include_images = bool(arguments.get("include_images", False))
            include_image_descriptions = bool(arguments.get("include_image_descriptions", False))
            return self._call_tavily_search(
                query=query,
                max_results=num_results,
                include_images=include_images,
                include_image_descriptions=include_image_descriptions,
            )
        raise SearchServiceGatewayError("GrokSearch currently only supports MCP transport")

    def _call_tavily_search(
        self,
        *,
        query: str,
        max_results: int,
        include_images: bool,
        include_image_descriptions: bool,
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
                response = client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()
                parsed = response.json()
        except httpx.HTTPError as exc:
            raise SearchServiceGatewayError(str(exc)) from exc
        return parsed if isinstance(parsed, dict) else {"data": parsed}

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
