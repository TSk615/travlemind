import json
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
import travelmind_api.agents.helloagents as helloagents_module

from travelmind_api.agents.base import PlanningRequest, PlanningResult
from travelmind_api.agents.factory import build_orchestrator
from travelmind_api.agents.helloagents import HelloAgentsOrchestrator
from travelmind_api.agents.openai_compatible import OpenAICompatibleOrchestrator
from travelmind_api.agents.stub import StubOrchestrator
from travelmind_api.api.schemas.search import ScoreBreakdown, SearchDocumentResponse
from travelmind_api.core.config import Settings
from travelmind_api.services.llm import LlmConfig, OpenAICompatibleClient
from travelmind_api.services.llm.parser import parse_planning_response
from travelmind_api.services.maps import StubMapsPoiProvider
from travelmind_api.services.search_connector import SearchServiceConfig



def _planning_request() -> PlanningRequest:
    return PlanningRequest(
        trip_id="trip_test",
        title="Kyoto calm days",
        origin="Shanghai",
        destination="Kyoto",
        start_date=date(2026, 4, 14),
        end_date=date(2026, 4, 15),
        budget=4800,
        travelers=2,
        interests=["temples", "coffee"],
        accommodation_preference="Quiet boutique hotel",
        pace="balanced",
        transport_mode="rail",
    )



def test_build_orchestrator_prefers_llm_when_configured(monkeypatch):
    monkeypatch.setenv("TRAVELMIND_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("TRAVELMIND_LLM_API_KEY", "test-key")
    monkeypatch.setenv("TRAVELMIND_LLM_MODEL", "gpt-test")
    monkeypatch.setenv("TRAVELMIND_LLM_WIRE_API", "chat_completions")

    orchestrator = build_orchestrator(Settings(agent_provider="stub"))

    assert isinstance(orchestrator, OpenAICompatibleOrchestrator)



def test_build_orchestrator_prefers_explicit_llm_config_over_env(monkeypatch):
    monkeypatch.delenv("TRAVELMIND_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("TRAVELMIND_LLM_API_KEY", raising=False)
    monkeypatch.delenv("TRAVELMIND_LLM_MODEL", raising=False)

    orchestrator = build_orchestrator(
        Settings(agent_provider="stub"),
        llm_config=LlmConfig(base_url="https://llm.override.test/v1", api_key="override-key", model="gpt-override", wire_api="responses"),
    )

    assert isinstance(orchestrator, OpenAICompatibleOrchestrator)


def test_openai_compatible_client_supports_multimodal_responses_payload():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "ok"}],
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = OpenAICompatibleClient(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        http_client=http_client,
    )

    try:
        response = client.create_chat_completion(
            messages=[
                {"role": "system", "content": "Review travel images."},
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Candidate c1 metadata."},
                        {"type": "input_image", "image_url": "https://cdn.example.test/c1.jpg"},
                    ],
                },
            ]
        )
    finally:
        http_client.close()

    assert response == "ok"
    payload = captured["payload"]
    assert payload["input"][1]["content"][0]["type"] == "input_text"
    assert payload["input"][1]["content"][1] == {"type": "input_image", "image_url": "https://cdn.example.test/c1.jpg"}


def test_openai_compatible_client_supports_multimodal_chat_payload():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "id": "chat_test",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "ok",
                        },
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = OpenAICompatibleClient(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="chat_completions"),
        http_client=http_client,
    )

    try:
        response = client.create_chat_completion(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Candidate c1 metadata."},
                        {"type": "image_url", "image_url": {"url": "https://cdn.example.test/c1.jpg"}},
                    ],
                }
            ]
        )
    finally:
        http_client.close()

    assert response == "ok"
    payload = captured["payload"]
    assert payload["messages"][0]["content"][0] == {"type": "text", "text": "Candidate c1 metadata."}
    assert payload["messages"][0]["content"][1] == {"type": "image_url", "image_url": {"url": "https://cdn.example.test/c1.jpg"}}



def test_openai_compatible_orchestrator_uses_chat_completions(monkeypatch):
    monkeypatch.setenv("TRAVELMIND_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("TRAVELMIND_LLM_API_KEY", "test-key")
    monkeypatch.setenv("TRAVELMIND_LLM_MODEL", "gpt-test")
    monkeypatch.setenv("TRAVELMIND_LLM_WIRE_API", "chat_completions")

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_test",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "summary": "Two Kyoto days focused on temples and coffee.",
                                    "total_budget_estimate": 4700,
                                    "risks": ["Popular sites may require early arrival."],
                                    "days": [
                                        {
                                            "title": "2026-04-14 | East Kyoto",
                                            "summary": "Temple-heavy first day.",
                                            "total_cost": 2300,
                                            "items": [
                                                {
                                                    "type": "sight",
                                                    "name": "Ginkaku-ji",
                                                    "start_time": "09:00",
                                                    "end_time": "11:00",
                                                    "location": "Kyoto",
                                                    "score": 0.9,
                                                    "note": "Start calm and scenic.",
                                                },
                                                {
                                                    "type": "meal",
                                                    "name": "Lunch along Philosopher's Path",
                                                    "start_time": "12:00",
                                                    "end_time": "13:30",
                                                    "location": "Kyoto",
                                                    "score": 0.82,
                                                    "note": "Cafe stop near the walking route.",
                                                },
                                            ],
                                        },
                                        {
                                            "title": "2026-04-15 | Central Kyoto",
                                            "summary": "Market and slow afternoon.",
                                            "total_cost": 2400,
                                            "items": [
                                                {
                                                    "type": "food",
                                                    "name": "Nishiki Market brunch",
                                                    "start_time": "10:00",
                                                    "end_time": "12:00",
                                                    "location": "Kyoto",
                                                    "score": 0.84,
                                                    "note": "Flexible food crawl.",
                                                },
                                                {
                                                    "type": "explore",
                                                    "name": "Kiyomizu hillside stroll",
                                                    "start_time": "14:00",
                                                    "end_time": "17:00",
                                                    "location": "Kyoto",
                                                    "score": 0.88,
                                                    "note": "End with panoramic views.",
                                                },
                                            ],
                                        },
                                    ],
                                }
                            ),
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    config = LlmConfig.from_env()
    assert config is not None
    client = OpenAICompatibleClient(config, http_client=http_client)
    orchestrator = OpenAICompatibleOrchestrator(config, llm_client=client, maps_provider=StubMapsPoiProvider())

    try:
        result = orchestrator.plan_trip(_planning_request())
    finally:
        http_client.close()

    assert isinstance(result, PlanningResult)
    assert result.trace.provider == "openai-compatible"
    assert result.days[0].items[0].location_ref is not None
    assert result.days[0].items[1].route_from_previous is not None
    assert captured["url"] == "https://llm.example.test/v1/chat/completions"
    assert captured["authorization"] == "Bearer test-key"
    assert captured["payload"]["model"] == "gpt-test"
    assert captured["payload"]["messages"][0]["role"] == "system"
    assert any("Planning prompt version:" in note for note in result.trace.notes)



