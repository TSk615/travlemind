import json


def test_bridge_supports_initialize_list_and_call(client, monkeypatch):
    import travelmind_groksearch_bridge.main as bridge_main

    class FakeRunner:
        def initialize(self, params):
            assert params["protocolVersion"] == "2024-11-05"
            return {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "groksearch", "version": "0.1.0"},
            }

        def list_tools(self):
            return [
                {"name": "web_search", "description": "Search with Grok"},
                {"name": "web_fetch", "description": "Fetch a page"},
            ]

        def call_tool(self, name, arguments):
            assert name == "web_search"
            assert arguments == {"query": "Kyoto quiet hotels"}
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"session_id": "session_123", "content": "Mock answer", "sources_count": 2}),
                    }
                ],
                "isError": False,
            }

        def close(self):
            return None

    monkeypatch.setattr(bridge_main, "get_runner", lambda: FakeRunner())

    initialize_response = client.post(
        "/mcp/",
        headers={"Authorization": "Bearer bridge-key"},
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
    assert initialize_response.json()["result"]["serverInfo"]["name"] == "groksearch"

    list_response = client.post(
        "/mcp/",
        headers={"Authorization": "Bearer bridge-key"},
        json={"jsonrpc": "2.0", "id": "2", "method": "tools/list", "params": {}},
    )
    assert list_response.status_code == 200, list_response.text
    tools = list_response.json()["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["web_search", "web_fetch"]

    call_response = client.post(
        "/mcp/",
        headers={"Authorization": "Bearer bridge-key"},
        json={
            "jsonrpc": "2.0",
            "id": "3",
            "method": "tools/call",
            "params": {"name": "web_search", "arguments": {"query": "Kyoto quiet hotels"}},
        },
    )
    assert call_response.status_code == 200, call_response.text
    text_payload = call_response.json()["result"]["content"][0]["text"]
    assert "session_123" in text_payload


def test_bridge_rejects_invalid_auth(client):
    response = client.post(
        "/mcp/",
        headers={"Authorization": "Bearer wrong-key"},
        json={"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}},
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid Bearer token for GrokSearch bridge"


def test_bridge_surfaces_runner_failures(client, monkeypatch):
    import travelmind_groksearch_bridge.main as bridge_main
    from travelmind_groksearch_bridge.service import GrokSearchRunnerError

    class FailingRunner:
        def initialize(self, params):
            del params
            raise GrokSearchRunnerError("upstream groksearch failed")

        def list_tools(self):
            raise AssertionError("should not be reached")

        def call_tool(self, name, arguments):
            raise AssertionError("should not be reached")

        def close(self):
            return None

    monkeypatch.setattr(bridge_main, "get_runner", lambda: FailingRunner())

    response = client.post(
        "/mcp/",
        headers={"Authorization": "Bearer bridge-key"},
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
    assert response.status_code == 500
    assert "upstream groksearch failed" in response.json()["error"]["message"]
