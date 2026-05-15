import json

import httpx
from fastapi.testclient import TestClient


class BrokenJsonStream(httpx.SyncByteStream):
    def __iter__(self):
        yield b'{"output_text":"Recovered partial body"}'
        raise httpx.RemoteProtocolError("peer closed connection without sending complete message body (incomplete chunked read)")

    def close(self) -> None:
        return None


class EventStream(httpx.SyncByteStream):
    def __init__(self, *chunks: bytes):
        self._chunks = chunks

    def __iter__(self):
        yield from self._chunks

    def close(self) -> None:
        return None



def _register(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Planner",
            "email": "planner@example.com",
            "password": "supersecure123",
        },
    )
    assert response.status_code == 200, response.text



def _patch_httpx_client(monkeypatch, transport: httpx.BaseTransport) -> None:
    import travelmind_api.api.routes.llm as llm_route

    original_client = httpx.Client

    def build_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(llm_route.httpx, "Client", build_client)



def test_llm_proxy_defaults_requests_to_non_streaming(client, monkeypatch):
    _register(client)
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"output_text": "Hello from relay"})

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))

    response = client.post(
        "/api/v1/llm/proxy",
        json={
            "base_url": "https://llm.example.test/v1",
            "api_key": "test-key",
            "wire_api": "responses",
            "payload": {
                "model": "gpt-test",
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": "hello"}],
                    }
                ],
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["output_text"] == "Hello from relay"
    assert captured["url"] == "https://llm.example.test/v1/responses"
    assert captured["authorization"] == "Bearer test-key"
    assert captured["payload"]["stream"] is False



def test_llm_proxy_uses_saved_user_settings_when_request_omits_provider_fields(client, monkeypatch):
    _register(client)
    response = client.put(
        "/api/v1/settings/llm",
        json={
            "base_url": "https://saved.example.test/v1",
            "api_key": "saved-key",
            "model": "saved-model",
            "wire_api": "chat_completions",
            "agent_provider": "standard",
        },
    )
    assert response.status_code == 200, response.text

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "hello from saved settings",
                        }
                    }
                ]
            },
        )

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))

    relay_response = client.post(
        "/api/v1/llm/proxy",
        json={
            "payload": {
                "messages": [
                    {"role": "user", "content": "hello"},
                ]
            }
        },
    )

    assert relay_response.status_code == 200
    assert relay_response.json()["choices"][0]["message"]["content"] == "hello from saved settings"
    assert captured["url"] == "https://saved.example.test/v1/chat/completions"
    assert captured["authorization"] == "Bearer saved-key"
    assert captured["payload"]["model"] == "saved-model"
    assert captured["payload"]["stream"] is False



def test_llm_proxy_requires_saved_or_explicit_configuration(client):
    _register(client)

    response = client.post(
        "/api/v1/llm/proxy",
        json={
            "payload": {
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": "hello"}],
                    }
                ]
            }
        },
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "llm_proxy_not_configured"



def test_llm_proxy_preserves_partial_upstream_body_when_stream_breaks(client, monkeypatch):
    _register(client)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={
                "content-type": "application/json",
                "cache-control": "no-store",
                "trace-id": "trace_123",
            },
            stream=BrokenJsonStream(),
        )

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))

    response = client.post(
        "/api/v1/llm/proxy",
        json={
            "base_url": "https://llm.example.test/v1",
            "api_key": "test-key",
            "wire_api": "responses",
            "payload": {
                "model": "gpt-test",
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": "hello"}],
                    }
                ],
            },
        },
    )

    assert response.status_code == 200
    assert response.text == '{"output_text":"Recovered partial body"}'
    assert response.headers["x-upstream-body-truncated"] == "1"
    assert response.headers["x-upstream-trace-id"] == "trace_123"
    assert response.headers["cache-control"] == "no-store"



def test_llm_proxy_streams_sse_payload_through_without_buffering(client, monkeypatch):
    _register(client)
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            headers={
                "content-type": "text/event-stream",
                "cache-control": "no-store",
                "trace-id": "trace_stream_123",
            },
            stream=EventStream(
                b'data: {"type":"response.output_text.delta","delta":"Hel"}\n\n',
                b'data: {"type":"response.output_text.delta","delta":"lo"}\n\n',
                b"data: [DONE]\n\n",
            ),
        )

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))

    with client.stream(
        "POST",
        "/api/v1/llm/proxy",
        json={
            "base_url": "https://llm.example.test/v1",
            "api_key": "test-key",
            "wire_api": "responses",
            "payload": {
                "model": "gpt-test",
                "stream": True,
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": "hello"}],
                    }
                ],
            },
        },
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-upstream-trace-id"] == "trace_stream_123"
        body = "".join(response.iter_text())

    assert '"delta":"Hel"' in body
    assert '"delta":"lo"' in body
    assert body.rstrip().endswith("data: [DONE]")
    assert captured["url"] == "https://llm.example.test/v1/responses"
    assert captured["payload"]["stream"] is True



