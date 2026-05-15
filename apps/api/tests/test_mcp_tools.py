import json

import httpx

from travelmind_api.services.mcp import McpClientConfig, McpHttpClient, build_mcp_tools



def test_mcp_http_client_lists_and_calls_tools():
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            {
                "authorization": request.headers.get("Authorization"),
                "payload": json.loads(request.content.decode("utf-8")),
            }
        )
        payload = calls[-1]["payload"]
        method = payload.get("method")
        if method == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload.get("id"), "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}})
        if method == "notifications/initialized":
            return httpx.Response(202, text="")
        if method == "tools/list":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "result": {
                        "tools": [
                            {
                                "name": "search",
                                "description": "Search the web",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "query": {"type": "string", "description": "Search query"},
                                        "numResults": {"type": "integer", "description": "Number of results", "default": 5},
                                    },
                                    "required": ["query"],
                                },
                            }
                        ]
                    },
                },
            )
        if method == "tools/call":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "result": {
                        "content": [
                            {"type": "text", "text": "Result A"},
                            {"type": "text", "text": "Result B"},
                        ]
                    },
                },
            )
        raise AssertionError(f"Unexpected MCP method: {method}")

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = McpHttpClient(McpClientConfig(base_url="https://mcp.example.test/mcp", api_key="mcp-key"), http_client=http_client)

    try:
        tools = client.list_tools()
        result = client.call_tool("search", {"query": "Kyoto temples"})
    finally:
        http_client.close()

    assert calls[0]["authorization"] == "Bearer mcp-key"
    assert tools[0]["name"] == "search"
    assert result["content"][0]["text"] == "Result A"
    assert any(call["payload"].get("method") == "initialize" for call in calls)
    assert any(call["payload"].get("method") == "tools/list" for call in calls)
    assert any(call["payload"].get("method") == "tools/call" for call in calls)



def test_build_mcp_tools_filters_allowed_remote_tools():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        method = payload.get("method")
        if method == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload.get("id"), "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}})
        if method == "notifications/initialized":
            return httpx.Response(202, text="")
        if method == "tools/list":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "result": {
                        "tools": [
                            {"name": "search", "description": "Search", "inputSchema": {"type": "object", "properties": {}}},
                            {"name": "research", "description": "Research", "inputSchema": {"type": "object", "properties": {}}},
                            {"name": "secretTool", "description": "Hidden", "inputSchema": {"type": "object", "properties": {}}},
                        ]
                    },
                },
            )
        raise AssertionError(f"Unexpected MCP method: {method}")

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    config = McpClientConfig(base_url="https://mcp.example.test/mcp", api_key="mcp-key")

    try:
        tools = build_mcp_tools(config=config, allowed_tools={"search", "research"}, http_client=http_client)
    finally:
        http_client.close()

    assert [tool.name for tool in tools] == ["search", "research"]
    assert tools[0].get_parameters() == []



def test_mcp_http_client_supports_query_param_auth_without_bearer_header():
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            {
                "url": str(request.url),
                "authorization": request.headers.get("Authorization"),
                "payload": json.loads(request.content.decode("utf-8")),
            }
        )
        payload = calls[-1]["payload"]
        method = payload.get("method")
        if method == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload.get("id"), "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}})
        if method == "notifications/initialized":
            return httpx.Response(202, text="")
        if method == "tools/list":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload.get("id"), "result": {"tools": []}})
        raise AssertionError(f"Unexpected MCP method: {method}")

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = McpHttpClient(McpClientConfig(base_url="https://exa.proxy.test?exaApiKey=query-key", api_key=None), http_client=http_client)

    try:
        client.list_tools(force_refresh=True)
    finally:
        http_client.close()

    assert calls[0]["authorization"] is None
    assert calls[0]["url"].startswith("https://exa.proxy.test")
    assert "exaApiKey=query-key" in calls[0]["url"]


def test_mcp_http_client_does_not_append_exa_query_key_for_generic_mcp():
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            {
                "url": str(request.url),
                "authorization": request.headers.get("Authorization"),
                "payload": json.loads(request.content.decode("utf-8")),
            }
        )
        payload = calls[-1]["payload"]
        method = payload.get("method")
        if method == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload.get("id"), "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}})
        if method == "notifications/initialized":
            return httpx.Response(202, text="")
        if method == "tools/list":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload.get("id"), "result": {"tools": []}})
        raise AssertionError(f"Unexpected MCP method: {method}")

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = McpHttpClient(McpClientConfig(base_url="https://bridge.example.test/mcp", api_key="bridge-key"), http_client=http_client)

    try:
        client.list_tools(force_refresh=True)
    finally:
        http_client.close()

    assert calls[0]["authorization"] == "Bearer bridge-key"
    assert "exaApiKey=" not in calls[0]["url"]


def test_mcp_http_client_supports_explicit_query_api_key_name():
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            {
                "url": str(request.url),
                "authorization": request.headers.get("Authorization"),
                "payload": json.loads(request.content.decode("utf-8")),
            }
        )
        payload = calls[-1]["payload"]
        method = payload.get("method")
        if method == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload.get("id"), "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}})
        if method == "notifications/initialized":
            return httpx.Response(202, text="")
        if method == "tools/list":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload.get("id"), "result": {"tools": []}})
        raise AssertionError(f"Unexpected MCP method: {method}")

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = McpHttpClient(
        McpClientConfig(base_url="https://mcp.exa.ai/mcp", api_key="exa-key", query_api_key_name="exaApiKey"),
        http_client=http_client,
    )

    try:
        client.list_tools(force_refresh=True)
    finally:
        http_client.close()

    assert calls[0]["authorization"] == "Bearer exa-key"
    assert "exaApiKey=exa-key" in calls[0]["url"]



def test_mcp_http_client_parses_sse_wrapped_jsonrpc_messages():
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content.decode("utf-8")))
        method = calls[-1].get("method")
        if method == "initialize":
            body = '''event: message
data: {"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{"listChanged":true}},"serverInfo":{"name":"mcp-typescript server on vercel","version":"0.1.0"}},"jsonrpc":"2.0","id":"init-1"}

'''
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        if method == "notifications/initialized":
            return httpx.Response(202, text="")
        if method == "tools/list":
            body = '''event: message
data: {"result":{"tools":[{"name":"web_search_exa","description":"Search the web","inputSchema":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}]},"jsonrpc":"2.0","id":"list-1"}

'''
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        raise AssertionError(f"Unexpected MCP method: {method}")

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = McpHttpClient(McpClientConfig(base_url="https://mcp.exa.ai/mcp", api_key=None), http_client=http_client)

    try:
        tools = client.list_tools(force_refresh=True)
    finally:
        http_client.close()

    assert tools[0]["name"] == "web_search_exa"