def test_openai_compatible_orchestrator_uses_responses_api():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "summary": "Two Kyoto days focused on temples and coffee.",
                                        "total_budget_estimate": 4700,
                                        "risks": ["Popular sites may require early arrival."],
                                        "days": [
                                            {
                                                "title": "2026-04-14 | East Kyoto",
                                                "summary": "Temple-heavy first day.",
                                                "total_cost": 2300,
                                                "items": [
                                                    {
                                                        "type": "sight",
                                                        "name": "Ginkaku-ji",
                                                        "start_time": "09:00",
                                                        "end_time": "11:00",
                                                        "location": "Kyoto",
                                                        "score": 0.9,
                                                        "note": "Start calm and scenic."
                                                    },
                                                    {
                                                        "type": "meal",
                                                        "name": "Lunch along Philosopher's Path",
                                                        "start_time": "12:00",
                                                        "end_time": "13:30",
                                                        "location": "Kyoto",
                                                        "score": 0.82,
                                                        "note": "Cafe stop near the walking route."
                                                    }
                                                ]
                                            },
                                            {
                                                "title": "2026-04-15 | Central Kyoto",
                                                "summary": "Market and slow afternoon.",
                                                "total_cost": 2400,
                                                "items": [
                                                    {
                                                        "type": "food",
                                                        "name": "Nishiki Market brunch",
                                                        "start_time": "10:00",
                                                        "end_time": "12:00",
                                                        "location": "Kyoto",
                                                        "score": 0.84,
                                                        "note": "Flexible food crawl."
                                                    },
                                                    {
                                                        "type": "explore",
                                                        "name": "Kiyomizu hillside stroll",
                                                        "start_time": "14:00",
                                                        "end_time": "17:00",
                                                        "location": "Kyoto",
                                                        "score": 0.88,
                                                        "note": "End with panoramic views."
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                )
                            }
                        ]
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    config = LlmConfig(base_url="https://sub.jlypx.de", api_key="test-key", model="gpt-5.4", wire_api="responses")
    client = OpenAICompatibleClient(config, http_client=http_client)
    orchestrator = OpenAICompatibleOrchestrator(config, llm_client=client, maps_provider=StubMapsPoiProvider())

    try:
        result = orchestrator.plan_trip(_planning_request())
    finally:
        http_client.close()

    assert isinstance(result, PlanningResult)
    assert result.trace.provider == "openai-compatible"
    assert captured["url"] == "https://sub.jlypx.de/responses"
    assert captured["authorization"] == "Bearer test-key"
    assert captured["payload"]["model"] == "gpt-5.4"
    assert captured["payload"]["input"][0]["role"] == "system"



def test_openai_compatible_orchestrator_accepts_responses_payload_with_chat_choices():
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "id": "resp_choices",
                "object": "response",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "summary": "Two Kyoto days focused on temples and coffee.",
                                    "total_budget_estimate": 4700,
                                    "risks": ["Popular sites may require early arrival."],
                                    "days": [
                                        {
                                            "title": "2026-04-14 | East Kyoto",
                                            "summary": "Temple-heavy first day.",
                                            "total_cost": 2300,
                                            "items": [
                                                {
                                                    "type": "sight",
                                                    "name": "Ginkaku-ji",
                                                    "start_time": "09:00",
                                                    "end_time": "11:00",
                                                    "location": "Kyoto",
                                                    "score": 0.9,
                                                    "note": "Start calm and scenic.",
                                                },
                                                {
                                                    "type": "meal",
                                                    "name": "Lunch along Philosopher's Path",
                                                    "start_time": "12:00",
                                                    "end_time": "13:30",
                                                    "location": "Kyoto",
                                                    "score": 0.82,
                                                    "note": "Cafe stop near the walking route.",
                                                },
                                            ],
                                        },
                                        {
                                            "title": "2026-04-15 | Central Kyoto",
                                            "summary": "Market and slow afternoon.",
                                            "total_cost": 2400,
                                            "items": [
                                                {
                                                    "type": "food",
                                                    "name": "Nishiki Market brunch",
                                                    "start_time": "10:00",
                                                    "end_time": "12:00",
                                                    "location": "Kyoto",
                                                    "score": 0.84,
                                                    "note": "Flexible food crawl.",
                                                },
                                                {
                                                    "type": "explore",
                                                    "name": "Kiyomizu hillside stroll",
                                                    "start_time": "14:00",
                                                    "end_time": "17:00",
                                                    "location": "Kyoto",
                                                    "score": 0.88,
                                                    "note": "End with panoramic views.",
                                                },
                                            ],
                                        },
                                    ],
                                }
                            ),
                        }
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    config = LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses")
    client = OpenAICompatibleClient(config, http_client=http_client)
    orchestrator = OpenAICompatibleOrchestrator(config, llm_client=client, maps_provider=StubMapsPoiProvider())

    try:
        result = orchestrator.plan_trip(_planning_request())
    finally:
        http_client.close()

    assert result.summary.startswith("Two Kyoto days focused on temples and coffee.")



def test_openai_compatible_orchestrator_accepts_nested_response_output_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "id": "resp_nested",
                "object": "response",
                "response": {
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {
                                            "summary": "Two Kyoto days focused on temples and coffee.",
                                            "total_budget_estimate": 4700,
                                            "risks": ["Popular sites may require early arrival."],
                                            "days": [
                                                {
                                                    "title": "2026-04-14 | East Kyoto",
                                                    "summary": "Temple-heavy first day.",
                                                    "total_cost": 2300,
                                                    "items": [
                                                        {
                                                            "type": "sight",
                                                            "name": "Ginkaku-ji",
                                                            "start_time": "09:00",
                                                            "end_time": "11:00",
                                                            "location": "Kyoto",
                                                            "score": 0.9,
                                                            "note": "Start calm and scenic.",
                                                        },
                                                        {
                                                            "type": "meal",
                                                            "name": "Lunch along Philosopher's Path",
                                                            "start_time": "12:00",
                                                            "end_time": "13:30",
                                                            "location": "Kyoto",
                                                            "score": 0.82,
                                                            "note": "Cafe stop near the walking route.",
                                                        },
                                                    ],
                                                },
                                                {
                                                    "title": "2026-04-15 | Central Kyoto",
                                                    "summary": "Market and slow afternoon.",
                                                    "total_cost": 2400,
                                                    "items": [
                                                        {
                                                            "type": "food",
                                                            "name": "Nishiki Market brunch",
                                                            "start_time": "10:00",
                                                            "end_time": "12:00",
                                                            "location": "Kyoto",
                                                            "score": 0.84,
                                                            "note": "Flexible food crawl.",
                                                        },
                                                        {
                                                            "type": "explore",
                                                            "name": "Kiyomizu hillside stroll",
                                                            "start_time": "14:00",
                                                            "end_time": "17:00",
                                                            "location": "Kyoto",
                                                            "score": 0.88,
                                                            "note": "End with panoramic views.",
                                                        },
                                                    ],
                                                },
                                            ],
                                        }
                                    ),
                                }
                            ],
                        }
                    ]
                },
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    config = LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses")
    client = OpenAICompatibleClient(config, http_client=http_client)
    orchestrator = OpenAICompatibleOrchestrator(config, llm_client=client, maps_provider=StubMapsPoiProvider())

    try:
        result = orchestrator.plan_trip(_planning_request())
    finally:
        http_client.close()

    assert result.summary.startswith("Two Kyoto days focused on temples and coffee.")



def test_openai_compatible_orchestrator_falls_back_to_chat_completions_when_responses_has_no_text():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url).endswith("/responses"):
            return httpx.Response(
                200,
                json={
                    "id": "resp_empty",
                    "object": "response",
                    "status": "completed",
                    "output": [],
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "summary": "Two Kyoto days focused on temples and coffee.",
                                    "total_budget_estimate": 4700,
                                    "risks": ["Popular sites may require early arrival."],
                                    "days": [
                                        {
                                            "title": "2026-04-14 | East Kyoto",
                                            "summary": "Temple-heavy first day.",
                                            "total_cost": 2300,
                                            "items": [
                                                {
                                                    "type": "sight",
                                                    "name": "Ginkaku-ji",
                                                    "start_time": "09:00",
                                                    "end_time": "11:00",
                                                    "location": "Kyoto",
                                                    "score": 0.9,
                                                    "note": "Start calm and scenic.",
                                                },
                                                {
                                                    "type": "meal",
                                                    "name": "Lunch along Philosopher's Path",
                                                    "start_time": "12:00",
                                                    "end_time": "13:30",
                                                    "location": "Kyoto",
                                                    "score": 0.82,
                                                    "note": "Cafe stop near the walking route.",
                                                },
                                            ],
                                        },
                                        {
                                            "title": "2026-04-15 | Central Kyoto",
                                            "summary": "Market and slow afternoon.",
                                            "total_cost": 2400,
                                            "items": [
                                                {
                                                    "type": "food",
                                                    "name": "Nishiki Market brunch",
                                                    "start_time": "10:00",
                                                    "end_time": "12:00",
                                                    "location": "Kyoto",
                                                    "score": 0.84,
                                                    "note": "Flexible food crawl.",
                                                },
                                                {
                                                    "type": "explore",
                                                    "name": "Kiyomizu hillside stroll",
                                                    "start_time": "14:00",
                                                    "end_time": "17:00",
                                                    "location": "Kyoto",
                                                    "score": 0.88,
                                                    "note": "End with panoramic views.",
                                                },
                                            ],
                                        },
                                    ],
                                }
                            ),
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    config = LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses")
    client = OpenAICompatibleClient(config, http_client=http_client)
    orchestrator = OpenAICompatibleOrchestrator(config, llm_client=client, maps_provider=StubMapsPoiProvider())

    try:
        result = orchestrator.plan_trip(_planning_request())
    finally:
        http_client.close()

    assert result.summary.startswith("Two Kyoto days focused on temples and coffee.")
    assert calls == [
        "https://llm.example.test/v1/responses",
        "https://llm.example.test/v1/chat/completions",
    ]