def test_search_proxy_runs_groksearch_web_search_and_returns_hits(client, monkeypatch):
    _register(client)

    import travelmind_api.api.routes.llm as llm_route

    monkeypatch.setattr(llm_route.ConfiguredSearchGateway, "available_tools", lambda self: {"web_search", "get_sources"})
    monkeypatch.setattr(
        llm_route.ConfiguredSearchGateway,
        "call_operation",
        lambda self, name, arguments: {
            "session_id": "session_123",
            "sources": [
                {
                    "title": "Kyoto quiet coffee",
                    "url": "https://groksearch.example.test/kyoto-quiet-coffee",
                    "snippet": "Quiet cafes around Kyoto Station.",
                    "published_at": "2026-04-12T00:00:00Z",
                }
            ],
            "query": arguments["query"],
            "tool_name": name,
        },
    )

    response = client.post(
        "/api/v1/llm/search-proxy",
        json={
            "provider": "groksearch",
            "transport": "mcp",
            "base_url": "https://groksearch.example.test/mcp",
            "api_key": "grok-key",
            "query": "Kyoto quiet coffee",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["provider"] == "groksearch"
    assert payload["transport"] == "mcp"
    assert payload["operation"] == "web_search"
    assert payload["arguments"] == {"query": "Kyoto quiet coffee"}
    assert payload["available_tools"] == ["get_sources", "web_search"]
    assert payload["hits"][0]["url"] == "https://groksearch.example.test/kyoto-quiet-coffee"
    assert payload["result"]["tool_name"] == "web_search"



def test_search_proxy_uses_saved_user_settings_when_request_omits_config(client, monkeypatch):
    _register(client)
    settings_response = client.put(
        "/api/v1/settings/llm",
        json={
            "search": {
                "provider": "groksearch",
                "transport": "mcp",
                "base_url": "https://saved.groksearch.example.test/mcp",
                "api_key": "saved-grok-key",
                "timeout_seconds": 18,
            }
        },
    )
    assert settings_response.status_code == 200, settings_response.text

    import travelmind_api.api.routes.llm as llm_route

    monkeypatch.setattr(llm_route.ConfiguredSearchGateway, "available_tools", lambda self: {"web_search"})
    monkeypatch.setattr(
        llm_route.ConfiguredSearchGateway,
        "call_operation",
        lambda self, name, arguments: {
            "sources": [
                {
                    "title": "Saved settings result",
                    "url": "https://saved.groksearch.example.test/result",
                    "snippet": "Loaded via saved config.",
                }
            ],
            "tool_name": name,
        },
    )

    response = client.post(
        "/api/v1/llm/search-proxy",
        json={
            "query": "Kyoto ryokan near station",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["provider"] == "groksearch"
    assert payload["base_url"] == "https://saved.groksearch.example.test/mcp"
    assert payload["operation"] == "web_search"
    assert payload["hits"][0]["title"] == "Saved settings result"


def test_search_images_proxy_extracts_image_urls_via_web_fetch(client, monkeypatch):
    _register(client)

    import travelmind_api.api.routes.llm as llm_route

    monkeypatch.setattr(llm_route.ConfiguredSearchGateway, "available_tools", lambda self: {"web_search", "web_fetch"})

    def fake_call_operation(self, name, arguments):
        if name == "web_search":
            return {
                "sources": [
                    {
                        "title": "Kyoto photo spot",
                        "url": "https://groksearch.example.test/kyoto-photo-spot",
                        "snippet": "A scenic page without direct image urls in the search payload.",
                    }
                ]
            }
        if name == "web_fetch":
            return {"html": '<meta property="og:image" content="https://cdn.example.test/kyoto-hero.jpg" />'}
        raise AssertionError(f"Unexpected operation: {name}")

    monkeypatch.setattr(llm_route.ConfiguredSearchGateway, "call_operation", fake_call_operation)

    response = client.post(
        "/api/v1/llm/search-images-proxy",
        json={
            "provider": "groksearch",
            "transport": "mcp",
            "base_url": "https://groksearch.example.test/mcp",
            "api_key": "grok-key",
            "query": "Kyoto scenic photo spot",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["operation"] == "web_search"
    assert payload["strategy"] == "search-fallback"
    assert "https://cdn.example.test/kyoto-hero.jpg" in payload["image_urls"]
    assert payload["fetch_payloads"][0]["url"] == "https://groksearch.example.test/kyoto-photo-spot"


def test_tavily_images_proxy_returns_top_level_and_result_images(client, monkeypatch):
    _register(client)

    import travelmind_api.api.routes.llm as llm_route

    class FakeResponse:
        def json(self):
            return {
                "images": [
                    {"url": "https://cdn.example.test/top-1.jpg", "description": "Top image"}
                ],
                "results": [
                    {
                        "title": "Wenguang Tower",
                        "url": "https://example.test/wenguang",
                        "images": [
                            {"url": "https://cdn.example.test/result-1.jpg", "description": "Result image"}
                        ],
                    }
                ],
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, endpoint, headers=None, json=None):
            assert endpoint == "https://api.tavily.com/search"
            assert json["include_images"] is True
            return FakeResponse()

    monkeypatch.setattr(llm_route.httpx, "Client", FakeClient)

    response = client.post(
        "/api/v1/llm/tavily-images-proxy",
        json={
            "base_url": "https://api.tavily.com/search",
            "api_key": "tvly-test",
            "query": "汕头文光塔",
            "search_depth": "basic",
            "max_results": 5,
            "include_image_descriptions": True,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["provider"] == "tavily"
    assert payload["top_level_images"][0]["url"] == "https://cdn.example.test/top-1.jpg"
    assert payload["result_images"][0]["url"] == "https://cdn.example.test/result-1.jpg"
