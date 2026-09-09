import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from travelmind_api.services.llm import LlmEndpointConfig, OpenAICompatibleClient


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
        return httpx.Response(200, json={"output_text": "hello from saved settings"})

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
    assert relay_response.json()["output_text"] == "hello from saved settings"
    assert captured["url"] == "https://saved.example.test/v1/responses"
    assert captured["authorization"] == "Bearer saved-key"
    assert captured["payload"]["model"] == "saved-model"
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["input"][0]["content"][0]["text"] == "hello"


def test_llm_connection_test_supports_newapi_chat_completions(client, monkeypatch):
    _register(client)
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))

    response = client.post(
        "/api/v1/llm/test",
        json={
            "provider_protocol": "newapi",
            "base_url": "http://localhost:3000/v1",
            "api_key": "newapi-key",
            "model": "gpt-test",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["provider_protocol"] == "newapi"
    assert payload["wire_api"] == "chat_completions"
    assert payload["reply"] == "ok"
    assert captured["url"] == "http://localhost:3000/v1/chat/completions"
    assert captured["authorization"] == "Bearer newapi-key"
    assert captured["payload"]["messages"][0]["content"] == "Reply with exactly: ok"


def test_llm_connection_test_can_use_saved_poi_settings(client, monkeypatch):
    _register(client)
    settings_response = client.put(
        "/api/v1/settings/llm",
        json={
            "agent": {
                "provider_protocol": "newapi",
                "base_url": "https://main.example.test/v1",
                "api_key": "main-key",
                "model": "main-model",
                "wire_api": "chat_completions",
                "poi_provider_protocol": "newapi",
                "poi_base_url": "https://poi.example.test/v1",
                "poi_api_key": "poi-key",
                "poi_model": "poi-model",
                "poi_wire_api": "chat_completions",
            }
        },
    )
    assert settings_response.status_code == 200, settings_response.text
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))

    response = client.post("/api/v1/llm/test", json={"scope": "poi"})

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["base_url"] == "https://poi.example.test/v1"
    assert payload["model"] == "poi-model"
    assert captured["url"] == "https://poi.example.test/v1/chat/completions"
    assert captured["authorization"] == "Bearer poi-key"
    assert captured["payload"]["model"] == "poi-model"
    assert captured["payload"]["stream"] is True


def test_openai_compatible_client_extracts_chat_sse_reasoning_content_fallback():
    client = OpenAICompatibleClient(LlmEndpointConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="grok-test"))
    stream_text = "\n\n".join(
        [
            'data: {"choices":[{"delta":{"role":"assistant","reasoning_content":"{\\"title\\":\\"Core"}}]}',
            'data: {"choices":[{"delta":{"reasoning_content":" Dali POIs\\"}"}}]}',
            "data: [DONE]",
        ]
    )

    assert client._extract_chat_completions_text_from_sse(stream_text) == '{"title":"Core Dali POIs"}'


def test_openai_compatible_client_reports_chat_sse_shape_when_text_is_missing():
    client = OpenAICompatibleClient(LlmEndpointConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="grok-test"))
    stream_text = "\n\n".join(
        [
            'data: {"choices":[{"delta":{"role":"assistant"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            "data: [DONE]",
        ]
    )

    with pytest.raises(ValueError) as exc_info:
        client._extract_chat_completions_text_from_sse(stream_text)

    message = str(exc_info.value)
    assert "did not contain assistant text" in message
    assert "delta_keys=role" in message
    assert "finish_reason=stop" in message



def _build_direct_client(handler, *, wire_api: str = "chat_completions", timeout_seconds: float = 30.0):
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    config = LlmEndpointConfig(
        base_url="https://llm.example.test/v1",
        api_key="test-key",
        model="gpt-test",
        wire_api=wire_api,
        timeout_seconds=timeout_seconds,
    )
    return OpenAICompatibleClient(config, http_client=http_client), http_client