def test_openai_compatible_orchestrator_retries_responses_with_streaming_after_400():
    captured_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        captured_payloads.append(payload)
        if len(captured_payloads) == 1:
            return httpx.Response(400, json={"error": {"message": "stream=true required"}})

        stream_payload = {
            "type": "response.completed",
            "response": {
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "summary": "Two Kyoto days focused on temples and coffee.",
                                        "total_budget_estimate": 4700,
                                        "risks": ["Popular sites may require early arrival."],
                                        "days": [
                                            {
                                                "title": "2026-04-14 | East Kyoto",
                                                "summary": "Temple-heavy first day.",
                                                "total_cost": 2300,
                                                "items": [
                                                    {
                                                        "type": "sight",
                                                        "name": "Ginkaku-ji",
                                                        "start_time": "09:00",
                                                        "end_time": "11:00",
                                                        "location": "Kyoto",
                                                        "score": 0.9,
                                                        "note": "Start calm and scenic.",
                                                    },
                                                    {
                                                        "type": "meal",
                                                        "name": "Lunch along Philosopher's Path",
                                                        "start_time": "12:00",
                                                        "end_time": "13:30",
                                                        "location": "Kyoto",
                                                        "score": 0.82,
                                                        "note": "Cafe stop near the walking route.",
                                                    },
                                                ],
                                            },
                                            {
                                                "title": "2026-04-15 | Central Kyoto",
                                                "summary": "Market and slow afternoon.",
                                                "total_cost": 2400,
                                                "items": [
                                                    {
                                                        "type": "food",
                                                        "name": "Nishiki Market brunch",
                                                        "start_time": "10:00",
                                                        "end_time": "12:00",
                                                        "location": "Kyoto",
                                                        "score": 0.84,
                                                        "note": "Flexible food crawl.",
                                                    },
                                                    {
                                                        "type": "explore",
                                                        "name": "Kiyomizu hillside stroll",
                                                        "start_time": "14:00",
                                                        "end_time": "17:00",
                                                        "location": "Kyoto",
                                                        "score": 0.88,
                                                        "note": "End with panoramic views.",
                                                    },
                                                ],
                                            },
                                        ],
                                    }
                                ),
                            }
                        ],
                    }
                ]
            },
        }
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=f"data: {json.dumps(stream_payload)}\n\ndata: [DONE]\n\n",
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    config = LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses")
    client = OpenAICompatibleClient(config, http_client=http_client)
    orchestrator = OpenAICompatibleOrchestrator(config, llm_client=client, maps_provider=StubMapsPoiProvider())

    try:
        result = orchestrator.plan_trip(_planning_request())
    finally:
        http_client.close()

    assert result.summary.startswith("Two Kyoto days focused on temples and coffee.")
    assert captured_payloads[0]["stream"] is False
    assert captured_payloads[1]["stream"] is True


def test_openai_compatible_orchestrator_retries_streaming_once_after_eof():
    captured_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        captured_payloads.append(payload)
        if len(captured_payloads) == 1:
            return httpx.Response(400, json={"error": {"message": "stream=true required"}})
        if len(captured_payloads) == 2:
            raise httpx.ReadError(
                "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1016)",
                request=request,
            )

        stream_payload = {
            "type": "response.completed",
            "response": {
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "summary": "Two Kyoto days focused on temples and coffee.",
                                        "total_budget_estimate": 4700,
                                        "risks": ["Popular sites may require early arrival."],
                                        "days": [
                                            {
                                                "title": "2026-04-14 | East Kyoto",
                                                "summary": "Temple-heavy first day.",
                                                "total_cost": 2300,
                                                "items": [
                                                    {
                                                        "type": "sight",
                                                        "name": "Ginkaku-ji",
                                                        "start_time": "09:00",
                                                        "end_time": "11:00",
                                                        "location": "Kyoto",
                                                        "score": 0.9,
                                                        "note": "Start calm and scenic.",
                                                    },
                                                    {
                                                        "type": "meal",
                                                        "name": "Lunch along Philosopher's Path",
                                                        "start_time": "12:00",
                                                        "end_time": "13:30",
                                                        "location": "Kyoto",
                                                        "score": 0.82,
                                                        "note": "Cafe stop near the walking route.",
                                                    },
                                                ],
                                            },
                                            {
                                                "title": "2026-04-15 | Central Kyoto",
                                                "summary": "Market and slow afternoon.",
                                                "total_cost": 2400,
                                                "items": [
                                                    {
                                                        "type": "food",
                                                        "name": "Nishiki Market brunch",
                                                        "start_time": "10:00",
                                                        "end_time": "12:00",
                                                        "location": "Kyoto",
                                                        "score": 0.84,
                                                        "note": "Flexible food crawl.",
                                                    },
                                                    {
                                                        "type": "explore",
                                                        "name": "Kiyomizu hillside stroll",
                                                        "start_time": "14:00",
                                                        "end_time": "17:00",
                                                        "location": "Kyoto",
                                                        "score": 0.88,
                                                        "note": "End with panoramic views.",
                                                    },
                                                ],
                                            },
                                        ],
                                    }
                                ),
                            }
                        ],
                    }
                ]
            },
        }
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=f"data: {json.dumps(stream_payload)}\n\ndata: [DONE]\n\n",
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    config = LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses")
    client = OpenAICompatibleClient(config, http_client=http_client)
    orchestrator = OpenAICompatibleOrchestrator(config, llm_client=client, maps_provider=StubMapsPoiProvider())

    try:
        result = orchestrator.plan_trip(_planning_request())
    finally:
        http_client.close()

    assert result.summary.startswith("Two Kyoto days focused on temples and coffee.")
    assert captured_payloads[0]["stream"] is False
    assert captured_payloads[1]["stream"] is True
    assert captured_payloads[2]["stream"] is True


def test_helloagents_compatible_llm_retries_once_after_transport_error(monkeypatch):
    class FakeClient:
        def __init__(self, config):
            del config
            self.calls = 0

        def create_chat_completion(self, *, messages, temperature=0.2, max_tokens=None):
            del messages, temperature, max_tokens
            self.calls += 1
            if self.calls == 1:
                raise httpx.ReadError(
                    "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1016)",
                    request=httpx.Request("POST", "https://llm.example.test/v1/responses"),
                )
            return "retry succeeded"

    monkeypatch.setattr(helloagents_module, "OpenAICompatibleClient", FakeClient)
    llm = helloagents_module.HelloAgentsCompatibleLLM(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses")
    )

    result = llm.invoke([{"role": "user", "content": "hello"}])

    assert result.content == "retry succeeded"
    assert llm._client.calls == 2


