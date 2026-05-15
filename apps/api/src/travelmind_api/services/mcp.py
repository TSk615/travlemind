from __future__ import annotations

import logging
import json
import threading
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from travelmind_api.core.env import get_env

_LOGGER = logging.getLogger(__name__)
from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse


@dataclass(frozen=True)
class McpClientConfig:
    base_url: str
    api_key: str | None = None
    query_api_key_name: str | None = None
    timeout_seconds: float = 30.0
    protocol_version: str = "2024-11-05"

    @classmethod
    def from_env(cls) -> McpClientConfig | None:
        import os

        base_url = (get_env("TRAVELMIND_MCP_BASE_URL") or "").strip()
        api_key = (get_env("TRAVELMIND_MCP_API_KEY") or "").strip() or None
        timeout_raw = (get_env("TRAVELMIND_MCP_TIMEOUT_SECONDS") or "30").strip()
        if not base_url:
            public_api_url = (get_env("TRAVELMIND_PUBLIC_API_URL") or "http://127.0.0.1:8000").strip().rstrip("/")
            local_server_key = (get_env("TRAVELMIND_MCP_SERVER_API_KEY") or "").strip() or None
            exa_pool_base = (get_env("TRAVELMIND_EXA_POOL_BASE_URL") or "").strip()
            exa_pool_api_key = (get_env("TRAVELMIND_EXA_POOL_API_KEY") or "").strip()
            if public_api_url and local_server_key and exa_pool_base and exa_pool_api_key:
                base_url = f"{public_api_url}/mcp/"
                api_key = local_server_key
        if not base_url:
            return None
        parsed = urlparse(base_url)
        has_query_key = any(key == "exaApiKey" and value for key, value in parse_qsl(parsed.query, keep_blank_values=True))
        query_api_key_name = (get_env("TRAVELMIND_MCP_QUERY_API_KEY_NAME") or "").strip() or None
        if query_api_key_name is None and has_query_key:
            query_api_key_name = "exaApiKey"
        if api_key is None and not has_query_key:
            return None
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError:
            timeout_seconds = 30.0
        return cls(base_url=base_url, api_key=api_key, query_api_key_name=query_api_key_name, timeout_seconds=timeout_seconds)


class McpClientError(RuntimeError):
    pass


class McpHttpClient:
    def __init__(self, config: McpClientConfig, *, http_client: httpx.Client | None = None) -> None:
        self._config = config
        self._http_client = http_client
        self._initialized = False
        self._initialize_lock = threading.Lock()
        self._tools_cache: list[dict[str, Any]] | None = None

    def list_tools(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        self._ensure_initialized()
        if self._tools_cache is not None and not force_refresh:
            return self._tools_cache
        result = self._request("tools/list")
        tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(tools, list):
            raise McpClientError("MCP tools/list response did not contain a tools array")
        self._tools_cache = tools
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(result, dict):
            raise McpClientError("MCP tools/call response did not contain an object result")
        return result

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._initialize_lock:
            if self._initialized:
                return
            self._request(
                "initialize",
                {
                    "protocolVersion": self._config.protocol_version,
                    "clientInfo": {"name": "travelmind-ai", "version": "0.1.0"},
                    "capabilities": {"tools": {}},
                },
            )
            try:
                self._notify("notifications/initialized", {})
            except Exception:
                pass
            self._initialized = True

    def _request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": method,
            "params": params or {},
        }
        response = self._post(payload)
        body = self._decode_json(response)
        if not isinstance(body, dict):
            raise McpClientError(f"MCP method {method} returned a non-object response")
        if body.get("error"):
            raise McpClientError(self._format_rpc_error(body["error"]))
        return body.get("result")

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        response = self._post(payload)
        if response.content:
            body = self._decode_json(response)
            if isinstance(body, dict) and body.get("error"):
                raise McpClientError(self._format_rpc_error(body["error"]))

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"

        attempted_urls: list[str] = []
        last_response: httpx.Response | None = None
        last_error: Exception | None = None
        for candidate_url in self._candidate_urls():
            attempted_urls.append(candidate_url)
            try:
                print(f"[MCP-HTTP] POST {candidate_url} method={payload.get('method')}")
                if self._http_client is not None:
                    response = self._http_client.post(candidate_url, headers=headers, json=payload)
                else:
                    with httpx.Client(timeout=self._config.timeout_seconds, follow_redirects=True) as client:
                        response = client.post(candidate_url, headers=headers, json=payload)
                print(f"[MCP-HTTP] POST {candidate_url} -> {response.status_code}")
                if response.status_code in {404, 405, 421}:
                    last_response = response
                    continue
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                last_response = exc.response
                last_error = exc
                if exc.response.status_code in {404, 405, 421}:
                    continue
                raise
            except Exception as exc:
                last_error = exc
                raise
        if last_response is not None:
            raise McpClientError(
                f"MCP request failed for candidate URLs {attempted_urls}: "
                f"HTTP {last_response.status_code} {last_response.reason_phrase}. Body: {last_response.text[:400]}"
            )
        if last_error is not None:
            raise last_error
        raise McpClientError("MCP request failed before an HTTP response was returned")

    def _candidate_urls(self) -> list[str]:
        parsed = urlparse(self._config.base_url.strip())
        if not parsed.scheme or not parsed.netloc:
            return []

        query_items = parse_qsl(parsed.query, keep_blank_values=True)
        query_api_key_name = str(self._config.query_api_key_name or "").strip()
        if query_api_key_name and self._config.api_key and not any(key == query_api_key_name for key, _ in query_items):
            query_items.append((query_api_key_name, self._config.api_key))
        query = urlencode(query_items)

        raw_path = parsed.path or ""
        normalized_path = raw_path.rstrip("/")
        path_candidates: list[str]
        if normalized_path:
            path_candidates = [normalized_path, normalized_path + "/"]
        else:
            path_candidates = ["", "/"]

        candidates: list[str] = []
        for candidate_path in path_candidates:
            candidates.append(
                urlunparse(
                    (
                        parsed.scheme,
                        parsed.netloc,
                        candidate_path,
                        parsed.params,
                        query,
                        parsed.fragment,
                    )
                )
            )
        return list(dict.fromkeys(candidate for candidate in candidates if candidate))

    def _decode_json(self, response: httpx.Response) -> Any:
        content_type = (response.headers.get("content-type") or "").lower()
        raw_text = response.text
        if "text/event-stream" in content_type or raw_text.lstrip().startswith(("event:", "data:")):
            return self._decode_sse_json(raw_text)
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise McpClientError(f"MCP response was not valid JSON: {response.text[:400]}") from exc

    def _decode_sse_json(self, stream_text: str) -> Any:
        data_lines = [line[6:] for line in stream_text.splitlines() if line.startswith("data: ")]
        last_json_error: json.JSONDecodeError | None = None
        for line in reversed(data_lines):
            if not line or line == "[DONE]":
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError as exc:
                last_json_error = exc
                continue
        preview = stream_text[:400]
        if last_json_error is not None:
            raise McpClientError(f"MCP SSE response did not contain valid JSON data: {preview}") from last_json_error
        raise McpClientError(f"MCP SSE response did not contain any data payload: {preview}")

    def _next_request_id(self) -> str:
        return f"mcp_{uuid.uuid4().hex}"

    def _format_rpc_error(self, error: Any) -> str:
        if isinstance(error, dict):
            code = error.get("code", "unknown")
            message = error.get("message") or error.get("data") or str(error)
            return f"MCP RPC error [{code}]: {message}"
        return f"MCP RPC error: {error}"


