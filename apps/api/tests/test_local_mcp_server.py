from fastapi.testclient import TestClient



def test_local_mcp_server_supports_initialize_list_and_call(client: TestClient, monkeypatch):
    import travelmind_api.api.routes.mcp as mcp_route

    class FakeExaPoolClient:
        def __init__(self, config):
            self.config = config

        def search(self, *, query: str, num_results: int = 10, search_type: str = "auto", include_text: bool = False):
            return {
                "query": query,
                "numResults": num_results,
                "searchType": search_type,
                "includeText": include_text,
                "results": [{"title": "Kyoto Guide"}],
            }

        def contents(self, *, urls, include_text: bool = True, include_html: bool = False):
            return {"urls": urls, "includeText": include_text, "includeHtml": include_html}

        def find_similar(self, *, url: str, num_results: int = 10, include_text: bool = False):
            return {"url": url, "numResults": num_results, "includeText": include_text}

        def answer(self, *, query: str, include_text: bool = False):
            return {"query": query, "includeText": include_text, "answer": "Mock answer"}

        def research(self, *, instructions: str, model: str = "exa-research", wait_for_completion: bool = True, poll_interval_seconds: float = 2.0, max_wait_seconds: float = 45.0):
            return {
                "instructions": instructions,
                "model": model,
                "waitForCompletion": wait_for_completion,
                "status": "completed",
            }

    monkeypatch.setenv("TRAVELMIND_MCP_SERVER_API_KEY", "local-mcp-key")
    monkeypatch.setenv("TRAVELMIND_EXA_POOL_BASE_URL", "https://exa.pool.test")
    monkeypatch.setenv("TRAVELMIND_EXA_POOL_API_KEY", "exa-key")
    monkeypatch.setattr(mcp_route, "ExaPoolClient", FakeExaPoolClient)

    initialize_response = client.post(
        "/mcp/",
        headers={"Authorization": "Bearer local-mcp-key"},
        json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "test-client", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            },
        },
    )
    assert initialize_response.status_code == 200, initialize_response.text
    assert initialize_response.json()["result"]["serverInfo"]["name"] == "travelmind-exa-pool-mcp"

    tools_response = client.post(
        "/mcp/",
        headers={"Authorization": "Bearer local-mcp-key"},
        json={"jsonrpc": "2.0", "id": "2", "method": "tools/list", "params": {}},
    )
    assert tools_response.status_code == 200, tools_response.text
    tools = tools_response.json()["result"]["tools"]
    assert any(tool["name"] == "search" for tool in tools)
    assert any(tool["name"] == "research" for tool in tools)

    call_response = client.post(
        "/mcp/",
        headers={"Authorization": "Bearer local-mcp-key"},
        json={
            "jsonrpc": "2.0",
            "id": "3",
            "method": "tools/call",
            "params": {"name": "search", "arguments": {"query": "Kyoto temples", "num_results": 3}},
        },
    )
    assert call_response.status_code == 200, call_response.text
    text_payload = call_response.json()["result"]["content"][0]["text"]
    assert "Kyoto Guide" in text_payload



def test_local_mcp_server_rejects_invalid_auth(client: TestClient, monkeypatch):
    monkeypatch.setenv("TRAVELMIND_MCP_SERVER_API_KEY", "local-mcp-key")
    response = client.post(
        "/mcp/",
        headers={"Authorization": "Bearer wrong-key"},
        json={"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}},
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid Bearer token for MCP server"
