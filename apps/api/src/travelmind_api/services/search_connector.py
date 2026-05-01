from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import parse_qsl, urlparse

import httpx
from pydantic import BaseModel, Field

from travelmind_api.core.env import get_env
from travelmind_api.services.exa_pool import ExaPoolClient, ExaPoolConfig
from travelmind_api.services.mcp import McpClientConfig, McpHttpClient

SearchServiceProvider = Literal["exa", "groksearch", "tavily"]
SearchServiceTransport = Literal["mcp", "api"]


def normalize_search_service_provider(value: object | None, *, default: SearchServiceProvider = "exa") -> SearchServiceProvider:
    candidate = str(value or "").strip().lower()
    if candidate in {"exa", ""}:
        return "exa"
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
    provider: SearchServiceProvider = "exa"
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

        return cls(
            provider=normalize_search_service_provider(payload.get("provider")),
            transport=normalize_search_service_transport(payload.get("transport")),
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )

    @classmethod
    def from_env(cls) -> SearchServiceConfig | None:
        configured_provider = normalize_search_service_provider(get_env("TRAVELMIND_SEARCH_SERVICE_PROVIDER"), default="exa")
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

        mcp_base_url = (get_env("TRAVELMIND_MCP_BASE_URL") or "").strip()
        mcp_api_key = (get_env("TRAVELMIND_MCP_API_KEY") or "").strip() or None
        mcp_timeout_raw = (get_env("TRAVELMIND_MCP_TIMEOUT_SECONDS") or "30").strip()
        if not mcp_base_url:
            public_api_url = (get_env("TRAVELMIND_PUBLIC_API_URL") or "http://127.0.0.1:8000").strip().rstrip("/")
            local_server_key = (get_env("TRAVELMIND_MCP_SERVER_API_KEY") or "").strip() or None
            exa_pool_base = (get_env("TRAVELMIND_EXA_POOL_BASE_URL") or "").strip()
            exa_pool_api_key = (get_env("TRAVELMIND_EXA_POOL_API_KEY") or "").strip()
            if public_api_url and local_server_key and exa_pool_base and exa_pool_api_key:
                mcp_base_url = f"{public_api_url}/mcp/"
                mcp_api_key = local_server_key
        if mcp_base_url and mcp_api_key:
            try:
                mcp_timeout = float(mcp_timeout_raw)
            except ValueError:
                mcp_timeout = 30.0
            return cls(provider="exa", transport="mcp", base_url=mcp_base_url.rstrip("/"), api_key=mcp_api_key, timeout_seconds=mcp_timeout)

        api_base_url = (get_env("TRAVELMIND_EXA_POOL_BASE_URL") or "").strip().rstrip("/")
        api_key = (get_env("TRAVELMIND_EXA_POOL_API_KEY") or "").strip()
        api_timeout_raw = (get_env("TRAVELMIND_EXA_POOL_TIMEOUT_SECONDS") or "30").strip()
        if not api_base_url or not api_key:
            return None
        try:
            api_timeout = float(api_timeout_raw)
        except ValueError:
            api_timeout = 30.0
        return cls(provider="exa", transport="api", base_url=api_base_url, api_key=api_key, timeout_seconds=api_timeout)


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
                    query_api_key_name=self._resolve_query_api_key_name(config),
                    timeout_seconds=config.timeout_seconds,
                )
            )
            if config.transport == "mcp"
            else None
        )
        self._api_client = (
            ExaPoolClient(
                ExaPoolConfig(
                    base_url=config.base_url,
                    api_key=config.api_key,
                    timeout_seconds=config.timeout_seconds,
                )
            )
            if config.transport == "api" and config.provider == "exa"
            else None
        )
        self._available_tools: set[str] | None = None

    def _resolve_query_api_key_name(self, config: SearchServiceConfig) -> str | None:
        parsed = urlparse(config.base_url)
        query_keys = {key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
        if "exaApiKey" in query_keys:
            return "exaApiKey"
        if config.provider == "exa" and parsed.netloc.endswith("exa.ai"):
            return "exaApiKey"
        return None

    @property
    def config(self) -> SearchServiceConfig:
        return self._config

    def available_tools(self) -> set[str]:
        if self._available_tools is not None:
            return self._available_tools
        if self._config.transport == "api" and self._config.provider == "tavily":
            self._available_tools = {"search"}
            return self._available_tools
        if self._api_client is not None:
            self._available_tools = {"search", "answer", "research", "contents"}
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
        assert self._api_client is not None
        if self._config.provider == "groksearch":
            raise SearchServiceGatewayError("GrokSearch currently only supports MCP transport")
        if name in {"search", "web_search_exa", "deep_search_exa"}:
            query = str(arguments.get("query") or arguments.get("objective") or "").strip()
            num_results = int(arguments.get("num_results", arguments.get("numResults", 10)))
            search_type = str(arguments.get("search_type") or arguments.get("type") or "auto")
            include_text = bool(arguments.get("include_text", True))
            return self._api_client.search(query=query, num_results=num_results, search_type=search_type, include_text=include_text)
        if name == "answer":
            return self._api_client.answer(
                query=str(arguments.get("query") or "").strip(),
                include_text=bool(arguments.get("include_text", False)),
            )
        if name in {"contents", "crawling_exa"}:
            raw_urls = arguments.get("urls")
            urls = [str(item).strip() for item in raw_urls if str(item).strip()] if isinstance(raw_urls, list) else []
            return self._api_client.contents(
                urls=urls,
                include_text=bool(arguments.get("include_text", True) or arguments.get("text", True)),
                include_html=bool(arguments.get("include_html", False) or arguments.get("htmlContent", False)),
            )
        if name in {"research", "deep_researcher_start"}:
            return self._api_client.research(
                instructions=str(arguments.get("instructions") or "").strip(),
                model=str(arguments.get("model") or "exa-research"),
                wait_for_completion=bool(arguments.get("wait_for_completion", True)),
                poll_interval_seconds=float(arguments.get("poll_interval_seconds", 2.0)),
                max_wait_seconds=float(arguments.get("max_wait_seconds", 45.0)),
            )
        raise SearchServiceGatewayError(f"Configured API transport does not support operation {name}")

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

    def run_research_with_fallback(self, instructions: str) -> tuple[str, dict[str, Any]]:
        available_tools = self.available_tools()
        if "deep_researcher_start" in available_tools:
            start_result = self.call_operation(
                "deep_researcher_start",
                {"instructions": instructions, "model": "exa-research-fast"},
            )
            research_id = str(start_result.get("researchId") or start_result.get("id") or "").strip()
            latest_result = start_result
            if research_id and "deep_researcher_check" in available_tools:
                for attempt in range(3):
                    latest_result = self.call_operation("deep_researcher_check", {"researchId": research_id})
                    status = self.research_status(latest_result)
                    if status in {"completed", "complete", "done", "failed", "error"}:
                        break
                    if attempt < 2:
                        time.sleep(2.0)
            return (
                "deep_researcher_start",
                {
                    "tool_name": "deep_researcher_start",
                    "research_id": research_id,
                    "status": self.research_status(latest_result) or self.research_status(start_result),
                    "start": start_result,
                    "result": latest_result,
                },
            )

        if "research" in available_tools:
            result = self.call_operation(
                "research",
                {
                    "instructions": instructions,
                    "model": "exa-research",
                    "wait_for_completion": True,
                    "poll_interval_seconds": 2.0,
                    "max_wait_seconds": 30.0,
                },
            )
            return ("research", {"tool_name": "research", "status": self.research_status(result), "result": result})

        raise SearchServiceGatewayError("Configured search service does not expose a research operation")
