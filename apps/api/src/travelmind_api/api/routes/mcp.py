from __future__ import annotations

import logging
import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from travelmind_api.core.env import get_env

_LOGGER = logging.getLogger(__name__)
from travelmind_api.services.exa_pool import ExaPoolClient, ExaPoolConfig

router = APIRouter(prefix="/mcp", tags=["mcp"])
_SERVER_INFO = {"name": "travelmind-exa-pool-mcp", "version": "0.1.0"}

_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "search",
        "description": "Search the web for destination, attraction, weather, or hotel context.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "num_results": {"type": "integer", "description": "Maximum number of results", "default": 10},
                "search_type": {"type": "string", "description": "Search mode", "default": "auto"},
                "include_text": {"type": "boolean", "description": "Whether to include source text snippets", "default": False},
            },
            "required": ["query"],
        },
    },
    {
        "name": "contents",
        "description": "Fetch page contents for one or more URLs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "urls": {"type": "array", "items": {"type": "string"}, "description": "List of URLs"},
                "include_text": {"type": "boolean", "description": "Return extracted text", "default": True},
                "include_html": {"type": "boolean", "description": "Return html content", "default": False},
            },
            "required": ["urls"],
        },
    },
    {
        "name": "findSimilar",
        "description": "Find pages similar to a given URL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Reference URL"},
                "num_results": {"type": "integer", "description": "Maximum number of similar results", "default": 10},
                "include_text": {"type": "boolean", "description": "Whether to include source text snippets", "default": False},
            },
            "required": ["url"],
        },
    },
    {
        "name": "answer",
        "description": "Answer a focused question using Exa answer endpoint.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Question to answer"},
                "include_text": {"type": "boolean", "description": "Whether to include support text", "default": False},
            },
            "required": ["query"],
        },
    },
    {
        "name": "research",
        "description": "Launch a research task and optionally wait for completion.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "instructions": {"type": "string", "description": "Research instructions"},
                "model": {"type": "string", "description": "Research model", "default": "exa-research"},
                "wait_for_completion": {"type": "boolean", "description": "Whether to poll until completion", "default": True},
                "poll_interval_seconds": {"type": "number", "description": "Polling interval in seconds", "default": 2.0},
                "max_wait_seconds": {"type": "number", "description": "Maximum wait time in seconds", "default": 45.0},
            },
            "required": ["instructions"],
        },
    },
]


@router.get("")
@router.get("/")
def mcp_info():
    return PlainTextResponse("TravelMind Exa Pool MCP endpoint")


@router.post("")
@router.post("/")
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

    exa_config = ExaPoolConfig.from_env()
    if exa_config is None:
        return JSONResponse(_rpc_error(request_id, -32000, "Exa Pool backend is not configured on this server"), status_code=503)

    client = ExaPoolClient(exa_config)

    try:
        if method == "initialize":
            print("[MCP] initialize")
            result = {
                "protocolVersion": str(params.get("protocolVersion") or "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": _SERVER_INFO,
            }
        elif method == "tools/list":
            print("[MCP] tools/list")
            result = {"tools": _TOOL_DEFINITIONS}
        elif method == "tools/call":
            print(f"[MCP] tools/call name={params.get('name')}")
            result = _call_tool(client, params)
        else:
            return JSONResponse(_rpc_error(request_id, -32601, f"Unsupported MCP method: {method}"), status_code=404)
    except Exception as exc:
        print(f"[MCP] method={method} failed params={json.dumps(params, ensure_ascii=False)}")
        return JSONResponse(_rpc_error(request_id, -32001, str(exc)), status_code=500)

    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})



def _call_tool(client: ExaPoolClient, params: dict[str, Any]) -> dict[str, Any]:
    name = str(params.get("name") or "").strip()
    arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    if not name:
        raise ValueError("tools/call requires a non-empty tool name")

    if name == "search":
        result = client.search(
            query=str(arguments.get("query") or "").strip(),
            num_results=int(arguments.get("num_results", 10)),
            search_type=str(arguments.get("search_type") or "auto"),
            include_text=bool(arguments.get("include_text", False)),
        )
    elif name == "contents":
        urls = arguments.get("urls")
        if not isinstance(urls, list) or not urls:
            raise ValueError("contents requires a non-empty urls list")
        result = client.contents(
            urls=[str(item).strip() for item in urls if str(item).strip()],
            include_text=bool(arguments.get("include_text", True)),
            include_html=bool(arguments.get("include_html", False)),
        )
    elif name == "findSimilar":
        result = client.find_similar(
            url=str(arguments.get("url") or "").strip(),
            num_results=int(arguments.get("num_results", 10)),
            include_text=bool(arguments.get("include_text", False)),
        )
    elif name == "answer":
        result = client.answer(
            query=str(arguments.get("query") or "").strip(),
            include_text=bool(arguments.get("include_text", False)),
        )
    elif name == "research":
        result = client.research(
            instructions=str(arguments.get("instructions") or "").strip(),
            model=str(arguments.get("model") or "exa-research"),
            wait_for_completion=bool(arguments.get("wait_for_completion", True)),
            poll_interval_seconds=float(arguments.get("poll_interval_seconds", 2.0)),
            max_wait_seconds=float(arguments.get("max_wait_seconds", 45.0)),
        )
    else:
        raise ValueError(f"Unsupported tool: {name}")

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(result, ensure_ascii=False, indent=2),
            }
        ],
        "isError": False,
    }



def _authenticate_request(request: Request) -> JSONResponse | None:
    expected = (get_env("TRAVELMIND_MCP_SERVER_API_KEY") or "").strip()
    if not expected:
        return JSONResponse(_rpc_error(None, 401, "MCP server API key is not configured"), status_code=503)

    header = request.headers.get("Authorization") or ""
    query_key = request.query_params.get("mcpApiKey") or request.query_params.get("apiKey")
    token = None
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
    elif query_key:
        token = str(query_key).strip()

    if token != expected:
        return JSONResponse(_rpc_error(None, 401, "Invalid Bearer token for MCP server"), status_code=401)
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
