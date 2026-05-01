from __future__ import annotations

import inspect
import os
import threading
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from .env import get_env
from .service import GrokSearchRunner, GrokSearchRunnerError, InProcessGrokSearchRunner, StdioMcpRunner, StdioRunnerConfig

_SERVER_INFO = {"name": "travelmind-groksearch-bridge", "version": "0.1.0"}
_RUNNER: GrokSearchRunner | None = None
_RUNNER_LOCK = threading.Lock()


def create_app() -> FastAPI:
    app = FastAPI(title="TravelMind GrokSearch Bridge")

    @app.on_event("shutdown")
    def on_shutdown() -> None:
        close_runner()

    @app.get("/")
    def info():
        return PlainTextResponse("TravelMind GrokSearch MCP bridge")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/mcp")
    @app.post("/mcp/")
    async def mcp_endpoint(request: Request):
        auth_error = _authenticate_request(request)
        if auth_error is not None:
            return auth_error

        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(_rpc_error(None, -32700, "Invalid JSON payload"), status_code=400)

        if not isinstance(payload, dict):
            return JSONResponse(_rpc_error(None, -32600, "JSON-RPC request body must be an object"), status_code=400)

        method = str(payload.get("method") or "").strip()
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        request_id = payload.get("id")

        if not method:
            return JSONResponse(_rpc_error(request_id, -32600, "Missing MCP method"), status_code=400)
        if method == "notifications/initialized":
            return Response(status_code=202)

        try:
            runner = get_runner()
            if method == "initialize":
                result = await _resolve_runner_call(runner.initialize(params))
            elif method == "tools/list":
                result = {"tools": await _resolve_runner_call(runner.list_tools())}
            elif method == "tools/call":
                name = str(params.get("name") or "").strip()
                arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
                if not name:
                    return JSONResponse(_rpc_error(request_id, -32600, "tools/call requires a non-empty tool name"), status_code=400)
                result = await _resolve_runner_call(runner.call_tool(name, arguments))
            else:
                return JSONResponse(_rpc_error(request_id, -32601, f"Unsupported MCP method: {method}"), status_code=404)
        except GrokSearchRunnerError as exc:
            return JSONResponse(_rpc_error(request_id, -32001, str(exc)), status_code=500)
        except Exception as exc:
            return JSONResponse(_rpc_error(request_id, -32001, str(exc)), status_code=500)

        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})

    return app


def build_runner() -> GrokSearchRunner:
    mode = (get_env("TRAVELMIND_GROKSEARCH_RUNNER_MODE") or "inprocess").strip().lower()
    if mode in {"inprocess", "module", "python"}:
        return InProcessGrokSearchRunner()
    return StdioMcpRunner(StdioRunnerConfig.from_env())


def get_runner() -> GrokSearchRunner:
    global _RUNNER
    if _RUNNER is not None:
        return _RUNNER
    with _RUNNER_LOCK:
        if _RUNNER is None:
            _RUNNER = build_runner()
        return _RUNNER


def close_runner() -> None:
    global _RUNNER
    with _RUNNER_LOCK:
        runner = _RUNNER
        _RUNNER = None
    if runner is not None:
        runner.close()


def _authenticate_request(request: Request) -> JSONResponse | None:
    expected = (get_env("TRAVELMIND_GROKSEARCH_BRIDGE_API_KEY") or "").strip()
    if not expected:
        return JSONResponse(_rpc_error(None, 401, "GrokSearch bridge API key is not configured"), status_code=503)

    header = request.headers.get("Authorization") or ""
    query_key = request.query_params.get("mcpApiKey") or request.query_params.get("apiKey")
    token = None
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
    elif query_key:
        token = str(query_key).strip()

    if token != expected:
        return JSONResponse(_rpc_error(None, 401, "Invalid Bearer token for GrokSearch bridge"), status_code=401)
    return None


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


async def _resolve_runner_call(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


app = create_app()
