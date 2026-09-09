from __future__ import annotations

import anyio
import inspect
import json
import logging
import os
import shlex
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass
from collections.abc import Awaitable
from pathlib import Path
from typing import Any, Protocol
import sys

from .env import get_env, load_into_process_env

_LOGGER = logging.getLogger(__name__)


class GrokSearchRunnerError(RuntimeError):
    pass


class GrokSearchRunner(Protocol):
    def initialize(self, params: dict[str, Any]) -> dict[str, Any] | Awaitable[dict[str, Any]]:
        ...

    def list_tools(self) -> list[dict[str, Any]] | Awaitable[list[dict[str, Any]]]:
        ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any] | Awaitable[dict[str, Any]]:
        ...

    def close(self) -> None:
        ...


@dataclass(frozen=True)
class StdioRunnerConfig:
    command: str
    protocol_version: str = "2024-11-05"

    @classmethod
    def from_env(cls) -> StdioRunnerConfig:
        command = (get_env("TRAVELMIND_GROKSEARCH_COMMAND") or "grok-search").strip()
        return cls(command=command)


class InProcessGrokSearchRunner:
    def __init__(self) -> None:
        load_into_process_env(
            "GUDA_BASE_URL",
            "GUDA_API_KEY",
            "GROK_API_URL",
            "GROK_API_KEY",
            "GROK_MODEL",
            "GROK_WIRE_API",
            "GROK_DEBUG",
            "GROK_LOG_LEVEL",
            "GROK_LOG_DIR",
            "TAVILY_ENABLED",
            "TAVILY_API_URL",
            "TAVILY_API_KEY",
            "FIRECRAWL_API_URL",
            "FIRECRAWL_API_KEY",
        )
        try:
            import grok_search.server as server_module
        except Exception as exc:  # pragma: no cover - import/runtime path
            raise GrokSearchRunnerError(f"Unable to import upstream GrokSearch package: {exc}") from exc
        wire_api = (get_env("GROK_WIRE_API") or "chat_completions").strip().lower()
        if wire_api in {"response", "responses"}:
            from .responses_provider import install_responses_provider

            install_responses_provider(server_module)
        self._server_module = server_module
        self._initialized_result: dict[str, Any] | None = None

    def initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        if self._initialized_result is not None:
            return self._initialized_result
        protocol_version = str(params.get("protocolVersion") or "2024-11-05")
        self._initialized_result = {
            "protocolVersion": protocol_version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "grok-search", "version": "0.1.0"},
        }
        return self._initialized_result

    async def list_tools(self) -> list[dict[str, Any]]:
        try:
            tools = await self._server_module.mcp.list_tools()
            results: list[dict[str, Any]] = []
            for tool in tools:
                tool_name = str(getattr(tool, "name", "") or "").strip()
                if not tool_name:
                    continue
                results.append(
                    {
                        "name": tool_name,
                        "description": str(getattr(tool, "description", "") or ""),
                        "inputSchema": self._normalize_schema(getattr(tool, "parameters", None)),
                    }
                )
            return results
        except Exception as exc:
            raise GrokSearchRunnerError(f"Unable to list upstream GrokSearch tools: {exc}") from exc

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            module_callable = getattr(self._server_module, name, None)
            if callable(module_callable):
                result = await self._invoke_module_tool(module_callable, arguments or {})
                return {"content": self._normalize_direct_result(result), "isError": False}

            tool_result = await self._server_module.mcp.call_tool(name, arguments or {})
            return {"content": self._normalize_tool_result(tool_result), "isError": False}
        except Exception as exc:
            raise GrokSearchRunnerError(f"Unable to call upstream GrokSearch tool '{name}': {exc}") from exc

    def close(self) -> None:
        return None

    def _normalize_schema(self, payload: Any) -> dict[str, Any]:
        if hasattr(payload, "model_dump"):
            dumped = payload.model_dump(mode="json")
            if isinstance(dumped, dict):
                return dumped
        if isinstance(payload, dict):
            return payload
        return {"type": "object", "properties": {}}

    async def _invoke_module_tool(self, fn: Any, arguments: dict[str, Any]) -> Any:
        signature = inspect.signature(fn)
        kwargs: dict[str, Any] = {}
        for parameter_name, parameter in signature.parameters.items():
            if parameter_name == "ctx":
                kwargs["ctx"] = None
                continue
            if parameter.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
                continue
            if parameter_name in arguments:
                kwargs[parameter_name] = arguments[parameter_name]
        result = fn(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    def _normalize_tool_result(self, tool_result: Any) -> list[dict[str, Any]]:
        content_items = tool_result.to_mcp_result()
        normalized_content: list[dict[str, Any]] = []
        for item in content_items:
            if hasattr(item, "model_dump"):
                normalized_content.append(item.model_dump(mode="json"))
            elif isinstance(item, dict):
                normalized_content.append(item)
            else:
                normalized_content.append({"type": "text", "text": str(item)})
        return normalized_content

    def _normalize_direct_result(self, result: Any) -> list[dict[str, Any]]:
        if result is None:
            return [{"type": "text", "text": ""}]
        if isinstance(result, (dict, list)):
            return [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]
        return [{"type": "text", "text": str(result)}]


class StdioMcpRunner:
    def __init__(self, config: StdioRunnerConfig) -> None:
        self._config = config
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._initialize_result: dict[str, Any] | None = None
        self._stderr_thread: threading.Thread | None = None

    def initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._initialize_result is not None:
                return self._initialize_result
            result = self._request_locked("initialize", params)
            self._initialize_result = result if isinstance(result, dict) else {}
            try:
                self._notify_locked("notifications/initialized", {})
            except Exception:
                pass
            return self._initialize_result

    def list_tools(self) -> list[dict[str, Any]]:
        self.initialize(
            {
                "protocolVersion": self._config.protocol_version,
                "clientInfo": {"name": "travelmind-groksearch-bridge", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            }
        )
        with self._lock:
            result = self._request_locked("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(tools, list):
            raise GrokSearchRunnerError("GrokSearch tools/list response did not contain a tools array")
        return [tool for tool in tools if isinstance(tool, dict)]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.initialize(
            {
                "protocolVersion": self._config.protocol_version,
                "clientInfo": {"name": "travelmind-groksearch-bridge", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            }
        )
        with self._lock:
            result = self._request_locked("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(result, dict):
            raise GrokSearchRunnerError("GrokSearch tools/call response did not contain an object result")
        return result

    def close(self) -> None:
        with self._lock:
            self._teardown_process_locked()

    def _request_locked(self, method: str, params: dict[str, Any]) -> Any:
        request_id = f"groksearch_{uuid.uuid4().hex}"
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        self._ensure_process_locked()
        assert self._process is not None
        assert self._process.stdin is not None
        assert self._process.stdout is not None
        try:
            _write_framed_message(self._process.stdin, payload)
            while True:
                message = _read_framed_message(self._process.stdout)
                if not isinstance(message, dict):
                    continue
                if message.get("id") != request_id:
                    continue
                if message.get("error"):
                    raise GrokSearchRunnerError(_format_rpc_error(message["error"]))
                return message.get("result")
        except BrokenPipeError as exc:
            self._teardown_process_locked()
            raise GrokSearchRunnerError(f"GrokSearch process pipe closed while calling {method}") from exc
        except GrokSearchRunnerError:
            raise
        except Exception as exc:
            self._teardown_process_locked()
            raise GrokSearchRunnerError(f"GrokSearch bridge failed during {method}: {exc}") from exc

    def _notify_locked(self, method: str, params: dict[str, Any]) -> None:
        self._ensure_process_locked()
        assert self._process is not None
        assert self._process.stdin is not None
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        _write_framed_message(self._process.stdin, payload)

    def _ensure_process_locked(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        self._teardown_process_locked()
        command = self._split_command(self._config.command)
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except Exception as exc:
            raise GrokSearchRunnerError(f"Unable to start GrokSearch command '{self._config.command}': {exc}") from exc
        self._stderr_thread = threading.Thread(target=self._drain_stderr, name="groksearch-stderr", daemon=True)
        self._stderr_thread.start()

    def _teardown_process_locked(self) -> None:
        process = self._process
        self._process = None
        self._initialize_result = None
        self._stderr_thread = None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except Exception:
            pass
        try:
            if process.stdout is not None:
                process.stdout.close()
        except Exception:
            pass
        try:
            if process.stderr is not None:
                process.stderr.close()
        except Exception:
            pass
        try:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for raw_line in iter(process.stderr.readline, b""):
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if line:
                _LOGGER.info("[groksearch] %s", line)

    def _split_command(self, command: str) -> list[str]:
        try:
            parts = shlex.split(command, posix=os.name != "nt")
        except ValueError as exc:
            raise GrokSearchRunnerError(f"Invalid GrokSearch command: {exc}") from exc
        if not parts:
            raise GrokSearchRunnerError("TRAVELMIND_GROKSEARCH_COMMAND must not be empty")
        resolved = _resolve_local_executable(parts[0])
        if resolved is not None:
            parts[0] = resolved
        return parts


def _write_framed_message(stream: Any, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    stream.write(header)
    stream.write(body)
    stream.flush()


def _read_framed_message(stream: Any) -> Any:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            raise GrokSearchRunnerError("GrokSearch process closed stdout before returning a response")
        if line in {b"\r\n", b"\n"}:
            break
        decoded = line.decode("ascii", errors="ignore").strip()
        if ":" not in decoded:
            continue
        key, value = decoded.split(":", 1)
        headers[key.strip().lower()] = value.strip()

    raw_length = headers.get("content-length")
    if not raw_length:
        raise GrokSearchRunnerError("GrokSearch response did not include a Content-Length header")
    try:
        content_length = int(raw_length)
    except ValueError as exc:
        raise GrokSearchRunnerError(f"Invalid Content-Length header: {raw_length}") from exc

    body = stream.read(content_length)
    if len(body) != content_length:
        raise GrokSearchRunnerError("GrokSearch response body was truncated")
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise GrokSearchRunnerError(f"GrokSearch response body was not valid JSON: {body[:200]!r}") from exc


def _format_rpc_error(error: Any) -> str:
    if isinstance(error, dict):
        code = error.get("code", "unknown")
        message = error.get("message") or error.get("data") or str(error)
        return f"MCP RPC error [{code}]: {message}"
    return f"MCP RPC error: {error}"


def _resolve_local_executable(candidate: str) -> str | None:
    normalized = str(candidate or "").strip()
    if not normalized:
        return None
    resolved = shutil.which(normalized)
    if resolved:
        return resolved
    script_dir = Path(sys.executable).resolve().parent
    for path in _candidate_executable_paths(script_dir, normalized):
        if path.exists():
            return str(path)
    return None


def _candidate_executable_paths(directory: Path, candidate: str) -> list[Path]:
    paths = [directory / candidate]
    if os.name == "nt" and not candidate.lower().endswith(".exe"):
        paths.append(directory / f"{candidate}.exe")
    return paths
