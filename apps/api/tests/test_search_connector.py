import importlib
import json

import httpx


def _search_connector_module():
    return importlib.import_module("travelmind_api.services.search_connector")


def test_groksearch_gateway_enrichs_web_search_with_get_sources(monkeypatch):
    search_connector = _search_connector_module()

    calls: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(
        search_connector.McpHttpClient,
        "list_tools",
        lambda self: [
            {"name": "web_search"},
            {"name": "get_sources"},
        ],
    )

    def fake_call_tool(self, name, arguments):
        calls.append((name, arguments))
        if name == "web_search":
            payload = {"session_id": "session_123", "content": "Mock Grok answer", "sources_count": 1}
        elif name == "get_sources":
            payload = {
                "session_id": "session_123",
                "sources": [
                    {
                        "title": "Kyoto quiet hotels",
                        "url": "https://groksearch.example.test/kyoto-quiet-hotels",
                        "snippet": "Quiet stays near Kyoto Station.",
                    }
                ],
            }
        else:
            raise AssertionError(f"Unexpected MCP tool: {name}")
        return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}

    monkeypatch.setattr(search_connector.McpHttpClient, "call_tool", fake_call_tool)

    gateway = search_connector.ConfiguredSearchGateway(
        search_connector.SearchServiceConfig(
            provider="groksearch",
            transport="mcp",
            base_url="https://groksearch.example.test/mcp",
            api_key="test-key",
        )
    )

    payload = gateway.call_operation("web_search", {"query": "Kyoto quiet hotels"})

    assert payload["session_id"] == "session_123"
    assert payload["sources"][0]["url"] == "https://groksearch.example.test/kyoto-quiet-hotels"
    assert calls == [
        ("web_search", {"query": "Kyoto quiet hotels"}),
        ("get_sources", {"session_id": "session_123"}),
    ]


def test_tavily_gateway_calls_search_api(monkeypatch):
    search_connector = _search_connector_module()

    calls: list[tuple[str, dict[str, object]]] = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, endpoint, headers=None, json=None):
            calls.append((endpoint, json or {}))

            class FakeResponse:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {
                        "results": [
                            {
                                "title": "Tavily Kyoto",
                                "url": "https://example.test/kyoto",
                            }
                        ],
                        "images": [{"url": "https://cdn.example.test/kyoto.jpg"}],
                    }

            return FakeResponse()

    monkeypatch.setattr(search_connector.httpx, "Client", FakeClient)

    gateway = search_connector.ConfiguredSearchGateway(
        search_connector.SearchServiceConfig(
            provider="tavily",
            transport="api",
            base_url="https://api.tavily.com/search",
            api_key="tvly-test",
        )
    )

    payload = gateway.call_operation(
        "search",
        {"query": "Kyoto quiet hotels", "num_results": 6, "include_images": True, "include_image_descriptions": True},
    )

    assert gateway.available_tools() == {"search"}
    assert [call[0] for call in calls] == [
        "https://api.tavily.com/search",
        "https://api.tavily.com/search",
        "https://api.tavily.com/search",
    ]
    assert [call[1]["include_domains"] for call in calls] == [["hk.trip.com"], ["pixabay.com"], ["pexels.com"]]
    assert calls[0][1]["include_images"] is True
    assert payload["request_mode"] == "per_domain"
    assert payload["domain_results"][0]["domain"] == "hk.trip.com"
    assert payload["images"][0]["source_domain"] == "hk.trip.com"
    assert payload["images"][0]["url"] == "https://cdn.example.test/kyoto.jpg"


def test_tavily_gateway_normalizes_image_include_domains(monkeypatch):
    search_connector = _search_connector_module()

    calls: list[dict[str, object]] = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, endpoint, headers=None, json=None):
            calls.append(json or {})

            class FakeResponse:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {"results": [], "images": []}

            return FakeResponse()

    monkeypatch.setattr(search_connector.httpx, "Client", FakeClient)

    gateway = search_connector.ConfiguredSearchGateway(
        search_connector.SearchServiceConfig(
            provider="tavily",
            transport="api",
            base_url="https://api.tavily.com/search",
            api_key="tvly-test",
            image_include_domains=[
                "https://pixabay.com/zh/images/search",
                "https://www.pexels.com/zh-cn/search/",
            ],
        )
    )

    gateway.call_operation("search", {"query": "Kyoto temple photos", "include_images": True})

    assert [call["include_domains"] for call in calls] == [["pixabay.com"], ["pexels.com"]]


def test_tavily_config_from_env_supports_legacy_env_names(monkeypatch):
    search_connector = _search_connector_module()

    monkeypatch.setenv("TRAVELMIND_SEARCH_SERVICE_PROVIDER", "tavily")
    monkeypatch.setenv("TRAVELMIND_SEARCH_SERVICE_TRANSPORT", "api")
    monkeypatch.delenv("TRAVELMIND_TAVILY_BASE_URL", raising=False)
    monkeypatch.delenv("TRAVELMIND_TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("TAVILY_API_URL", "https://api.tavily.com/search")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-legacy")

    config = search_connector.SearchServiceConfig.from_env()

    assert config is not None
    assert config.provider == "tavily"
    assert config.transport == "api"
    assert config.base_url == "https://api.tavily.com/search"
    assert config.api_key == "tvly-legacy"