def test_openai_compatible_client_does_not_retry_or_fallback_on_http_400():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    llm_client, http_client = _build_direct_client(handler, wire_api="responses")
    llm_client._sleep = lambda seconds: pytest.fail(f"unexpected retry sleep of {seconds}s for HTTP 400")

    try:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            llm_client.create_chat_completion(messages=[{"role": "user", "content": "hello"}])
    finally:
        http_client.close()

    assert exc_info.value.response.status_code == 400
    assert len(calls) == 1


def test_openai_compatible_client_retries_503_with_exponential_backoff():
    attempts: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(503, json={"error": "upstream busy"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "recovered"}}]})

    llm_client, http_client = _build_direct_client(handler)
    llm_client._sleep = sleeps.append

    try:
        reply = llm_client.create_chat_completion(messages=[{"role": "user", "content": "hello"}])
    finally:
        http_client.close()

    assert reply == "recovered"
    assert len(attempts) == 3
    assert sleeps == [1.0, 2.0]


def test_openai_compatible_client_prefers_retry_after_header_on_429():
    attempts: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"Retry-After": "3"}, json={"error": "rate limited"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "after backoff"}}]})

    llm_client, http_client = _build_direct_client(handler)
    llm_client._sleep = sleeps.append

    try:
        reply = llm_client.create_chat_completion(messages=[{"role": "user", "content": "hello"}])
    finally:
        http_client.close()

    assert reply == "after backoff"
    assert len(attempts) == 2
    assert sleeps == [3.0]


def test_openai_compatible_client_gives_up_after_bounded_retries():
    attempts: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        attempts.append(1)
        return httpx.Response(500, json={"error": "boom"})

    llm_client, http_client = _build_direct_client(handler)
    llm_client._sleep = sleeps.append

    try:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            llm_client.create_chat_completion(messages=[{"role": "user", "content": "hello"}])
    finally:
        http_client.close()

    assert exc_info.value.response.status_code == 500
    assert len(attempts) == 3
    assert sleeps == [1.0, 2.0]


def test_openai_compatible_client_retries_network_errors_with_backoff():
    attempts: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "network recovered"}}]})

    llm_client, http_client = _build_direct_client(handler)
    llm_client._sleep = sleeps.append

    try:
        reply = llm_client.create_chat_completion(messages=[{"role": "user", "content": "hello"}])
    finally:
        http_client.close()

    assert reply == "network recovered"
    assert len(attempts) == 3
    assert sleeps == [1.0, 2.0]


def test_openai_compatible_client_streaming_request_retries_retryable_status():
    attempts: list[dict[str, object]] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(json.loads(request.content.decode("utf-8")))
        if len(attempts) == 1:
            return httpx.Response(502, json={"error": "bad gateway"})
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text='data: {"choices":[{"delta":{"content":"stream"}}]}\n\ndata: {"choices":[{"delta":{"content":" ok"}}]}\n\ndata: [DONE]\n\n',
        )

    llm_client, http_client = _build_direct_client(handler)
    llm_client._sleep = sleeps.append

    try:
        reply = llm_client.create_chat_completion(messages=[{"role": "user", "content": "hello"}], stream=True)
    finally:
        http_client.close()

    assert reply == "stream ok"
    assert attempts[0]["stream"] is True
    assert attempts[1]["stream"] is True
    assert sleeps == [1.0]


def test_openai_compatible_client_preserves_stream_citations():
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'data: {"choices":[{"delta":{"content":"weather"}}],'
                '"citations":[{"url":"https://weather.example.test/daily"}]}\n\n'
                'data: [DONE]\n\n'
            ),
        )

    llm_client, http_client = _build_direct_client(handler)
    try:
        reply = llm_client.create_chat_completion(
            messages=[{"role": "user", "content": "weather"}],
            stream=True,
        )
    finally:
        http_client.close()

    assert reply == "weather"
    assert llm_client.last_citations == ["https://weather.example.test/daily"]


def test_openai_compatible_client_honors_timeout_with_injected_http_client():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    llm_client, http_client = _build_direct_client(handler, timeout_seconds=7.5)

    try:
        reply = llm_client.create_chat_completion(messages=[{"role": "user", "content": "hello"}])
    finally:
        http_client.close()

    assert reply == "ok"
    timeout = captured["timeout"]
    assert isinstance(timeout, dict)
    assert timeout["read"] == 7.5
    assert timeout["connect"] == 7.5