def test_build_orchestrator_returns_stub_without_llm_config(monkeypatch):
    monkeypatch.delenv("TRAVELMIND_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("TRAVELMIND_LLM_API_KEY", raising=False)
    monkeypatch.delenv("TRAVELMIND_LLM_MODEL", raising=False)
    monkeypatch.delenv("TRAVELMIND_LLM_WIRE_API", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    orchestrator = build_orchestrator(Settings(agent_provider="stub"))

    assert isinstance(orchestrator, StubOrchestrator)



def test_openai_compatible_orchestrator_falls_back_to_stub_on_parse_error():
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "not valid json",
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    config = LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="chat_completions")
    client = OpenAICompatibleClient(config, http_client=http_client)
    orchestrator = OpenAICompatibleOrchestrator(config, llm_client=client, maps_provider=StubMapsPoiProvider())

    try:
        result = orchestrator.plan_trip(_planning_request())
    finally:
        http_client.close()

    assert isinstance(result, PlanningResult)
    assert result.trace.provider == "stub"
    assert result.days[0].items[0].location_ref is not None
    assert any("fallback" in note.lower() for note in result.trace.notes)

def test_llm_config_supports_role_overrides_from_mapping():
    config = LlmConfig.from_mapping(
        {
            "base_url": "https://default.example.test/v1",
            "api_key": "default-key",
            "model": "gpt-default",
            "wire_api": "responses",
            "role_overrides": {
                "attraction_specialist": {
                    "base_url": "https://attractions.example.test/v1",
                    "model": "gpt-attractions",
                },
                "hotel_specialist": {
                    "base_url": "https://hotels.example.test/v1",
                    "api_key": "hotel-key",
                    "model": "gpt-hotels",
                },
            },
        }
    )

    assert config is not None
    assert config.config_for_role("attraction_specialist").base_url == "https://attractions.example.test/v1"
    assert config.config_for_role("attraction_specialist").api_key == "default-key"
    assert config.config_for_role("attraction_specialist").model == "gpt-attractions"
    assert config.config_for_role("weather_specialist").base_url == "https://default.example.test/v1"
    assert config.config_for_role("hotel_specialist").api_key == "hotel-key"



def test_build_orchestrator_prefers_helloagents_when_requested():
    orchestrator = build_orchestrator(
        Settings(agent_provider="standard"),
        llm_config=LlmConfig(base_url="https://llm.override.test/v1", api_key="override-key", model="gpt-override", wire_api="responses"),
        agent_provider="helloagents",
    )

    assert isinstance(orchestrator, HelloAgentsOrchestrator)



def test_build_orchestrator_ignores_helloagents_when_disabled():
    orchestrator = build_orchestrator(
        Settings(agent_provider="helloagents"),
        llm_config=LlmConfig(base_url="https://llm.override.test/v1", api_key="override-key", model="gpt-override", wire_api="responses"),
        agent_provider="helloagents",
        enable_helloagents=False,
    )

    assert isinstance(orchestrator, OpenAICompatibleOrchestrator)



def _fake_helloagents_module(
    calls: list[str],
    *,
    llm_by_role: dict[str, dict[str, object]] | None = None,
    failing_role: str | None = None,
):
    class FakeSimpleAgent:
        def __init__(self, *, name, llm, system_prompt, **kwargs):
            self.name = name
            self.llm = llm
            self.system_prompt = system_prompt
            self.kwargs = kwargs
            if llm_by_role is not None:
                llm_by_role[name] = dict(llm.kwargs)

        def run(self, prompt):
            calls.append(self.name)
            if failing_role == self.name:
                raise RuntimeError(f"forced upstream failure for {self.name}")
            if self.name == "brief_parser":
                assert "trip_request" in prompt
                return json.dumps(
                    {
                        "destination": "Kyoto",
                        "trip_days": 2,
                        "budget_band": "midrange",
                        "budget_is_hard_constraint": True,
                        "budget_priority": "protect transport and ticket budget first",
                        "allow_budget_flex": False,
                        "pace": "balanced",
                        "must_have": ["temples", "coffee"],
                        "avoid": ["overpacked long-distance transfers"],
                        "transport": "rail",
                        "accommodation": "Quiet boutique hotel",
                        "interests": ["temples", "coffee"],
                        "planning_constraints": ["keep sequencing realistic"],
                    }
                )
            if self.name == "attraction_specialist":
                assert "candidate_attractions" in prompt
                return json.dumps(
                    {
                        "candidate_areas": ["Higashiyama", "Downtown Kyoto"],
                        "featured_pois": [
                            {
                                "name": "Ginkaku-ji",
                                "area": "Higashiyama",
                                "reason": "Calm scenic morning.",
                                "suggested_time": "morning",
                                "booking_info": {
                                    "price_label": "Adult ticket around 500 JPY",
                                    "estimated_price": 25,
                                    "booking_required": False,
                                    "reservation_required": False,
                                    "official_booking_url": "https://www.city.kyoto.lg.jp/official/ginkakuji",
                                    "booking_window": "Buy on the day unless peak season notices change.",
                                    "reminder": "Check the official notice page during peak foliage periods.",
                                    "notes": ["Use the official page if a seasonal reservation rule appears."],
                                    "source_urls": ["https://www.city.kyoto.lg.jp/official/ginkakuji"],
                                },
                                "visit_requirements": {
                                    "reservation_policy": "not_needed",
                                    "timed_entry": False,
                                    "identity_required": False,
                                    "advance_booking_note": "No reservation is usually needed, but peak seasonal controls can change.",
                                    "notes": ["Arrive early if limited-entry notices appear."],
                                },
                            }
                        ],
                        "sequencing_hints": ["Keep East Kyoto stops together."],
                        "crowd_notes": ["Arrive early at the headline sights."],
                        "attraction_risks": ["Long cross-city transfers will hurt pacing."],
                    }
                )
            if self.name == "weather_specialist":
                assert "season_context" in prompt
                return json.dumps(
                    {
                        "overall_outlook": "Cool mornings and mild afternoons with occasional light rain.",
                        "daily_outlook": ["Day 1: cool start, mild afternoon.", "Day 2: light rain risk after lunch."],
                        "packing_notes": ["Carry a light layer.", "Bring a compact umbrella."],
                        "timing_guidance": ["Outdoor walks fit best before late afternoon."],
                        "weather_risks": ["Light rain may affect exposed temple walks."],
                    }
                )
            if self.name == "hotel_specialist":
                assert "candidate_hotels" in prompt
                return json.dumps(
                    {
                        "recommended_areas": ["Downtown Kyoto", "Higashiyama"],
                        "hotel_candidates": [
                            {
                                "name": "Downtown Kyoto Hotel",
                                "area": "Downtown Kyoto",
                                "reason": "Balanced access to food and transit.",
                                "price_hint": "moderate",
                            }
                        ],
                        "stay_strategy": ["Prefer one transit-friendly base for the whole trip."],
                        "budget_notes": ["Keep the hotel near the nightly target budget band."],
                    }
                )
            if self.name == "transport_specialist":
                assert "transport_context" in prompt
                return json.dumps(
                    {
                        "intercity_options": [
                            {
                                "mode": "high_speed_rail",
                                "route": "Osaka to Kyoto Station",
                                "duration_hint": "about 15 to 30 minutes",
                                "price_hint": "roughly within the current rail fare range",
                                "booking_window": "Reserve early during peak periods",
                                "reason": "Fastest practical rail transfer into central Kyoto.",
                                "official_booking_url": "https://rail.example.test/kyoto",
                                "booking_required": True,
                                "reservation_required": True,
                                "booking_notes": ["Use the operator booking page for reserved seats."],
                            }
                        ],
                        "arrival_strategy": ["Align the arrival transfer with the hotel area and first-day pacing."],
                        "local_mobility_strategy": ["Use rail or subway first, with buses only when they reduce walking burden."],
                        "pass_or_ticket_notes": ["Only recommend rail passes when they beat point-to-point tickets."],
                        "budget_notes": ["Treat the rail transfer as a dedicated transport cost and keep it grounded."],
                        "transport_risks": ["Peak-hour trains may require reserved seats."],
                        "sequencing_constraints": ["Keep departure-day activities close to the final station corridor."],
                        "estimated_intercity_cost": 320,
                        "estimated_local_transport_cost": 60,
                        "summary": "Rail is the best fit for this itinerary and budget.",
                        "recommended_option": "Osaka to Kyoto Station by rail",
                        "booking_required": True,
                        "official_booking_url": "https://rail.example.test/kyoto",
                        "booking_window": "Reserve early during peak periods",
                        "reminders": ["Reserve seats ahead of peak departures."],
                        "notes": ["Use the operator booking page first."],
                        "source_urls": ["https://rail.example.test/kyoto"],
                    }
                )
            if self.name == "itinerary_planner":
                assert "attractions" in prompt
                assert "weather" in prompt
                assert "hotels" in prompt
                assert "transport" in prompt
                parsed = json.loads(prompt)
                attractions = parsed["attractions"]
                hotels = parsed["hotels"]
                transport = parsed["transport"]
                assert "crowd_notes" not in attractions
                assert len(attractions["featured_pois"]) <= 6
                assert len(hotels["hotel_candidates"]) <= 4
                assert len(transport["intercity_options"]) <= 3
                return json.dumps(
                    {
                        "summary": "Two Kyoto days coordinated across attractions, weather, and hotel strategy.",
                        "total_budget_estimate": 4700,
                        "risks": ["Popular sites may require early arrival."],
                        "days": [
                            {
                                "title": "2026-04-14 | East Kyoto",
                                "summary": "Temple-heavy first day.",
                                "total_cost": 2300,
                                "items": [
                                    {
                                        "type": "sight",
                                        "name": "Ginkaku-ji",
                                        "start_time": "09:00",
                                        "end_time": "11:00",
                                        "location": "Kyoto",
                                        "score": 0.9,
                                        "note": "Start calm and scenic.",
                                    },
                                    {
                                        "type": "meal",
                                        "name": "Lunch along Philosopher's Path",
                                        "start_time": "12:00",
                                        "end_time": "13:30",
                                        "location": "Kyoto",
                                        "score": 0.82,
                                        "note": "Cafe stop near the walking route.",
                                    },
                                ],
                            },
                            {
                                "title": "2026-04-15 | Central Kyoto",
                                "summary": "Market and slow afternoon.",
                                "total_cost": 2400,
                                "items": [
                                    {
                                        "type": "food",
                                        "name": "Nishiki Market brunch",
                                        "start_time": "10:00",
                                        "end_time": "12:00",
                                        "location": "Kyoto",
                                        "score": 0.84,
                                        "note": "Flexible food crawl.",
                                    },
                                    {
                                        "type": "explore",
                                        "name": "Kamo River slow walk",
                                        "start_time": "14:00",
                                        "end_time": "16:30",
                                        "location": "Kyoto",
                                        "score": 0.81,
                                        "note": "Keep the afternoon light.",
                                    },
                                ],
                            },
                        ],
                    }
                )
            raise AssertionError(f"Unexpected agent role: {self.name}")

    class FakeModule:
        SimpleAgent = FakeSimpleAgent

    return FakeModule



def test_helloagents_orchestrator_raises_when_package_is_unavailable(monkeypatch):
    monkeypatch.setattr(helloagents_module, "import_module", lambda _: (_ for _ in ()).throw(ModuleNotFoundError("hello_agents")))
    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    with pytest.raises(ModuleNotFoundError):
        orchestrator.plan_trip(_planning_request())



def test_helloagents_orchestrator_returns_business_specialist_result(monkeypatch):
    calls: list[str] = []
    llm_by_role: dict[str, dict[str, object]] = {}
    monkeypatch.setattr(helloagents_module, "import_module", lambda _: _fake_helloagents_module(calls, llm_by_role=llm_by_role))
    config = LlmConfig.from_mapping(
        {
            "base_url": "https://default.example.test/v1",
            "api_key": "default-key",
            "model": "gpt-default",
            "wire_api": "responses",
            "role_overrides": {
                "attraction_specialist": {
                    "base_url": "https://attractions.example.test/v1",
                    "model": "gpt-attractions",
                },
                "hotel_specialist": {
                    "base_url": "https://hotels.example.test/v1",
                    "api_key": "hotel-key",
                    "model": "gpt-hotels",
                },
            },
        }
    )
    assert config is not None
    orchestrator = HelloAgentsOrchestrator(config, maps_provider=StubMapsPoiProvider())

    result = orchestrator.plan_trip(_planning_request())

    assert isinstance(result, PlanningResult)
    assert result.trace.provider == "helloagents-poc"
    assert result.days[0].items[0].location_ref is not None
    assert result.days[0].items[1].route_from_previous is not None
    assert calls[0] == "brief_parser"
    assert calls[-1] == "itinerary_planner"
    assert set(calls[1:5]) == {"attraction_specialist", "weather_specialist", "hotel_specialist", "transport_specialist"}
    assert llm_by_role["attraction_specialist"]["base_url"] == "https://attractions.example.test/v1"
    assert llm_by_role["attraction_specialist"]["model"] == "gpt-attractions"
    assert llm_by_role["weather_specialist"]["base_url"] == "https://default.example.test/v1"
    assert llm_by_role["hotel_specialist"]["base_url"] == "https://hotels.example.test/v1"
    assert llm_by_role["hotel_specialist"]["api_key"] == "hotel-key"
    assert llm_by_role["transport_specialist"]["base_url"] == "https://default.example.test/v1"
    assert len(result.trace.agent_runs) == 6
    assert all(run.prompt_version for run in result.trace.agent_runs)
    assert any("business-specialist" in note.lower() for note in result.trace.notes)
    assert any("not a live forecast feed" in note.lower() for note in result.trace.notes)
    assert result.days[0].items[0].booking_info is not None
    assert result.days[0].items[0].booking_info.official_booking_url == "https://www.city.kyoto.lg.jp/official/ginkakuji"
    assert result.days[0].items[0].visit_requirements is not None
    assert result.transport_booking_summary is not None
    assert result.transport_booking_summary.official_booking_url == "https://rail.example.test/kyoto"
    assert result.transport_booking_summary.booking_required is True
    assert result.budget_summary is not None
    assert result.budget_summary.breakdown.tickets >= 25



def test_helloagents_orchestrator_uses_transport_guidance_to_override_budget_breakdown(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(helloagents_module, "import_module", lambda _: _fake_helloagents_module(calls))
    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator.plan_trip(_planning_request())

    assert result.trace.transport_guidance is not None
    assert result.trace.transport_guidance["estimated_intercity_cost"] == 320
    assert result.trace.transport_guidance["estimated_local_transport_cost"] == 60
    assert result.budget_summary is not None
    assert result.budget_summary.breakdown.transport == 380
    assert result.budget_summary.estimated_total >= result.budget_summary.breakdown.transport
    assert any(item.key == "trip_transport_intercity" for item in result.budget_summary.line_items)
    assert any(item.key == "trip_transport_local" for item in result.budget_summary.line_items)


def test_budgeting_classifies_grounded_prices_by_item_type(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(helloagents_module, "import_module", lambda _: _fake_helloagents_module(calls))
    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator.plan_trip(_planning_request())

    assert result.budget_summary is not None
    assert result.budget_summary.breakdown.tickets < result.budget_summary.breakdown.dining
    assert result.budget_summary.breakdown.tickets < result.budget_summary.breakdown.accommodation
    assert result.budget_summary.breakdown.transport == 380


def test_helloagents_orchestrator_fails_when_specialist_role_fails(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        helloagents_module,
        "import_module",
        lambda _: _fake_helloagents_module(calls, failing_role="weather_specialist"),
    )
    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    with pytest.raises(RuntimeError, match="weather_specialist"):
        orchestrator.plan_trip(_planning_request())
    assert calls[0] == "brief_parser"
    assert "weather_specialist" in calls
    assert "itinerary_planner" not in calls

def _zh_planning_request() -> PlanningRequest:
    return _planning_request().model_copy(
        update={
            "title": "\u4eac\u90fd\u6162\u8282\u594f\u4e24\u65e5",
            "origin": "\u4e0a\u6d77",
            "destination": "\u4eac\u90fd",
            "interests": ["\u5bfa\u5e99", "\u5496\u5561"],
            "accommodation_preference": "\u5b89\u9759\u7cbe\u54c1\u9152\u5e97",
            "locale": "zh-CN",
        }
    )



def test_openai_compatible_orchestrator_warns_when_chinese_output_is_not_localized():
    captured_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        captured_payloads.append(payload)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "summary": "Two Kyoto days focused on temples and coffee.",
                                    "total_budget_estimate": 4700,
                                    "risks": ["Popular sites may require early arrival."],
                                    "days": [
                                        {
                                            "title": "2026-04-14 | East Kyoto",
                                            "summary": "Temple-heavy first day.",
                                            "total_cost": 2300,
                                            "items": [
                                                {
                                                    "type": "sight",
                                                    "name": "Ginkaku-ji",
                                                    "start_time": "09:00",
                                                    "end_time": "11:00",
                                                    "location": "Kyoto",
                                                    "score": 0.9,
                                                    "note": "Start calm and scenic.",
                                                },
                                                {
                                                    "type": "meal",
                                                    "name": "Lunch along Philosopher's Path",
                                                    "start_time": "12:00",
                                                    "end_time": "13:30",
                                                    "location": "Kyoto",
                                                    "score": 0.82,
                                                    "note": "Cafe stop near the walking route.",
                                                },
                                            ],
                                        },
                                        {
                                            "title": "2026-04-15 | Central Kyoto",
                                            "summary": "Market and slow afternoon.",
                                            "total_cost": 2400,
                                            "items": [
                                                {
                                                    "type": "food",
                                                    "name": "Nishiki Market brunch",
                                                    "start_time": "10:00",
                                                    "end_time": "12:00",
                                                    "location": "Kyoto",
                                                    "score": 0.84,
                                                    "note": "Flexible food crawl.",
                                                },
                                                {
                                                    "type": "explore",
                                                    "name": "Kamo River slow walk",
                                                    "start_time": "14:00",
                                                    "end_time": "16:30",
                                                    "location": "Kyoto",
                                                    "score": 0.81,
                                                    "note": "Keep the afternoon light.",
                                                },
                                            ],
                                        },
                                    ],
                                }
                            ),
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    config = LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="chat_completions")
    client = OpenAICompatibleClient(config, http_client=http_client)
    orchestrator = OpenAICompatibleOrchestrator(config, llm_client=client, maps_provider=StubMapsPoiProvider())

    try:
        result = orchestrator.plan_trip(_zh_planning_request())
    finally:
        http_client.close()

    assert len(captured_payloads) == 1
    assert result.summary.startswith("Two Kyoto days")
    assert any("did not fully match the requested locale" in note for note in result.trace.notes)