class McpRemoteTool(Tool):
    def __init__(self, *, client: McpHttpClient, tool_definition: dict[str, Any]) -> None:
        self._client = client
        self._tool_definition = tool_definition
        super().__init__(
            name=str(tool_definition.get("name") or "mcp_tool"),
            description=str(tool_definition.get("description") or "Remote MCP tool"),
        )

    def get_parameters(self) -> list[ToolParameter]:
        schema = self._normalize_input_schema()
        properties = schema.get("properties") if isinstance(schema, dict) else None
        required = schema.get("required") if isinstance(schema, dict) else None
        required_names = set(required if isinstance(required, list) else [])
        if not isinstance(properties, dict):
            return []

        parameters: list[ToolParameter] = []
        for name, definition in properties.items():
            if not isinstance(definition, dict):
                continue
            raw_type = definition.get("type")
            if isinstance(raw_type, list):
                parameter_type = next((item for item in raw_type if item != "null"), "string")
            else:
                parameter_type = str(raw_type or "string")
            parameters.append(
                ToolParameter(
                    name=name,
                    type=parameter_type,
                    description=str(definition.get("description") or ""),
                    required=name in required_names,
                    default=definition.get("default"),
                )
            )
        return parameters

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        try:
            result = self._client.call_tool(self.name, parameters)
        except Exception as exc:
            return ToolResponse.error(code="MCP_CALL_FAILED", message=str(exc))

        content = result.get("content") if isinstance(result, dict) else None
        is_error = bool(result.get("isError")) if isinstance(result, dict) else False
        text_output = self._content_to_text(content)
        if is_error:
            return ToolResponse.error(code="MCP_TOOL_ERROR", message=text_output or f"Remote MCP tool {self.name} failed")
        return ToolResponse.success(
            text=text_output or f"MCP tool {self.name} completed successfully.",
            data=result if isinstance(result, dict) else {"result": result},
        )

    def _normalize_input_schema(self) -> dict[str, Any]:
        schema = self._tool_definition.get("inputSchema")
        if not isinstance(schema, dict):
            schema = self._tool_definition.get("input_schema")
        return schema if isinstance(schema, dict) else {"type": "object", "properties": {}}

    def _content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if not isinstance(content, list):
            return json.dumps(content, ensure_ascii=False) if content is not None else ""

        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                normalized = item.strip()
                if normalized:
                    parts.append(normalized)
                continue
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                normalized = item["text"].strip()
                if normalized:
                    parts.append(normalized)
                continue
            if item.get("type") in {"json", "resource"}:
                parts.append(json.dumps(item, ensure_ascii=False))
                continue
            if isinstance(item.get("text"), str):
                normalized = item["text"].strip()
                if normalized:
                    parts.append(normalized)
        return "\n".join(parts).strip()


def build_mcp_tools(
    *,
    config: McpClientConfig,
    allowed_tools: set[str] | None = None,
    http_client: httpx.Client | None = None,
) -> list[McpRemoteTool]:
    client = McpHttpClient(config, http_client=http_client)
    tools = client.list_tools()
    selected: list[McpRemoteTool] = []
    for definition in tools:
        if not isinstance(definition, dict):
            continue
        name = str(definition.get("name") or "").strip()
        if not name:
            continue
        if allowed_tools is not None and name not in allowed_tools:
            continue
        selected.append(McpRemoteTool(client=client, tool_definition=definition))
    return selected