def test_openai_compatible_client_logs_usage_tokens(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46},
            },
        )

    llm_client, http_client = _build_direct_client(handler)

    try:
        with caplog.at_level(logging.INFO, logger="travelmind_api.services.llm.client"):
            reply = llm_client.create_chat_completion(messages=[{"role": "user", "content": "hello"}])
    finally:
        http_client.close()

    assert reply == "ok"
    assert "prompt_tokens=12" in caplog.text
    assert "completion_tokens=34" in caplog.text


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


def test_llm_proxy_rejects_restricted_upstream_base_url(client):
    _register(client)

    response = client.post(
        "/api/v1/llm/proxy",
        json={
            "base_url": "http://10.0.0.5/v1",
            "api_key": "test-key",
            "wire_api": "responses",
            "payload": {
                "model": "gpt-test",
                "input": [{"role": "user", "content": [{"type": "input_text", "text": "hello"}]}],
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_upstream_base_url"



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

def test_llm_proxy_supports_gemini_native_protocol(client, monkeypatch):
    _register(client)
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("x-goog-api-key")
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "hello from gemini"}],
                        }
                    }
                ]
            },
        )

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))

    response = client.post(
        "/api/v1/llm/proxy",
        json={
            "provider_protocol": "gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "api_key": "gemini-key",
            "wire_api": "chat_completions",
            "payload": {
                "model": "gemini-2.5-flash",
                "messages": [
                    {"role": "system", "content": "Be concise."},
                    {"role": "user", "content": "hello"},
                ],
            },
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["choices"][0]["message"]["content"] == "hello from gemini"
    assert captured["url"] == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    assert captured["api_key"] == "gemini-key"
    assert captured["payload"]["systemInstruction"]["parts"][0]["text"] == "Be concise."
    assert captured["payload"]["contents"][0]["role"] == "user"


def test_llm_proxy_supports_claude_native_protocol(client, monkeypatch):
    _register(client)
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("x-api-key")
        captured["version"] = request.headers.get("anthropic-version")
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "hello from claude"},
                ]
            },
        )

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))

    response = client.post(
        "/api/v1/llm/proxy",
        json={
            "provider_protocol": "claude",
            "base_url": "https://api.anthropic.com/v1",
            "api_key": "claude-key",
            "wire_api": "responses",
            "payload": {
                "model": "claude-sonnet-4-5",
                "max_output_tokens": 512,
                "input": [
                    {"role": "system", "content": [{"type": "input_text", "text": "Be concise."}]},
                    {"role": "user", "content": [{"type": "input_text", "text": "hello"}]},
                ],
            },
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["output_text"] == "hello from claude"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["api_key"] == "claude-key"
    assert captured["version"] == "2023-06-01"
    assert captured["payload"]["system"] == "Be concise."
    assert captured["payload"]["max_tokens"] == 512


def test_llm_models_endpoint_normalizes_gemini_models(client, monkeypatch):
    _register(client)
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("x-goog-api-key")
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "models/gemini-2.5-flash",
                        "displayName": "Gemini 2.5 Flash",
                        "description": "Fast model",
                        "supportedGenerationMethods": ["generateContent"],
                        "inputTokenLimit": 1000,
                        "outputTokenLimit": 2000,
                    },
                    {
                        "name": "models/embedding-001",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                ]
            },
        )

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))

    response = client.post(
        "/api/v1/llm/models",
        json={
            "provider_protocol": "gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "api_key": "gemini-key",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert captured["url"] == "https://generativelanguage.googleapis.com/v1beta/models"
    assert captured["api_key"] == "gemini-key"
    assert payload["provider_protocol"] == "gemini"
    assert payload["models"] == [
        {
            "id": "gemini-2.5-flash",
            "name": "Gemini 2.5 Flash",
            "description": "Fast model",
            "owned_by": None,
            "created_at": None,
            "input_token_limit": 1000,
            "output_token_limit": 2000,
        }
    ]


def test_llm_models_endpoint_normalizes_openai_and_claude_models(client, monkeypatch):
    _register(client)
    calls: list[tuple[str, str | None, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((str(request.url), request.headers.get("Authorization"), request.headers.get("x-api-key")))
        if str(request.url).endswith("/openai/v1/models"):
            return httpx.Response(200, json={"data": [{"id": "gpt-5.4-mini", "owned_by": "openai"}]})
        return httpx.Response(200, json={"data": [{"id": "claude-sonnet-4-5", "display_name": "Claude Sonnet 4.5"}]})

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))

    openai_response = client.post(
        "/api/v1/llm/models",
        json={"provider_protocol": "openai", "base_url": "https://models.example.test/openai/v1", "api_key": "openai-key"},
    )
    claude_response = client.post(
        "/api/v1/llm/models",
        json={"provider_protocol": "claude", "base_url": "https://api.anthropic.com/v1", "api_key": "claude-key"},
    )

    assert openai_response.status_code == 200, openai_response.text
    assert claude_response.status_code == 200, claude_response.text
    assert openai_response.json()["data"]["models"][0]["id"] == "gpt-5.4-mini"
    assert claude_response.json()["data"]["models"][0]["id"] == "claude-sonnet-4-5"
    assert calls == [
        ("https://models.example.test/openai/v1/models", "Bearer openai-key", None),
        ("https://api.anthropic.com/v1/models", None, "claude-key"),
    ]


def test_llm_models_endpoint_can_use_saved_poi_key(client, monkeypatch):
    _register(client)
    settings_response = client.put(
        "/api/v1/settings/llm",
        json={
            "agent": {
                "provider_protocol": "newapi",
                "base_url": "https://main.example.test/v1",
                "api_key": "main-key",
                "model": "main-model",
                "wire_api": "chat_completions",
                "poi_provider_protocol": "newapi",
                "poi_base_url": "https://poi.example.test/v1",
                "poi_api_key": "poi-key",
                "poi_model": "poi-model",
                "poi_wire_api": "chat_completions",
            }
        },
    )
    assert settings_response.status_code == 200, settings_response.text
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"data": [{"id": "poi-model"}]})

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))

    response = client.post("/api/v1/llm/models", json={"scope": "poi"})

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["base_url"] == "https://poi.example.test/v1"
    assert payload["models"][0]["id"] == "poi-model"
    assert captured["url"] == "https://poi.example.test/v1/models"
    assert captured["authorization"] == "Bearer poi-key"


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