def test_helloagents_orchestrator_warns_when_weather_guidance_locale_mismatches(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(helloagents_module, "import_module", lambda _: _fake_helloagents_module(calls))
    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator.plan_trip(_zh_planning_request())

    assert result.days[0].weather is not None
    assert "cool" in result.days[0].weather.summary.casefold()
    assert any("Weather specialist output did not fully match the requested locale" in note for note in result.trace.notes)




def test_helloagents_orchestrator_attaches_weather_citations(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(helloagents_module, "import_module", lambda _: _fake_helloagents_module(calls))
    monkeypatch.setattr(
        HelloAgentsOrchestrator,
        "_build_role_mcp_client",
        lambda self, role_name: object() if role_name == "weather_specialist" else None,
    )
    monkeypatch.setattr(
        HelloAgentsOrchestrator,
        "_available_mcp_tools",
        lambda self, role_name, client: {"answer"} if role_name == "weather_specialist" else set(),
    )
    monkeypatch.setattr(
        HelloAgentsOrchestrator,
        "_call_search_like_tool",
        lambda self, client, tool_name, query, num_results, *, role_name: {
            "answer": "Mock weather answer",
            "results": [
                {"url": "https://weather.example.test/forecast"},
                {"url": "https://weather.example.test/advisory"},
            ],
        },
    )

    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator.plan_trip(_planning_request())

    weather_run = next(run for run in result.trace.agent_runs if run.key == "weather_specialist")
    assert "https://weather.example.test/forecast" in weather_run.citations
    assert "https://weather.example.test/advisory" in weather_run.citations
    assert result.days[0].weather is not None
    assert result.days[0].weather.citations == [
        "https://weather.example.test/forecast",
        "https://weather.example.test/advisory",
    ]



def test_helloagents_orchestrator_embeds_daily_weather_into_days(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(helloagents_module, "import_module", lambda _: _fake_helloagents_module(calls))
    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator.plan_trip(_planning_request())

    assert result.days[0].weather is not None
    assert result.days[0].weather.summary.startswith("Day 1:")
    assert result.days[0].weather.notes
    assert result.days[1].weather is not None
    assert result.days[1].weather.summary.startswith("Day 2:")



def test_helloagents_orchestrator_adds_grounding_links_to_agent_citations_and_temperature_to_day_weather(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(helloagents_module, "import_module", lambda _: _fake_helloagents_module(calls))

    def fake_augment(self, role_name, input_payload):
        del self
        if role_name == "attraction_specialist":
            input_payload["tool_results"] = {
                "grounding_docs": [
                    {"url": "https://www.xiaohongshu.com/explore/attraction-post"},
                    {"url": "https://official.example.test/guide"},
                ]
            }
        elif role_name == "hotel_specialist":
            input_payload["tool_results"] = {
                "grounding_docs": [
                    {"url": "https://www.xiaohongshu.com/explore/hotel-post"},
                ],
                "crawl_urls": ["https://hotel.example.test/detail"],
            }
        elif role_name == "weather_specialist":
            input_payload["tool_results"] = {
                "citations": ["https://weather.example.test/forecast"],
                "answer": {
                    "text": "Forecast temperatures around 24?C to 30?C with afternoon rain risk.",
                },
            }
        elif role_name == "transport_specialist":
            input_payload["tool_results"] = {
                "citations": ["https://transport.example.test/rail-fares"],
                "grounding_docs": [
                    {"url": "https://transport.example.test/rail-fares"},
                ],
            }
        return input_payload

    monkeypatch.setattr(HelloAgentsOrchestrator, "_augment_payload_with_tool_results", fake_augment)
    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator.plan_trip(_planning_request())

    attraction_run = next(run for run in result.trace.agent_runs if run.key == "attraction_specialist")
    hotel_run = next(run for run in result.trace.agent_runs if run.key == "hotel_specialist")
    transport_run = next(run for run in result.trace.agent_runs if run.key == "transport_specialist")

    assert "https://www.xiaohongshu.com/explore/attraction-post" in attraction_run.citations
    assert "https://www.xiaohongshu.com/explore/hotel-post" in hotel_run.citations
    assert "https://hotel.example.test/detail" in hotel_run.citations
    assert "https://transport.example.test/rail-fares" in transport_run.citations
    assert result.days[0].weather is not None
    assert "24" in result.days[0].weather.summary



def test_helloagents_build_day_weather_uses_tool_temperature_hint_when_daily_outlook_omits_it():
    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    weather_guidance = helloagents_module.HelloAgentsWeatherGuidance(
        overall_outlook="Mild spring weather with occasional rain.",
        daily_outlook=["Day 1: light rain risk after lunch."],
        packing_notes=["Carry a compact umbrella."],
        timing_guidance=["Outdoor walks fit best before noon."],
        weather_risks=["Brief showers may disrupt exposed stops."],
    )

    day_weather = orchestrator._build_day_weather(
        1,
        weather_guidance,
        ["https://weather.example.test/forecast"],
        {"answer": {"text": "Temperatures around 18?C to 24?C with light rain risk."}},
    )

    assert day_weather is not None
    assert "18" in day_weather.summary



def test_helloagents_weather_tool_results_use_deep_research_when_available(monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_call(self, client, tool_name, arguments, *, role_name):
        del self, client, role_name
        calls.append((tool_name, arguments))
        if tool_name == "deep_researcher_start":
            return {"researchId": "research_123", "status": "running"}
        if tool_name == "deep_researcher_check":
            return {
                "researchId": "research_123",
                "status": "completed",
                "sources": [{"url": "https://weather.example.test/forecast"}],
                "report": "Cool mornings with a light rain risk.",
            }
        raise AssertionError(f"Unexpected MCP tool: {tool_name}")

    monkeypatch.setattr(HelloAgentsOrchestrator, "_call_mcp_tool", fake_call)
    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator._collect_weather_tool_results(
        object(),
        {"deep_researcher_start", "deep_researcher_check"},
        {"trip_request": {"destination": "Kyoto", "start_date": "2026-04-14", "end_date": "2026-04-15"}},
    )

    assert result["research_tool"] == "deep_researcher_start"
    assert [name for name, _ in calls] == ["deep_researcher_start", "deep_researcher_check"]
    assert "https://weather.example.test/forecast" in result["citations"]



def test_helloagents_deep_search_uses_official_objective_schema(monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_call(self, client, tool_name, arguments, *, role_name):
        del self, client, role_name
        calls.append((tool_name, arguments))
        return {"answer": "mock deep search"}

    monkeypatch.setattr(HelloAgentsOrchestrator, "_call_mcp_tool", fake_call)
    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    orchestrator._call_search_like_tool(
        object(),
        "deep_search_exa",
        "Travel weather guidance for Kyoto between 2026-04-14 and 2026-04-15",
        5,
        role_name="weather_specialist",
    )

    assert calls == [
        (
            "deep_search_exa",
            {
                "objective": "Travel weather guidance for Kyoto between 2026-04-14 and 2026-04-15",
                "type": "deep",
                "numResults": 5,
            },
        )
    ]


def test_helloagents_hotel_tool_results_crawl_top_search_urls_when_available(monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_call(self, client, tool_name, arguments, *, role_name):
        del self, client, role_name
        calls.append((tool_name, arguments))
        if tool_name == "web_search_exa":
            return {
                "results": [
                    {"url": "https://stay.example.test/hotel-alpha", "title": "Hotel Alpha"},
                    {"url": "https://stay.example.test/hotel-beta", "title": "Hotel Beta"},
                ]
            }
        if tool_name == "crawling_exa":
            return {
                "results": [
                    {"url": "https://stay.example.test/hotel-alpha", "text": "Transit-friendly stay."},
                    {"url": "https://stay.example.test/hotel-beta", "text": "Quiet boutique option."},
                ]
            }
        raise AssertionError(f"Unexpected MCP tool: {tool_name}")

    monkeypatch.setattr(HelloAgentsOrchestrator, "_call_mcp_tool", fake_call)
    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator._collect_hotel_tool_results(
        object(),
        {"web_search_exa", "crawling_exa"},
        {
            "trip_request": {"destination": "Kyoto", "accommodation_preference": "Quiet boutique hotel"},
            "planning_brief": {"destination": "Kyoto", "accommodation": "Quiet boutique hotel"},
            "candidate_hotels": [{"name": "Hotel Alpha"}, {"name": "Hotel Beta"}],
        },
    )

    assert result["search_tool"] == "web_search_exa"
    assert result["crawl_tool"] == "crawling_exa"
    assert result["crawl_urls"] == [
        "https://stay.example.test/hotel-alpha",
        "https://stay.example.test/hotel-beta",
    ]
    assert [name for name, _ in calls] == ["web_search_exa", "crawling_exa"]



def test_helloagents_attraction_tool_results_include_grounding_docs(monkeypatch):
    monkeypatch.setattr(
        helloagents_module,
        "search_documents",
        lambda query, destination, manual_links, *, interests=None, social_context="general", search_service_config=None, xhs_source_enabled=True, xhs_user_id=None: [
            SearchDocumentResponse(
                id="src_1",
                platform="xiaohongshu",
                title="Kyoto quiet walk",
                url="https://www.xiaohongshu.com/explore/xhs_1",
                summary="Local quiet walk guide.",
                destination=destination,
                place_name="Kyoto",
                category="social-guide",
                source_type="social-guide-post",
                scores=ScoreBreakdown(
                    trust_score=0.78,
                    quality_score=0.8,
                    freshness_score=0.9,
                    ad_score=0.14,
                    final_score=0.8,
                    reasons=["Local traveler-generated guide"],
                ),
            )
        ],
    )
    monkeypatch.setattr(
        HelloAgentsOrchestrator,
        "_call_search_like_tool",
        lambda self, client, tool_name, query, num_results, *, role_name: {"results": [{"url": "https://example.test/a"}]},
    )
    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator._collect_attraction_tool_results(
        object(),
        {"web_search_exa"},
        {
            "trip_request": {"destination": "Kyoto", "pace": "balanced"},
            "planning_brief": {"destination": "Kyoto", "must_have": ["coffee"]},
        },
    )

    assert result["grounding_docs"][0]["platform"] == "xiaohongshu"



def test_helloagents_hotel_tool_results_include_grounding_docs(monkeypatch):
    monkeypatch.setattr(
        helloagents_module,
        "search_documents",
        lambda query, destination, manual_links, *, interests=None, social_context="general", search_service_config=None, xhs_source_enabled=True, xhs_user_id=None: [
            SearchDocumentResponse(
                id="src_1",
                platform="xiaohongshu",
                title="Kyoto hotel district guide",
                url="https://www.xiaohongshu.com/explore/xhs_hotel",
                summary="Stay near Kyoto Station.",
                destination=destination,
                place_name="Kyoto Station",
                category="social-guide",
                source_type="social-guide-post",
                scores=ScoreBreakdown(
                    trust_score=0.78,
                    quality_score=0.8,
                    freshness_score=0.9,
                    ad_score=0.14,
                    final_score=0.8,
                    reasons=["Local traveler-generated guide"],
                ),
            )
        ],
    )
    monkeypatch.setattr(
        HelloAgentsOrchestrator,
        "_call_mcp_tool",
        lambda self, client, tool_name, arguments, *, role_name: {"results": [{"url": "https://stay.example.test/hotel-alpha"}]},
    )
    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator._collect_hotel_tool_results(
        object(),
        {"web_search_exa", "crawling_exa"},
        {
            "trip_request": {"destination": "Kyoto", "accommodation_preference": "Quiet boutique hotel"},
            "planning_brief": {"destination": "Kyoto", "accommodation": "Quiet boutique hotel"},
            "candidate_hotels": [{"name": "Hotel Alpha"}],
        },
    )

    assert result["grounding_docs"][0]["platform"] == "xiaohongshu"



def test_helloagents_weather_tool_results_do_not_include_social_grounding(monkeypatch):
    monkeypatch.setattr(
        helloagents_module,
        "search_documents",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("weather should not request social grounding")),
    )
    monkeypatch.setattr(
        HelloAgentsOrchestrator,
        "_call_search_like_tool",
        lambda self, client, tool_name, query, num_results, *, role_name: {"answer": "Mock weather answer", "results": []},
    )
    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator._collect_weather_tool_results(
        object(),
        {"answer"},
        {"trip_request": {"destination": "Kyoto", "start_date": "2026-04-14", "end_date": "2026-04-15"}},
    )

    assert "grounding_docs" not in result


def test_helloagents_attraction_tool_results_use_groksearch_web_fetch(monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        helloagents_module,
        "search_documents",
        lambda query, destination, manual_links, *, interests=None, social_context="general", search_service_config=None, xhs_source_enabled=True: [],
    )

    def fake_call(self, client, tool_name, arguments, *, role_name):
        del self, client, role_name
        calls.append((tool_name, arguments))
        if tool_name == "web_search":
            return {
                "sources": [
                    {"url": "https://example.test/a", "title": "Guide A"},
                    {"url": "https://example.test/b", "title": "Guide B"},
                ]
            }
        if tool_name == "web_fetch":
            return {"text": "Grounded attraction details."}
        raise AssertionError(f"Unexpected MCP tool: {tool_name}")

    monkeypatch.setattr(HelloAgentsOrchestrator, "_call_mcp_tool", fake_call)
    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator._collect_attraction_tool_results(
        SimpleNamespace(config=SearchServiceConfig(provider="groksearch", transport="mcp", base_url="https://groksearch.example.test/mcp", api_key="test-key")),
        {"web_search", "web_fetch"},
        {
            "trip_request": {"destination": "Kyoto", "pace": "balanced"},
            "planning_brief": {"destination": "Kyoto", "must_have": ["coffee"]},
        },
    )

    assert result["search_tool"] == "web_search"
    assert result["crawl_tool"] == "web_fetch"
    assert result["crawl_urls"] == [
        "https://example.test/a",
        "https://example.test/b",
    ]
    assert [name for name, _ in calls] == ["web_search", "web_fetch", "web_fetch"]


def test_helloagents_weather_tool_results_use_groksearch_web_search(monkeypatch):
    monkeypatch.setattr(
        HelloAgentsOrchestrator,
        "_call_search_like_tool",
        lambda self, client, tool_name, query, num_results, *, role_name: {
            "session_id": "session_123",
            "content": "Cool mornings with light rain risk.",
            "sources": [{"url": "https://weather.example.test/forecast"}],
        },
    )
    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator._collect_weather_tool_results(
        SimpleNamespace(config=SearchServiceConfig(provider="groksearch", transport="mcp", base_url="https://groksearch.example.test/mcp", api_key="test-key")),
        {"web_search", "get_sources"},
        {"trip_request": {"destination": "Kyoto", "start_date": "2026-04-14", "end_date": "2026-04-15"}},
    )

    assert result["research_tool"] == "web_search"
    assert result["citations"] == ["https://weather.example.test/forecast"]


def test_helloagents_hotel_tool_results_use_groksearch_web_fetch(monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_call(self, client, tool_name, arguments, *, role_name):
        del self, client, role_name
        calls.append((tool_name, arguments))
        if tool_name == "web_search":
            return {
                "sources": [
                    {"url": "https://stay.example.test/hotel-alpha", "title": "Hotel Alpha"},
                    {"url": "https://stay.example.test/hotel-beta", "title": "Hotel Beta"},
                ]
            }
        if tool_name == "web_fetch":
            return {"text": "Transit-friendly stay."}
        raise AssertionError(f"Unexpected MCP tool: {tool_name}")

    monkeypatch.setattr(HelloAgentsOrchestrator, "_call_mcp_tool", fake_call)
    monkeypatch.setattr(
        helloagents_module,
        "search_documents",
        lambda query, destination, manual_links, *, interests=None, social_context="general", search_service_config=None, xhs_source_enabled=True: [],
    )
    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator._collect_hotel_tool_results(
        SimpleNamespace(config=SearchServiceConfig(provider="groksearch", transport="mcp", base_url="https://groksearch.example.test/mcp", api_key="test-key")),
        {"web_search", "web_fetch"},
        {
            "trip_request": {"destination": "Kyoto", "accommodation_preference": "Quiet boutique hotel"},
            "planning_brief": {"destination": "Kyoto", "accommodation": "Quiet boutique hotel"},
            "candidate_hotels": [{"name": "Hotel Alpha"}, {"name": "Hotel Beta"}],
        },
    )

    assert result["search_tool"] == "web_search"
    assert result["crawl_tool"] == "web_fetch"
    assert result["crawl_urls"] == [
        "https://stay.example.test/hotel-alpha",
        "https://stay.example.test/hotel-beta",
    ]
    assert [name for name, _ in calls] == ["web_search", "web_fetch", "web_fetch"]


def test_helloagents_transport_tool_results_use_groksearch_web_fetch(monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_call(self, client, tool_name, arguments, *, role_name):
        del self, client, role_name
        calls.append((tool_name, arguments))
        if tool_name == "web_search":
            return {
                "sources": [
                    {"url": "https://transport.example.test/rail-fares", "title": "Rail fares"},
                    {"url": "https://transport.example.test/local-pass", "title": "Local pass"},
                ]
            }
        if tool_name == "web_fetch":
            return {"text": "Grounded transport pricing."}
        raise AssertionError(f"Unexpected MCP tool: {tool_name}")

    monkeypatch.setattr(HelloAgentsOrchestrator, "_call_mcp_tool", fake_call)
    monkeypatch.setattr(
        helloagents_module,
        "search_documents",
        lambda query, destination, manual_links, *, interests=None, social_context="general", search_service_config=None, xhs_source_enabled=True: [],
    )
    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator._collect_transport_tool_results(
        SimpleNamespace(config=SearchServiceConfig(provider="groksearch", transport="mcp", base_url="https://groksearch.example.test/mcp", api_key="test-key")),
        {"web_search", "web_fetch"},
        {
            "trip_request": {
                "origin": "Osaka",
                "destination": "Kyoto",
                "start_date": "2026-04-14",
                "end_date": "2026-04-15",
                "transport_mode": "rail",
                "travelers": 2,
            },
            "planning_brief": {"destination": "Kyoto", "transport": "rail"},
            "transport_context": {"transport_mode": "rail"},
        },
    )

    assert result["search_tool"] == "web_search"
    assert result["crawl_tool"] == "web_fetch"
    assert result["crawl_urls"] == [
        "https://transport.example.test/rail-fares",
        "https://transport.example.test/local-pass",
    ]
    assert result["citations"] == [
        "https://transport.example.test/rail-fares",
        "https://transport.example.test/local-pass",
    ]
    assert [name for name, _ in calls] == ["web_search", "web_fetch", "web_fetch"]



def test_helloagents_extract_urls_from_text_payload():
    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    urls = orchestrator._extract_urls_from_search_result(
        {
            "text": "Title: Example\nURL: https://example.com/one\nMore text https://example.com/two?ref=travel."
        }
    )

    assert urls == ["https://example.com/one", "https://example.com/two?ref=travel"]


def test_helloagents_orchestrator_warns_when_chinese_final_payload_is_not_localized(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(helloagents_module, "import_module", lambda _: _fake_helloagents_module(calls))
    orchestrator = HelloAgentsOrchestrator(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator.plan_trip(_zh_planning_request())

    assert result.summary.startswith("Two Kyoto days")
    assert any("Itinerary planner output did not fully match the requested locale" in note for note in result.trace.notes)


def test_parse_planning_response_unwraps_nested_itinerary_payload():
    content = json.dumps(
        {
            "target_locale": "zh-CN",
            "trip_request": {"destination": "Kyoto"},
            "rewrite_fields": ["summary"],
            "itinerary": {
                "summary": "两天京都行程。",
                "total_budget_estimate": 4700,
                "risks": ["热门景点建议提早出发。"],
                "days": [
                    {
                        "title": "2026-04-14 | 京都东部",
                        "summary": "第一天以寺庙与散步为主。",
                        "total_cost": 2300,
                        "items": [
                            {
                                "type": "sight",
                                "name": "Ginkaku-ji",
                                "start_time": "09:00",
                                "end_time": "11:00",
                                "location": "Kyoto",
                                "score": 0.9,
                                "note": "先从安静的景点开始。",
                            }
                        ],
                    }
                ],
            },
        }
    )

    payload = parse_planning_response(content)

    assert payload.summary == "两天京都行程。"
    assert len(payload.days) == 1


def test_stub_orchestrator_localizes_output_for_chinese_requests():
    orchestrator = StubOrchestrator(maps_provider=StubMapsPoiProvider())
    result = orchestrator.plan_trip(_zh_planning_request())

    assert "\u5929\u884c\u7a0b" in result.summary
    assert "\u4ece\u4e0a\u4e00\u7ad9\u8f6c\u79fb\u5230\u8fd9\u91cc\u7ea6" in result.days[0].items[1].note


def test_openai_compatible_orchestrator_refine_uses_current_itinerary_context():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "summary": "Refined Kyoto plan with a slower second day.",
                                    "total_budget_estimate": 4700,
                                    "risks": ["Popular sites may require early arrival."],
                                    "days": [
                                        {
                                            "title": "2026-04-14 | East Kyoto",
                                            "summary": "Temple-heavy first day.",
                                            "total_cost": 2300,
                                            "items": [
                                                {
                                                    "type": "sight",
                                                    "name": "Ginkaku-ji",
                                                    "start_time": "09:00",
                                                    "end_time": "11:00",
                                                    "location": "Kyoto",
                                                    "score": 0.9,
                                                    "note": "Start calm and scenic.",
                                                },
                                                {
                                                    "type": "meal",
                                                    "name": "Lunch along Philosopher's Path",
                                                    "start_time": "12:00",
                                                    "end_time": "13:30",
                                                    "location": "Kyoto",
                                                    "score": 0.82,
                                                    "note": "Cafe stop near the walking route.",
                                                },
                                            ],
                                        },
                                        {
                                            "title": "2026-04-15 | Central Kyoto",
                                            "summary": "Slower market and riverside afternoon.",
                                            "total_cost": 2400,
                                            "items": [
                                                {
                                                    "type": "food",
                                                    "name": "Nishiki Market brunch",
                                                    "start_time": "10:30",
                                                    "end_time": "12:00",
                                                    "location": "Kyoto",
                                                    "score": 0.84,
                                                    "note": "Flexible food crawl.",
                                                },
                                                {
                                                    "type": "explore",
                                                    "name": "Kamo River slow walk",
                                                    "start_time": "14:00",
                                                    "end_time": "16:30",
                                                    "location": "Kyoto",
                                                    "score": 0.81,
                                                    "note": "End with a slower riverside walk.",
                                                },
                                            ],
                                        },
                                    ],
                                }
                            ),
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    config = LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="chat_completions")
    client = OpenAICompatibleClient(config, http_client=http_client)
    orchestrator = OpenAICompatibleOrchestrator(config, llm_client=client, maps_provider=StubMapsPoiProvider())
    current_plan = StubOrchestrator(maps_provider=StubMapsPoiProvider()).plan_trip(_planning_request())

    try:
        result = orchestrator.refine_trip(
            _planning_request(),
            current_plan,
            instruction="Make day 2 quieter and slower.",
            scope="day_plan",
            day_index=2,
        )
    finally:
        http_client.close()

    assert isinstance(result, PlanningResult)
    messages = captured["payload"]["messages"]
    assert messages[0]["role"] == "system"
    assert "current itinerary" in messages[0]["content"].lower()
    assert "current_itinerary" in messages[1]["content"]
    assert "Make day 2 quieter and slower." in messages[1]["content"]
    assert result.summary.startswith("Refined Kyoto plan")