def test_poi_specialist_probe_is_prompt_only_even_when_search_requested(client, monkeypatch):
    _register(client)

    import travelmind_api.api.routes.llm as llm_route

    captured: dict[str, object] = {}

    def forbidden_search_config(*args, **kwargs):
        raise AssertionError("POI probe should not resolve or call a search service")

    def fake_create_chat_completion(self, *, messages, temperature=0.2, max_tokens=None, stream=False):
        del self
        captured["messages"] = messages
        captured["temperature"] = temperature
        captured["max_tokens"] = max_tokens
        captured["stream"] = stream
        return json.dumps(
            {
                "title": "Core Dali POIs",
                "best_season": "spring and autumn",
                "recommended_duration": "3 to 5 days",
                "general_tips": "Keep the pace slow and group nearby areas.",
                "top_pois": [
                    {
                        "name": "Dali Ancient City",
                        "kind": "district",
                        "area": "old town",
                        "highlights": ["South Gate", "Wuhua Tower", "local cafes"],
                        "reason": "It anchors the first-time Dali experience.",
                        "suggested_time": "half day",
                        "confidence": "high",
                        "source_url": "https://example.test/dali-ancient-city",
                    }
                ],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(llm_route, "_resolve_poi_probe_search_config", forbidden_search_config)
    monkeypatch.setattr(llm_route.OpenAICompatibleClient, "create_chat_completion", fake_create_chat_completion)

    response = client.post(
        "/api/v1/llm/poi-specialist-probe",
        json={
            "provider_protocol": "openai",
            "base_url": "https://llm.example.test/v1",
            "api_key": "llm-key",
            "wire_api": "responses",
            "payload": {"model": "gpt-test", "temperature": 0.2, "max_tokens": 6000},
            "search_provider": "groksearch",
            "search_transport": "mcp",
            "search_base_url": "https://groksearch.example.test/mcp",
            "search_api_key": "grok-key",
            "destination": "Dali",
            "interests": ["city walk", "local food"],
            "user_input": "I want city walk, nearby food, and lakeside wandering ideas.",
            "use_search": True,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert "全网公开信息" in payload["system_prompt"]
    assert "小红书" in payload["system_prompt"]
    assert "知乎" in payload["system_prompt"]
    assert "不要调用外部工具" in payload["system_prompt"]
    assert payload["parsed_json"]["featured_pois"][0]["name"] == "Dali Ancient City"
    assert payload["search"]["enabled"] is False
    assert payload["search"]["requested"] is True
    assert payload["search"]["skipped"] is True
    assert payload["search"]["native_search_allowed"] is True
    assert payload["search"]["external_tool_collection"] is False
    assert payload["search"]["tool_result_keys"] == []
    assert payload["citations"] == []
    assert payload["warnings"] == [payload["search"]["reason"]]
    prompt_payload = json.loads(captured["messages"][1]["content"])
    assert prompt_payload["trip_request"]["destination"] == "Dali"
    assert "planning_brief" in prompt_payload
    assert "poi_context" in prompt_payload
    assert "poi_request" not in prompt_payload
    assert "candidate_pois" not in prompt_payload
    assert "candidate_food_pois" not in prompt_payload
    assert "tool_results" not in prompt_payload
    assert captured["max_tokens"] == 6000
    assert captured["stream"] is True


def test_search_images_proxy_limits_tavily_image_domains(client, monkeypatch):
    _register(client)

    import travelmind_api.api.routes.llm as llm_route

    captured: dict[str, object] = {}
    monkeypatch.setattr(llm_route.ConfiguredSearchGateway, "available_tools", lambda self: {"search"})

    def fake_call_operation(self, name, arguments):
        del self
        captured["name"] = name
        captured["arguments"] = arguments
        return {
            "images": [
                {"url": "https://cdn.pixabay.com/photo/test.jpg", "description": "Pixabay image"}
            ],
            "results": [],
        }

    monkeypatch.setattr(llm_route.ConfiguredSearchGateway, "call_operation", fake_call_operation)

    response = client.post(
        "/api/v1/llm/search-images-proxy",
        json={
            "provider": "tavily",
            "transport": "api",
            "base_url": "https://api.tavily.com/search",
            "api_key": "tvly-test",
            "query": "Guangzhou Tower",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert captured["name"] == "search"
    assert captured["arguments"]["include_images"] is True
    assert captured["arguments"]["include_domains"] == ["hk.trip.com", "pixabay.com", "pexels.com"]
    assert payload["arguments"]["include_domains"] == ["hk.trip.com", "pixabay.com", "pexels.com"]


def test_tavily_images_proxy_returns_top_level_and_result_images(client, monkeypatch):
    _register(client)

    import travelmind_api.api.routes.llm as llm_route
    calls: list[list[str]] = []

    class FakeResponse:
        def __init__(self, domain: str):
            self.domain = domain

        def json(self):
            domain_slug = self.domain.replace(".", "-")
            return {
                "images": [
                    {"url": f"https://cdn.example.test/{domain_slug}-top-1.jpg", "description": "Top image"}
                ],
                "results": [
                    {
                        "title": "Wenguang Tower",
                        "url": "https://example.test/wenguang",
                        "images": [
                            {"url": f"https://cdn.example.test/{domain_slug}-result-1.jpg", "description": "Result image"}
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
            calls.append(json["include_domains"])
            return FakeResponse(json["include_domains"][0])

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
    assert calls == [["hk.trip.com"], ["pixabay.com"], ["pexels.com"]]
    assert payload["request_mode"] == "per_domain"
    assert [entry["domain"] for entry in payload["domain_results"]] == ["hk.trip.com", "pixabay.com", "pexels.com"]
    assert payload["image_candidates"][0]["source"] == "top_level"
    assert payload["image_candidates"][0]["source_domain"] == "hk.trip.com"
    assert payload["image_candidates"][0]["url"] == "https://cdn.example.test/hk-trip-com-top-1.jpg"
    assert payload["image_candidates"][1]["source"] == "result"
    assert payload["image_candidates"][1]["url"] == "https://cdn.example.test/hk-trip-com-result-1.jpg"
    assert payload["top_level_images"][0]["url"] == "https://cdn.example.test/hk-trip-com-top-1.jpg"
    assert payload["result_images"][0]["url"] == "https://cdn.example.test/hk-trip-com-result-1.jpg"


def test_tavily_images_proxy_reuses_saved_tavily_key_when_request_omits_key(client, monkeypatch):
    _register(client)
    settings_response = client.put(
        "/api/v1/settings/llm",
        json={
            "search": {
                "provider": "tavily",
                "transport": "api",
                "base_url": "https://api.tavily.com/search",
                "api_key": "saved-tvly-key",
                "timeout_seconds": 18,
            }
        },
    )
    assert settings_response.status_code == 200, settings_response.text

    import travelmind_api.api.routes.llm as llm_route

    captured: dict[str, object] = {}

    class FakeResponse:
        def json(self):
            return {"images": [], "results": []}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, endpoint, headers=None, json=None):
            captured["authorization"] = (headers or {}).get("Authorization")
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(llm_route.httpx, "Client", FakeClient)

    response = client.post(
        "/api/v1/llm/tavily-images-proxy",
        json={
            "base_url": "https://api.tavily.com/search",
            "query": "Guangzhou Tower",
        },
    )

    assert response.status_code == 200, response.text
    assert captured["authorization"] == "Bearer saved-tvly-key"
    assert captured["payload"]["include_images"] is True


def test_tavily_images_proxy_does_not_reuse_saved_groksearch_key(client):
    _register(client)
    settings_response = client.put(
        "/api/v1/settings/llm",
        json={
            "search": {
                "provider": "groksearch",
                "transport": "mcp",
                "base_url": "https://groksearch.example.test/mcp",
                "api_key": "saved-grok-bridge-key",
                "timeout_seconds": 18,
            }
        },
    )
    assert settings_response.status_code == 200, settings_response.text

    response = client.post(
        "/api/v1/llm/tavily-images-proxy",
        json={
            "base_url": "https://api.tavily.com/search",
            "query": "Guangzhou Tower",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "tavily_api_key_required"


def test_tavily_images_proxy_limits_returned_image_candidates(client, monkeypatch):
    _register(client)

    import travelmind_api.api.routes.llm as llm_route

    class FakeResponse:
        def __init__(self, domain: str):
            self.domain = domain

        def json(self):
            domain_slug = self.domain.replace(".", "-")
            return {
                "images": [
                    {"url": f"https://cdn.example.test/{domain_slug}-top-{index}.jpg", "description": f"Top image {index}"}
                    for index in range(30)
                ],
                "results": [],
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, endpoint, headers=None, json=None):
            del endpoint, headers
            return FakeResponse(json["include_domains"][0])

    monkeypatch.setattr(llm_route.httpx, "Client", FakeClient)

    response = client.post(
        "/api/v1/llm/tavily-images-proxy",
        json={
            "base_url": "https://api.tavily.com/search",
            "api_key": "tvly-test",
            "query": "Guangzhou Tower",
            "search_depth": "basic",
            "max_results": 8,
            "include_image_descriptions": True,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert len(payload["image_candidates"]) == 12
    assert payload["image_candidates_total"] == 90
    assert payload["image_candidates_truncated"] is True
    assert len(payload["top_level_images"]) == 12
    assert payload["top_level_images_total"] == 90
    assert payload["top_level_images_truncated"] is True
    assert payload["domain_results"][0]["images_total_count"] == 30
    assert payload["domain_results"][0]["images_returned_count"] == 4
    assert len(payload["raw_result"]["domain_results"][0]["result"]["images"]) == 4
    assert payload["raw_result"]["domain_results"][0]["result"]["images_total_count"] == 30
    assert payload["raw_result"]["domain_results"][0]["result"]["images_truncated"] is True
