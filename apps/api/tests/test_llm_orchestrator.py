import json
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
import travelmind_api.agents.planning_core as planning_core_module

from travelmind_api.agents.base import (
    AgentTrace,
    BookingInfo,
    PlannedDay,
    PlannedItem,
    PlanningRequest,
    PlanningResult,
    TransportBookingSummary,
)
from travelmind_api.agents.factory import build_orchestrator
from travelmind_api.agents.planning_core import PlanningCore, PlanningRoleConfig
from travelmind_api.services.planning.role_models import (
    PlanningBrief,
    HotelCandidate,
    HotelRecommendation,
    PoiGrounding,
    TransportGuidance,
)
from travelmind_api.agents.langgraph_orchestrator import LangGraphOrchestrator
from travelmind_api.agents.openai_compatible import OpenAICompatibleOrchestrator
from travelmind_api.agents.stub import StubOrchestrator
from travelmind_api.api.schemas.search import ScoreBreakdown, SearchDocumentResponse
from travelmind_api.core.config import Settings
from travelmind_api.prompts.roles.planning import (
    build_hotel_specialist_prompt,
    build_poi_specialist_prompt,
    build_weather_specialist_prompt,
)
from travelmind_api.services.llm import LlmConfig, OpenAICompatibleClient
from travelmind_api.services.llm.parser import parse_planning_response
from travelmind_api.services.maps import StubMapsPoiProvider
from travelmind_api.services.search_connector import SearchServiceConfig
from travelmind_api.services.budgeting import enrich_plan_with_budget



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


def test_openai_compatible_client_supports_streaming_chat_completions_payload():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = OpenAICompatibleClient(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="chat_completions"),
        http_client=http_client,
    )

    try:
        response = client.create_chat_completion(
            messages=[{"role": "user", "content": "hello"}],
            stream=True,
        )
    finally:
        http_client.close()

    assert response == "hello"
    assert captured["payload"]["stream"] is True


def test_openai_compatible_client_forces_streaming_for_grok_models():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = OpenAICompatibleClient(
        LlmConfig(base_url="https://poi.example.test/v1", api_key="test-key", model="grok-4.20-multi-agent-medium", wire_api="chat_completions"),
        http_client=http_client,
    )

    try:
        response = client.create_chat_completion(messages=[{"role": "user", "content": "hello"}])
    finally:
        http_client.close()

    assert response == "ok"
    assert captured["payload"]["stream"] is True



def test_openai_compatible_orchestrator_uses_chat_completions(monkeypatch):
    monkeypatch.setenv("TRAVELMIND_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("TRAVELMIND_LLM_API_KEY", "test-key")
    monkeypatch.setenv("TRAVELMIND_LLM_MODEL", "gpt-test")
    monkeypatch.setenv("TRAVELMIND_LLM_WIRE_API", "chat_completions")
    monkeypatch.setenv("TRAVELMIND_LLM_PROVIDER_PROTOCOL", "newapi")

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


def test_openai_compatible_client_retries_responses_504_with_streaming():
    captured_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        captured_payloads.append(payload)
        if len(captured_payloads) == 1:
            return httpx.Response(504, json={"error": {"message": "Gateway Timeout"}})
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'data: {"type":"response.output_text.delta","delta":"stream"}\n\n'
                'data: {"type":"response.output_text.delta","delta":" ok"}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = OpenAICompatibleClient(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        http_client=http_client,
    )

    try:
        response = client.create_chat_completion(messages=[{"role": "user", "content": "hello"}])
    finally:
        http_client.close()

    assert response == "stream ok"
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


def test_openai_compatible_client_retries_streaming_once_after_http2_internal_error():
    captured_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        captured_payloads.append(payload)
        if len(captured_payloads) == 1:
            raise httpx.ReadError(
                "Failed to perform, curl: (92) HTTP/2 stream 1 was not closed cleanly: INTERNAL_ERROR (err 2).",
                request=request,
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'data: {"choices":[{"delta":{"content":"retry"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":" ok"}}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = OpenAICompatibleClient(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="grok-test", wire_api="chat_completions"),
        http_client=http_client,
    )

    try:
        response = client.create_chat_completion(
            messages=[{"role": "user", "content": "hello"}],
            stream=True,
        )
    finally:
        http_client.close()

    assert response == "retry ok"
    assert len(captured_payloads) == 2
    assert captured_payloads[0]["stream"] is True
    assert captured_payloads[1]["stream"] is True


















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
                "poi_specialist": {
                    "base_url": "https://poi.example.test/v1",
                    "model": "gpt-poi",
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
    assert config.config_for_role("poi_specialist").base_url == "https://poi.example.test/v1"
    assert config.config_for_role("poi_specialist").api_key == "default-key"
    assert config.config_for_role("poi_specialist").model == "gpt-poi"
    assert config.config_for_role("weather_specialist").base_url == "https://default.example.test/v1"
    assert config.config_for_role("hotel_specialist").api_key == "hotel-key"


def test_llm_config_uses_grok_env_for_direct_search_specialists(monkeypatch):
    monkeypatch.setenv("GROK_API_URL", "https://api.x.ai/v1")
    monkeypatch.setenv("GROK_API_KEY", "grok-key")
    monkeypatch.setenv("GROK_MODEL", "grok-4.20-beta")

    config = LlmConfig.from_mapping(
        {
            "base_url": "https://default.example.test/v1",
            "api_key": "default-key",
            "model": "gpt-default",
            "wire_api": "responses",
        }
    )

    assert config is not None
    for role_name in ("weather_specialist", "hotel_specialist", "transport_specialist"):
        role_config = config.config_for_role(role_name)
        assert role_config.base_url == "https://api.x.ai/v1"
        assert role_config.api_key == "grok-key"
        assert role_config.model == "grok-4.20-beta"
        assert role_config.provider_protocol == "newapi"
        assert role_config.wire_api == "chat_completions"
    assert config.config_for_role("poi_specialist").model == "gpt-default"


def test_llm_config_can_source_poi_override_from_user_mapping():
    config = LlmConfig.from_mapping(
        {
            "base_url": "https://default.example.test/v1",
            "api_key": "default-key",
            "model": "gpt-default",
            "wire_api": "responses",
            "provider_protocol": "openai",
            "role_overrides": {
                "poi_specialist": {
                    "base_url": "https://poi.example.test/v1",
                    "api_key": "poi-key",
                    "model": "grok-4.20-multi-agent-xhigh",
                    "wire_api": "chat_completions",
                    "provider_protocol": "newapi",
                }
            },
        }
    )

    assert config is not None
    poi_config = config.config_for_role("poi_specialist")
    assert poi_config.base_url == "https://poi.example.test/v1"
    assert poi_config.api_key == "poi-key"
    assert poi_config.model == "grok-4.20-multi-agent-xhigh"
    assert poi_config.wire_api == "chat_completions"
    assert poi_config.provider_protocol == "newapi"


def test_user_poi_role_override_requires_complete_saved_settings():
    from travelmind_api.services.llm.user_config import build_user_poi_role_overrides

    user = SimpleNamespace(
        poi_llm_base_url="https://old-poi.example.test/v1",
        poi_llm_api_key="poi-key",
        poi_llm_model=None,
        poi_llm_wire_api="responses",
        poi_llm_provider_protocol="openai",
    )

    assert build_user_poi_role_overrides(user) == {}

    user.poi_llm_model = "Console/grok-4.20-multi-agent-0309"
    user.weather_llm_model = "Console/grok-4.20-0309-non-reasoning"
    user.hotel_llm_model = "Console/grok-4.20-0309-reasoning"
    user.transport_llm_model = "Console/grok-4.20-0309-reasoning"
    overrides = build_user_poi_role_overrides(user)
    config = LlmConfig.from_mapping(
        {
            "base_url": "https://default.example.test/v1",
            "api_key": "default-key",
            "model": "gpt-default",
            "wire_api": "responses",
            "provider_protocol": "newapi",
            "role_overrides": overrides,
        }
    )

    assert config is not None
    assert set(overrides) == {"poi_specialist", "weather_specialist", "hotel_specialist", "transport_specialist"}
    expected_models = {
        "poi_specialist": "Console/grok-4.20-multi-agent-0309",
        "weather_specialist": "Console/grok-4.20-0309-non-reasoning",
        "hotel_specialist": "Console/grok-4.20-0309-reasoning",
        "transport_specialist": "Console/grok-4.20-0309-reasoning",
    }
    for role_name in ("poi_specialist", "weather_specialist", "hotel_specialist", "transport_specialist"):
        role_config = config.config_for_role(role_name)
        assert role_config.base_url == "https://old-poi.example.test/v1"
        assert role_config.api_key == "poi-key"
        assert role_config.model == expected_models[role_name]
        assert role_config.wire_api == "responses"
        assert role_config.provider_protocol == "openai"



def test_build_orchestrator_maps_legacy_helloagents_alias_to_langgraph():
    orchestrator = build_orchestrator(
        Settings(agent_provider="standard"),
        llm_config=LlmConfig(base_url="https://llm.override.test/v1", api_key="override-key", model="gpt-override", wire_api="responses"),
        agent_provider="helloagents",
    )

    assert isinstance(orchestrator, LangGraphOrchestrator)



def _fake_planning_core_module(
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
            if self.name == "poi_specialist":
                assert "poi_context" in prompt
                assert "candidate_pois" not in prompt
                assert "candidate_food_pois" not in prompt
                assert "poi_request" not in prompt
                return json.dumps(
                    {
                        "candidate_areas": ["Higashiyama", "Downtown Kyoto"],
                        "featured_pois": [
                            {
                                "name": "Ginkaku-ji",
                                "kind": "attraction",
                                "category": "temple",
                                "area": "Higashiyama",
                                "reason": "Calm scenic morning.",
                                "suggested_time": "morning",
                                "confidence": "high",
                                "source_urls": ["https://www.city.kyoto.lg.jp/official/ginkakuji"],
                                "evidence_notes": ["Official ticket context is available."],
                                "caveats": ["Peak foliage controls can change."],
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
                            },
                            {
                                "name": "Lunch along Philosopher's Path",
                                "kind": "food",
                                "category": "cafe lunch",
                                "area": "Higashiyama",
                                "cuisine_or_type": "cafe lunch",
                                "reason": "Works near the walking route.",
                                "suggested_time": "lunch",
                                "price_hint": "around 1,500 to 2,500 JPY per person from current search evidence",
                                "price_checked_at": "current search snapshot",
                                "price_valid_for": "2026-04-14, two travelers",
                                "review_score": "4.3/5",
                                "review_count": "500+",
                                "review_summary": "Good location and relaxed lunch feedback.",
                                "signature_dishes": ["coffee", "light lunch"],
                                "reservation_hint": "unknown",
                                "queue_hint": "short queue possible at lunch",
                                "confidence": "medium",
                                "caveats": ["Re-check opening hours before going."],
                                "source_urls": ["https://food.example.test/philosopher-cafe"],
                            },
                            {
                                "name": "Nishiki Market brunch",
                                "kind": "market",
                                "category": "market food",
                                "area": "Downtown Kyoto",
                                "cuisine_or_type": "market food",
                                "reason": "Flexible food crawl.",
                                "suggested_time": "brunch",
                                "price_hint": "unknown",
                                "price_checked_at": "unknown",
                                "review_score": "unknown",
                                "review_count": "unknown",
                                "review_summary": "Popular food market; exact stall ratings vary.",
                                "signature_dishes": ["snacks"],
                                "reservation_hint": "not usually required",
                                "queue_hint": "expect queues near noon",
                                "confidence": "low",
                                "caveats": ["Use unknown instead of invented exact ratings."],
                                "source_urls": ["https://food.example.test/nishiki"],
                            },
                        ],
                        "sequencing_hints": ["Keep East Kyoto stops together."],
                        "crowd_notes": ["Arrive early at the headline sights."],
                        "meal_strategy": ["Anchor lunches near the attraction clusters."],
                        "price_notes": ["Use unknown when source-backed prices are missing."],
                        "review_notes": ["Use recent review signals over generic popularity."],
                        "poi_risks": ["Long cross-city transfers will hurt pacing.", "Queues can affect meal timing."],
                    }
                )
            if self.name == "weather_specialist":
                assert "season_context" in prompt
                assert "weather_segments" in prompt
                return json.dumps(
                    {
                        "overall_outlook": "Cool mornings and mild afternoons with occasional light rain.",
                        "daily_outlook": ["Day 1: cool start, mild afternoon.", "Day 2: light rain risk after lunch."],
                        "segments": [
                            {
                                "name": "Kyoto",
                                "date_range": "2026-04-14 to 2026-04-15",
                                "outlook": "Mild with light rain risk.",
                                "temperature_range": "18 C to 24 C",
                                "clothing_advice": ["Carry a light layer."],
                                "outdoor_notes": ["Keep temple walks before late afternoon."],
                                "risks": ["Light rain may affect exposed paths."],
                            }
                        ],
                        "packing_notes": ["Carry a light layer.", "Bring a compact umbrella."],
                        "timing_guidance": ["Outdoor walks fit best before late afternoon."],
                        "weather_risks": ["Light rain may affect exposed temple walks."],
                    }
                )
            if self.name == "food_specialist":
                assert "candidate_food_pois" in prompt
                return json.dumps(
                    {
                        "candidate_areas": ["Downtown Kyoto", "Nishiki Market"],
                        "featured_pois": [
                            {
                                "name": "Lunch along Philosopher's Path",
                                "area": "Higashiyama",
                                "cuisine_or_type": "cafe lunch",
                                "reason": "Works near the walking route.",
                                "suggested_time": "lunch",
                                "price_hint": "around 1,500 to 2,500 JPY per person from current search evidence",
                                "price_checked_at": "current search snapshot",
                                "price_valid_for": "2026-04-14, two travelers",
                                "review_score": "4.3/5",
                                "review_count": "500+",
                                "review_summary": "Good location and relaxed lunch feedback.",
                                "signature_dishes": ["coffee", "light lunch"],
                                "reservation_hint": "unknown",
                                "queue_hint": "short queue possible at lunch",
                                "confidence": "medium",
                                "caveats": ["Re-check opening hours before going."],
                                "source_urls": ["https://food.example.test/philosopher-cafe"],
                            },
                            {
                                "name": "Nishiki Market brunch",
                                "area": "Downtown Kyoto",
                                "cuisine_or_type": "market food",
                                "reason": "Flexible food crawl.",
                                "suggested_time": "brunch",
                                "price_hint": "unknown",
                                "price_checked_at": "unknown",
                                "review_score": "unknown",
                                "review_count": "unknown",
                                "review_summary": "Popular food market; exact stall ratings vary.",
                                "signature_dishes": ["snacks"],
                                "reservation_hint": "not usually required",
                                "queue_hint": "expect queues near noon",
                                "confidence": "low",
                                "caveats": ["Use unknown instead of invented exact ratings."],
                                "source_urls": ["https://food.example.test/nishiki"],
                            },
                        ],
                        "meal_strategy": ["Anchor lunches near the attraction clusters."],
                        "price_notes": ["Use unknown when source-backed prices are missing."],
                        "review_notes": ["Use recent review signals over generic popularity."],
                        "food_risks": ["Queues can affect meal timing."],
                    }
                )
            if self.name == "hotel_specialist":
                assert "candidate_hotels" in prompt
                assert "poi_collection" in prompt
                return json.dumps(
                    {
                        "recommended_areas": ["Downtown Kyoto", "Higashiyama"],
                        "hotel_candidates": [
                            {
                                "name": "Downtown Kyoto Hotel",
                                "city": "Kyoto",
                                "area": "Downtown Kyoto",
                                "address": "Downtown Kyoto",
                                "reason": "Balanced access to food and transit.",
                                "price_hint": "moderate",
                                "source_urls": ["https://hotel.example.test/downtown-kyoto"],
                                "source_page_titles": ["Downtown Kyoto Hotel | Hotel listing"],
                            }
                        ],
                        "stay_strategy": ["Prefer one transit-friendly base for the whole trip."],
                        "budget_notes": ["Keep the hotel near the nightly target budget band."],
                    }
                )
            if self.name == "transport_specialist":
                assert "transport_context" in prompt
                assert "poi_collection" in prompt
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
                assert "poi_collection" in prompt
                assert "weather" in prompt
                assert "hotels" in prompt
                assert "transport" in prompt
                parsed = json.loads(prompt)
                poi_collection = parsed["poi_collection"]
                hotels = parsed["hotels"]
                transport = parsed["transport"]
                assert "pois" in poi_collection
                assert "food_pois" in poi_collection
                assert poi_collection["food_pois"] == []
                assert not any(poi["kind"] in {"food", "cafe", "market", "night_market"} for poi in poi_collection["pois"])
                assert len(poi_collection["pois"]) <= 20
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
                                        "type": "explore",
                                        "name": "Philosopher's Path",
                                        "start_time": "12:00",
                                        "end_time": "13:30",
                                        "location": "Kyoto",
                                        "score": 0.82,
                                        "note": "Canal-side walk near the temple route.",
                                    },
                                ],
                            },
                            {
                                "title": "2026-04-15 | Central Kyoto",
                                "summary": "Slow scenic afternoon.",
                                "total_cost": 2400,
                                "items": [
                                    {
                                        "type": "sight",
                                        "name": "Kiyomizu hillside stroll",
                                        "start_time": "10:00",
                                        "end_time": "12:00",
                                        "location": "Kyoto",
                                        "score": 0.84,
                                        "note": "Traditional lanes and hillside views.",
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















def test_departure_buffer_starts_after_last_non_transport_activity():
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )
    payload = parse_planning_response(
        json.dumps(
            {
                "summary": "Return day with a complete departure chain.",
                "total_budget_estimate": 1000,
                "risks": [],
                "days": [
                    {
                        "title": "Arrival",
                        "summary": "Arrival day.",
                        "total_cost": 0,
                        "items": [
                            {
                                "type": "sight",
                                "name": "Old town",
                                "start_time": "18:00",
                                "end_time": "19:00",
                                "location": "Shantou",
                                "score": 0.8,
                                "note": "Short walk.",
                            }
                        ],
                    },
                    {
                        "title": "Return",
                        "summary": "Museum, station transfer, then rail.",
                        "total_cost": 0,
                        "items": [
                            {
                                "type": "sight",
                                "name": "Museum",
                                "start_time": "09:45",
                                "end_time": "10:45",
                                "location": "Shantou",
                                "score": 0.9,
                                "note": "Last visit.",
                            },
                            {
                                "type": "accommodation",
                                "name": "Hotel checkout and luggage collection",
                                "start_time": "12:15",
                                "end_time": "12:45",
                                "location": "Shantou",
                                "score": 0.9,
                                "note": "Collect luggage before leaving.",
                            },
                            {
                                "type": "transport",
                                "name": "Collect luggage and transfer to station",
                                "start_time": "12:45",
                                "end_time": "13:45",
                                "location": "Shantou Station",
                                "score": 0.9,
                                "note": "Station transfer.",
                            },
                            {
                                "type": "transport",
                                "name": "汕头至广州高铁",
                                "start_time": "13:45",
                                "end_time": "16:45",
                                "location": "Shantou to Guangzhou",
                                "score": 0.9,
                                "note": "Rail window pending booking.",
                            },
                        ],
                    },
                ],
            }
        )
    )

    orchestrator._validate_execution_constraints(
        payload,
        _planning_request(),
        TransportGuidance(
            departure_transfer_minutes=50,
            station_buffer_minutes=40,
            luggage_buffer_minutes=30,
            minimum_departure_buffer_minutes=120,
        ),
    )


def test_budgeting_uses_itemized_costs_without_filling_unused_budget_capacity():
    request = _planning_request().model_copy(update={"budget": 6800})
    plan = PlanningResult(
        summary="Grounded budget test.",
        total_budget_estimate=6800,
        risks=[],
        days=[
            PlannedDay(
                day_index=1,
                title="Arrival",
                summary="Rail and hotel.",
                total_cost=4000,
                items=[
                    PlannedItem(
                        id="rail_out",
                        type="transport",
                        name="Outbound rail",
                        start_time="15:00",
                        end_time="18:00",
                        location="Shantou",
                        score=0.9,
                        note="Estimate superseded by transport specialist total.",
                        booking_info=BookingInfo(estimated_price=1000),
                    ),
                    PlannedItem(
                        id="hotel",
                        type="accommodation",
                        name="Two-night hotel",
                        start_time="18:30",
                        end_time="19:00",
                        location="Shantou",
                        score=0.9,
                        note="One grounded stay total.",
                        booking_info=BookingInfo(estimated_price=1100),
                    ),
                ],
            ),
            PlannedDay(
                day_index=2,
                title="Return",
                summary="Return rail.",
                total_cost=2800,
                items=[
                    PlannedItem(
                        id="rail_back",
                        type="transport",
                        name="Return rail",
                        start_time="14:00",
                        end_time="17:00",
                        location="Guangzhou",
                        score=0.9,
                        note="Estimate superseded by transport specialist total.",
                        booking_info=BookingInfo(estimated_price=500),
                    )
                ],
            ),
        ],
        transport_booking_summary=TransportBookingSummary(
            estimated_intercity_cost=1000,
            estimated_local_transport_cost=350,
        ),
        trace=AgentTrace(provider="test", workflow_id="workflow_test", notes=[]),
    )

    result = enrich_plan_with_budget(plan, request)

    assert result.total_budget_estimate == 2450
    assert result.budget_summary is not None
    assert result.budget_summary.estimated_total == 2450
    assert result.budget_summary.remaining_budget == 4350
    assert result.budget_summary.breakdown.accommodation == 1100
    assert result.budget_summary.breakdown.transport == 1350
    assert result.budget_summary.breakdown.other == 0
    assert sum(day.total_cost for day in result.days) == 2450
    assert sum(item.amount for item in result.budget_summary.line_items) == 2450
    assert any("planner-stated day totals" in risk for risk in result.risks)










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











def test_helloagents_planner_hotels_payload_filters_unverified_concrete_hotels():
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )
    unverified = HotelCandidate(
        name="大理中央地标酒店",
        area="大理古城",
        reason="Looks central, but no source URL was returned.",
        price_hint="current search snapshot",
        booking_confidence="medium",
    )
    hotel = HotelRecommendation(
        recommended_areas=["大理古城"],
        final_recommended_hotel=unverified,
        hotel_candidates=[unverified],
        stay_strategy=["住在古城步行范围内，减少来回打车。"],
    )

    payload = orchestrator._build_planner_hotels_payload(hotel)

    assert payload["final_recommended_hotel"] is None
    assert payload["hotel_candidates"] == []
    assert "核验" in " ".join(payload["stay_strategy"])
    assert "大理中央地标酒店" not in json.dumps(payload, ensure_ascii=False)


def test_helloagents_planner_hotels_payload_keeps_source_backed_hotels():
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )
    verified = HotelCandidate(
        name="Verified Dali Hotel",
        city="Dali",
        area="Dali Old Town",
        address="Dali Old Town, Dali",
        reason="Source-backed listing near the planned POI cluster.",
        booking_confidence="medium",
        source_urls=["https://hotel.example.test/dali-verified"],
        source_page_titles=["Verified Dali Hotel | official listing"],
    )
    hotel = HotelRecommendation(
        recommended_areas=["Dali Old Town"],
        final_recommended_hotel=verified,
        hotel_candidates=[verified],
    )

    payload = orchestrator._build_planner_hotels_payload(hotel)

    assert payload["final_recommended_hotel"]["name"] == "Verified Dali Hotel"
    assert payload["final_recommended_hotel"]["source_urls"] == ["https://hotel.example.test/dali-verified"]
    assert payload["hotel_candidates"] == []


def test_helloagents_parser_uses_last_valid_object_when_response_contains_conflicting_objects():
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    parsed = orchestrator._parse_structured_response(
        '{"destination":"Kyoto","trip_days":2}{"destination":"Osaka","trip_days":3}',
        PlanningBrief,
    )

    assert parsed.destination == "Osaka"
    assert parsed.trip_days == 3


def test_helloagents_hotel_verification_requires_city_and_page_entity_match():
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )
    valid = HotelCandidate(
        name="汕头小公园宜必思酒店",
        city="汕头",
        area="金平区",
        address="汕头市金平区",
        source_urls=["https://hotel.example.test/ibis-shantou-xiaogongyuan"],
        source_page_titles=["汕头小公园宜必思酒店 | 酒店详情"],
    )
    wrong_city = valid.model_copy(update={"city": "广州"})
    wrong_entity = valid.model_copy(update={"source_page_titles": ["汕头新华酒店 | 酒店详情"]})

    assert orchestrator._is_verified_hotel_candidate(valid, destination="汕头")
    assert not orchestrator._is_verified_hotel_candidate(wrong_city, destination="汕头")
    assert not orchestrator._is_verified_hotel_candidate(wrong_entity, destination="汕头")


def test_helloagents_hotel_verification_removes_conflicting_source_url_candidates():
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )
    first = HotelCandidate(
        name="汕头宜必思酒店",
        city="汕头",
        source_urls=["https://hotel.example.test/hotel-123"],
        source_page_titles=["汕头宜必思酒店 | 酒店详情"],
    )
    second = HotelCandidate(
        name="汕头新华酒店",
        city="汕头",
        source_urls=["https://hotel.example.test/hotel-123"],
        source_page_titles=["汕头新华酒店 | 酒店详情"],
    )
    hotel = HotelRecommendation(
        recommended_areas=["金平区"],
        final_recommended_hotel=first,
        hotel_candidates=[first, second],
    )

    payload = orchestrator._build_planner_hotels_payload(hotel, destination="汕头")

    assert payload["final_recommended_hotel"] is None
    assert payload["hotel_candidates"] == []
    assert any("无法消歧" in item for item in payload["hotel_risks"])


def test_helloagents_planner_poi_payload_excludes_food_pois():
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )
    payload = orchestrator._build_planner_poi_collection_payload(
        {
            "pois": [
                {"kind": "attraction", "name": "大理古城", "area": "大理古城片区"},
                {"kind": "food", "name": "在回首", "area": "大理古城"},
                {"kind": "cafe", "name": "古城咖啡馆", "area": "大理古城"},
                {"kind": "market", "name": "大理古城夜市", "area": "大理古城"},
                {"kind": "experience", "name": "洱海生态廊道", "area": "洱海沿岸"},
            ],
            "top_areas": ["大理古城", "洱海沿岸"],
        }
    )

    assert [item["name"] for item in payload["pois"]] == ["大理古城", "洱海生态廊道"]
    assert payload["food_pois"] == []
    assert any("Excluded 3 food/cafe/market POIs" in item for item in payload["risks"])









def test_helloagents_build_day_weather_uses_tool_temperature_hint_when_daily_outlook_omits_it():
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    weather_guidance = planning_core_module.WeatherGuidance(
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


def test_helloagents_build_day_weather_uses_matching_date_sources():
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )
    weather_guidance = planning_core_module.WeatherGuidance(
        overall_outlook="Warm with showers.",
        source_urls=["https://weather.example.test/city"],
        daily_forecasts=[
            planning_core_module.DailyForecast(
                date=date(2026, 4, 14),
                outlook="18°C to 24°C.",
                source_urls=["https://weather.example.test/2026-04-14"],
            ),
            planning_core_module.DailyForecast(
                date=date(2026, 4, 15),
                outlook="19°C to 25°C.",
                source_urls=["https://weather.example.test/2026-04-15"],
            ),
        ],
    )

    day_weather = orchestrator._build_day_weather(
        2,
        weather_guidance,
        [
            "https://weather.example.test/2026-04-14",
            "https://weather.example.test/2026-04-15",
            "https://weather.example.test/search-metadata",
        ],
        target_date=date(2026, 4, 15),
        trip_start_date=date(2026, 4, 14),
        expected_days=2,
    )

    assert day_weather is not None
    assert day_weather.citations == ["https://weather.example.test/2026-04-15"]



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

    monkeypatch.setattr(PlanningCore, "_call_mcp_tool", fake_call)
    orchestrator = PlanningCore(
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
    assert result["research"]["deep_research_completed"] is True



def test_helloagents_hotel_tool_results_crawl_top_search_urls_when_available(monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_call(self, client, tool_name, arguments, *, role_name):
        del self, client, role_name
        calls.append((tool_name, arguments))
        if tool_name == "search":
            return {
                "results": [
                    {"url": "https://stay.example.test/hotel-alpha", "title": "Hotel Alpha"},
                    {"url": "https://stay.example.test/hotel-beta", "title": "Hotel Beta"},
                ]
            }
        if tool_name == "contents":
            return {
                "results": [
                    {"url": "https://stay.example.test/hotel-alpha", "text": "Transit-friendly stay."},
                    {"url": "https://stay.example.test/hotel-beta", "text": "Quiet boutique option."},
                ]
            }
        raise AssertionError(f"Unexpected MCP tool: {tool_name}")

    monkeypatch.setattr(PlanningCore, "_call_mcp_tool", fake_call)
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator._collect_hotel_tool_results(
        object(),
        {"search", "contents"},
        {
            "trip_request": {"destination": "Kyoto", "accommodation_preference": "Quiet boutique hotel"},
            "planning_brief": {"destination": "Kyoto", "accommodation": "Quiet boutique hotel"},
            "candidate_hotels": [{"name": "Hotel Alpha"}, {"name": "Hotel Beta"}],
        },
    )

    assert result["search_tool"] == "search"
    assert result["crawl_tool"] == "contents"
    assert result["crawl_urls"] == [
        "https://stay.example.test/hotel-alpha",
        "https://stay.example.test/hotel-beta",
    ]
    assert [name for name, _ in calls] == ["search", "contents"]



def test_helloagents_hotel_tool_results_include_grounding_docs(monkeypatch):
    monkeypatch.setattr(
        planning_core_module,
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
        PlanningCore,
        "_call_mcp_tool",
        lambda self, client, tool_name, arguments, *, role_name: {"results": [{"url": "https://stay.example.test/hotel-alpha"}]},
    )
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator._collect_hotel_tool_results(
        object(),
        {"search", "contents"},
        {
            "trip_request": {"destination": "Kyoto", "accommodation_preference": "Quiet boutique hotel"},
            "planning_brief": {"destination": "Kyoto", "accommodation": "Quiet boutique hotel"},
            "candidate_hotels": [{"name": "Hotel Alpha"}],
        },
    )

    assert result["grounding_docs"][0]["platform"] == "xiaohongshu"



def test_helloagents_weather_tool_results_do_not_include_social_grounding(monkeypatch):
    monkeypatch.setattr(
        planning_core_module,
        "search_documents",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("weather should not request social grounding")),
    )
    monkeypatch.setattr(
        PlanningCore,
        "_call_search_like_tool",
        lambda self, client, tool_name, query, num_results, *, role_name: {"answer": "Mock weather answer", "results": []},
    )
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator._collect_weather_tool_results(
        object(),
        {"answer"},
        {"trip_request": {"destination": "Kyoto", "start_date": "2026-04-14", "end_date": "2026-04-15"}},
    )

    assert "grounding_docs" not in result


def test_helloagents_poi_specialist_augment_skips_tool_collection_with_native_search(monkeypatch):
    events: list[dict[str, object]] = []

    def fake_log_job_event(event, **payload):
        events.append({"event": event, "payload": payload})

    def forbidden_build_role_mcp_clients(self, role_name):
        del self
        raise AssertionError(f"POI specialist should not build tool clients for {role_name}")

    monkeypatch.setattr(planning_core_module, "log_job_event", fake_log_job_event)
    monkeypatch.setattr(PlanningCore, "_build_role_mcp_clients", forbidden_build_role_mcp_clients)
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://rainflow.example.test/v1", api_key="test-key", model="Web/grok-chat-fast", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )
    payload = {
        "trip_request": {"destination": "Dali"},
        "planning_brief": {"destination": "Dali", "interests": ["ancient town", "lake"]},
        "poi_context": {"interests": ["city walk", "附近吃饭", "湖边随便逛"]},
    }

    result = orchestrator._augment_payload_with_tool_results("poi_specialist", payload)

    assert result is payload
    assert result["tool_results"] == {"poi_source": "native_search"}
    skip_event = next(item for item in events if item["event"] == "helloagents_poi_tool_collection_skipped")
    assert skip_event["payload"]["role"] == "poi_specialist"
    assert skip_event["payload"]["external_tool_collection"] is False
    assert skip_event["payload"]["native_search_allowed"] is True
    assert skip_event["payload"]["poi_specialist_uses_search"] is True


def test_helloagents_poi_specialist_augment_collects_mcp_evidence_without_native_search(monkeypatch):
    monkeypatch.setattr(
        planning_core_module,
        "search_documents",
        lambda query, destination, manual_links, **kwargs: [],
    )
    fake_client = SimpleNamespace(
        config=SearchServiceConfig(provider="groksearch", transport="mcp", base_url="https://groksearch.example.test/mcp", api_key="test-key")
    )
    monkeypatch.setattr(
        PlanningCore,
        "_build_role_mcp_clients",
        lambda self, role_name: [(fake_client, {"web_search"})],
    )
    monkeypatch.setattr(
        PlanningCore,
        "_call_mcp_tool",
        lambda self, client, tool_name, arguments, *, role_name: {
            "sources": [{"url": "https://example.test/kyoto-guide", "title": "Kyoto guide"}]
        },
    )
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )
    payload = {
        "trip_request": {"destination": "Kyoto", "pace": "balanced"},
        "planning_brief": {"destination": "Kyoto", "must_have": ["temples"], "interests": ["temples"]},
        "poi_context": {"interests": ["temples"], "must_have": ["temples"]},
        "candidate_pois": [{"name": "Ginkaku-ji"}],
    }

    result = orchestrator._augment_payload_with_tool_results("poi_specialist", payload)

    assert result["tool_results"]["poi_source"] == "search_evidence"
    assert result["tool_results"]["search_tool"] == "web_search"
    assert result["tool_results"]["citations"] == ["https://example.test/kyoto-guide"]


def test_helloagents_has_native_search_requires_known_web_model():
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    def endpoint(base_url, model):
        return LlmConfig(base_url=base_url, api_key="test-key", model=model, wire_api="responses").config_for_role("poi_specialist")

    assert orchestrator._has_native_search("poi_specialist", endpoint("https://proxy.example.test/v1", "Web/grok-chat-fast")) is True
    assert orchestrator._has_native_search("weather_specialist", endpoint("https://proxy.example.test/v1", "Web/grok-chat-fast")) is True
    assert orchestrator._has_native_search("poi_specialist", endpoint("https://proxy.example.test/v1", "Console/grok-4.20-multi-agent-0309")) is True
    assert orchestrator._has_native_search("weather_specialist", endpoint("https://proxy.example.test/v1", "Console/grok-4.20-0309-non-reasoning")) is True
    assert orchestrator._has_native_search("poi_specialist", endpoint("https://api.x.ai/v1", "grok-4")) is False
    assert orchestrator._has_native_search("poi_specialist", endpoint("https://rainflow.example.test/v1", "gpt-test")) is False
    assert orchestrator._has_native_search("poi_specialist", endpoint("https://llm.example.test/v1", "gpt-test")) is False
    assert orchestrator._has_native_search("itinerary_planner", endpoint("https://rainflow.example.test/v1", "gpt-test")) is False
    assert orchestrator._has_native_search("poi_specialist", None) is False
    assert orchestrator._role_config_uses_search_capable_grok(
        "poi_specialist", endpoint("https://proxy.example.test/v1", "Web/grok-chat-fast")
    ) is True


def _booking_orchestrator() -> PlanningCore:
    return PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )


def test_food_booking_info_negated_reservation_hint_is_not_required():
    orchestrator = _booking_orchestrator()
    for hint in ("无需预约，随到随吃", "无须预约", "不需要预约", "不用预约", "免预约", "No reservation needed", "Reservation not required", "Walk-in only", "walk in welcome"):
        booking = orchestrator._build_food_booking_info(
            planning_core_module.FoodPoi(name="Test Diner", reservation_hint=hint)
        )
        assert booking is not None, hint
        assert booking.reservation_required is False, hint
        assert booking.booking_required is False, hint


def test_food_booking_info_positive_reservation_hint_is_required():
    orchestrator = _booking_orchestrator()
    for hint in ("需要预约", "需预约", "建议预约", "请提前订位", "Reservation required", "Please reserve ahead"):
        booking = orchestrator._build_food_booking_info(
            planning_core_module.FoodPoi(name="Test Diner", reservation_hint=hint)
        )
        assert booking is not None, hint
        assert booking.reservation_required is True, hint
        assert booking.booking_required is True, hint


def test_helloagents_direct_grok_specialist_skips_mcp_tool_collection(monkeypatch):
    events: list[dict[str, object]] = []

    def fake_log_job_event(event, **payload):
        events.append({"event": event, "payload": payload})

    def forbidden_build_role_mcp_clients(self, role_name):
        del self
        raise AssertionError(f"Grok direct specialist should not build tool clients for {role_name}")

    monkeypatch.setattr(planning_core_module, "log_job_event", fake_log_job_event)
    monkeypatch.setattr(PlanningCore, "_build_role_mcp_clients", forbidden_build_role_mcp_clients)
    config = LlmConfig.from_mapping(
        {
            "base_url": "https://default.example.test/v1",
            "api_key": "default-key",
            "model": "gpt-default",
            "wire_api": "responses",
            "role_overrides": {
                "weather_specialist": {
                    "base_url": "https://api.x.ai/v1",
                    "api_key": "grok-key",
                    "model": "Web/grok-chat-fast",
                    "wire_api": "chat_completions",
                    "provider_protocol": "newapi",
                }
            },
        }
    )
    orchestrator = PlanningCore(config, maps_provider=StubMapsPoiProvider())
    payload = {
        "trip_request": {"destination": "Kyoto"},
        "planning_brief": {"destination": "Kyoto"},
        "weather_segments": [{"name": "Kyoto"}],
    }

    result = orchestrator._augment_payload_with_tool_results("weather_specialist", payload)

    assert result is payload
    assert "tool_results" not in result
    skip_event = next(item for item in events if item["event"] == "helloagents_direct_grok_tool_collection_skipped")
    assert skip_event["payload"]["role"] == "weather_specialist"
    assert skip_event["payload"]["model"] == "Web/grok-chat-fast"


def test_poi_specialist_prompt_allows_native_search_and_constrains_dirty_names():
    prompt = build_poi_specialist_prompt()
    text = prompt.system_prompt

    assert "用户的出发地、目的地、日期、预算、人数、兴趣、节奏" in text
    assert "全网公开信息" in text
    assert "小红书" in text
    assert "知乎" in text
    assert "马蜂窝" in text
    assert "携程" in text
    assert "必须只使用当前模型自带的联网检索能力" in text
    assert "交叉参考" in text
    assert "不要调用外部工具" in text
    assert "不要输出搜索摘要" in text
    assert "5天及以上返回15到20个" in text
    assert "每个核心锚点可扩展1到3个周边点" in text
    assert "name 必须是真实、可搜索、位于目的地或其合理一日游范围内的景点、街区、自然风景或体验名" in text
    assert "真实、可搜索、位于目的地或其合理一日游范围内" in text
    assert "city walk route" in text
    assert "古城晨间散步" in text
    assert "湖边随便逛" in text
    assert "Central Landmark" in text
    assert "Market Hall" in text
    assert "Riverside Walk" in text
    assert "center zone" in text
    assert "每个 top_poi 只输出 8 个字段" in text
    assert "highlights 保留 2-4 个短词组" in text
    assert "真实可搜索的子景点" in text
    assert "南门城楼" in text
    assert "source_urls 返回1到3个" in text
    assert "政府网站根首页" in text
    assert "每个 top_poi 都应带 source_urls" in text
    assert "source_urls 为空，confidence 必须是 low" in text
    assert "这类无来源 POI 不要超过 2 个" in text
    assert "不要推荐餐厅、小吃店、咖啡馆、夜市、美食街、菜市场" in text
    assert "餐饮词也不要出现在 name、kind、highlights 或 reason 中" in text
    assert "不要把小吃街、菜市场、夜市、咖啡馆包装成 district 或 experience" in text
    assert "area 必须写真实行政区、县、岛屿、街区或景区片区" in text
    assert "kind 只能从 attraction、district、experience 中选择" in text
    assert "kind 只能从 attraction、food、market、cafe、district、experience 中选择" not in text
    assert "evidence_notes" not in text
    assert "source_url\"" not in text
    assert "does not search the web" not in text
    assert "tool_results" not in text
    assert "trip_request" not in text
    assert "planning_brief" not in text
    assert "poi_context" not in text


def test_weather_specialist_prompt_keeps_weather_as_planning_support():
    prompt = build_weather_specialist_prompt()
    text = prompt.system_prompt

    assert "天气只作为行程编排辅助" in text
    assert "daily_outlook 每天最多 1 句" in text
    assert "segments 最多 2 个" in text


def test_hotel_specialist_prompt_rejects_unsourced_concrete_hotel_names():
    prompt = build_hotel_specialist_prompt()
    text = prompt.system_prompt

    assert "每个具体酒店必须带 source_urls" in text
    assert "source-backed 的最低标准不是 URL 不为空" in text
    assert "每个具体酒店必须同时填写 city 和 address" in text
    assert "source_page_titles 必须与 source_urls 按顺序对应" in text
    assert "后端会校验酒店名称、目的地城市、页面标题和来源 URL 的实体一致性" in text
    assert "酒店精确名称、所在城市/区域、地址或地标位置、近期评价/评分/设施信号" in text
    assert "中国大陆目的地优先输出来源中的中文本地展示名" in text
    assert "不要只输出英文名" in text
    assert "如果只有海外英文 OTA 页面，最多作为候选，不能直接定为最终推荐" in text
    assert "final_recommended_hotel 设为 null" in text
    assert "严禁为了满足字段而编造酒店名" in text
    assert "hotel_candidates 输出 2-3 个来源充足的不同实体" in text
    assert "预算是上限和舒适度约束，不是越便宜越好" in text
    assert "不要因为低价选择质量信号弱的酒店" in text
    assert "你必须在 final_recommended_hotel 中选择一个具体酒店名称" not in text


def test_helloagents_poi_tool_results_use_groksearch_search_evidence_only(monkeypatch):
    calls: list[tuple[str, dict[str, object], str]] = []
    monkeypatch.setattr(
        planning_core_module,
        "search_documents",
        lambda query, destination, manual_links, **kwargs: [],
    )

    def fake_call(self, client, tool_name, arguments, *, role_name):
        del self, client
        calls.append((tool_name, arguments, role_name))
        if tool_name == "web_search":
            query = str(arguments["query"])
            assert "Kyoto" in query
            assert "Ginkaku-ji" in query
            assert "temples" in query
            assert "Kyoto Cafe" not in query
            assert "coffee" not in query
            assert "cafe" not in query.lower()
            assert "restaurant" not in query.lower()
            assert "搜索任务：" not in query
            assert "输出一个具名 POI 池" not in query
            return {
                "sources": [
                    {"url": "https://example.test/kyoto-guide", "title": "Kyoto guide"},
                    {"url": "https://attraction.example.test/philosopher-path", "title": "Philosopher Path guide"},
                ]
            }
        raise AssertionError(f"Unexpected MCP tool: {tool_name}")

    monkeypatch.setattr(PlanningCore, "_call_mcp_tool", fake_call)
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator._collect_poi_tool_results(
        SimpleNamespace(config=SearchServiceConfig(provider="groksearch", transport="mcp", base_url="https://groksearch.example.test/mcp", api_key="test-key")),
        {"web_search", "web_fetch"},
        {
            "trip_request": {"destination": "Kyoto", "pace": "balanced", "raw_user_input": "I want quiet coffee and temple neighborhoods in Kyoto"},
            "planning_brief": {"destination": "Kyoto", "must_have": ["temples"], "interests": ["coffee"]},
            "poi_request": {"task": "Find named Kyoto POIs worth visiting."},
            "poi_context": {"interests": ["temples"], "food_interests": ["coffee"], "must_have": ["temples"]},
            "candidate_pois": [{"name": "Ginkaku-ji"}],
            "candidate_food_pois": [{"name": "Kyoto Cafe"}],
        },
    )

    assert result["search_tool"] == "web_search"
    assert result["poi_source"] == "search_evidence"
    assert result["citations"] == [
        "https://example.test/kyoto-guide",
        "https://attraction.example.test/philosopher-path",
    ]
    assert "crawl_tool" not in result
    assert "crawl_urls" not in result
    assert [name for name, _, _ in calls] == ["web_search"]
    assert all(role_name == "poi_specialist" for _, _, role_name in calls)


def test_helloagents_poi_tool_results_fall_back_to_groksearch_answer_when_web_search_is_unavailable(monkeypatch):
    calls: list[tuple[str, dict[str, object], str]] = []
    monkeypatch.setattr(
        planning_core_module,
        "search_documents",
        lambda query, destination, manual_links, **kwargs: [],
    )

    def fake_call(self, client, tool_name, arguments, *, role_name):
        del self, client
        calls.append((tool_name, arguments, role_name))
        assert tool_name == "answer"
        query = str(arguments["query"])
        assert "Kyoto" in query
        assert "POI" in query
        assert "restaurant" not in query.lower()
        assert "cafe" not in query.lower()
        assert arguments["include_text"] is True
        return {
            "answer": "Use Ginkaku-ji and Kiyomizu-dera as grounded sightseeing POIs.",
            "sources": [{"url": "https://example.test/kyoto-poi", "title": "Kyoto POI guide"}],
        }

    monkeypatch.setattr(PlanningCore, "_call_mcp_tool", fake_call)
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator._collect_poi_tool_results(
        SimpleNamespace(config=SearchServiceConfig(provider="groksearch", transport="mcp", base_url="https://groksearch.example.test/mcp", api_key="test-key")),
        {"answer"},
        {
            "trip_request": {"destination": "Kyoto", "pace": "balanced"},
            "planning_brief": {"destination": "Kyoto", "must_have": ["temples"], "interests": ["markets"]},
            "poi_context": {"interests": ["temples"], "food_interests": ["markets"], "must_have": ["temples"]},
            "candidate_pois": [],
            "candidate_food_pois": [],
        },
    )

    assert result["search_tool"] == "answer"
    assert result["research_tool"] == "answer"
    assert result["poi_source"] == "search_evidence"
    assert result["citations"] == ["https://example.test/kyoto-poi"]
    assert [name for name, _, _ in calls] == ["answer"]
    assert all(role_name == "poi_specialist" for _, _, role_name in calls)


def test_helloagents_mcp_tool_call_logs_request_and_response_snapshots(monkeypatch):
    events: list[dict[str, object]] = []

    def fake_log_job_event(event, **payload):
        events.append({"event": event, "payload": payload})

    class FakeGateway:
        def call_operation(self, name, arguments):
            assert name == "web_search"
            assert arguments == {"query": "大理 POI 美食 评分"}
            return {
                "session_id": "session_123",
                "sources": [
                    {
                        "title": "大理旅行攻略",
                        "url": "https://example.test/dali-guide",
                        "snippet": "大理古城、洱海和喜洲古镇。",
                    }
                ],
            }

    monkeypatch.setattr(planning_core_module, "log_job_event", fake_log_job_event)
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator._call_mcp_tool(FakeGateway(), "web_search", {"query": "大理 POI 美食 评分"}, role_name="poi_specialist")

    assert result["session_id"] == "session_123"
    request_event = next(item for item in events if item["event"] == "helloagents_mcp_tool_request")
    response_event = next(item for item in events if item["event"] == "helloagents_mcp_tool_response")
    assert request_event["payload"]["role"] == "poi_specialist"
    assert request_event["payload"]["tool"] == "web_search"
    assert request_event["payload"]["arguments"]["query"] == "大理 POI 美食 评分"
    response_snapshot = response_event["payload"]["response"]
    assert response_snapshot["session_id"] == "session_123"
    assert response_snapshot["sources"][0]["url"] == "https://example.test/dali-guide"
    assert response_snapshot["citations"] == ["https://example.test/dali-guide"]


def test_helloagents_weather_tool_results_use_groksearch_web_search(monkeypatch):
    monkeypatch.setattr(
        PlanningCore,
        "_call_search_like_tool",
        lambda self, client, tool_name, query, num_results, *, role_name: {
            "session_id": "session_123",
            "content": "Cool mornings with light rain risk.",
            "sources": [{"url": "https://weather.example.test/forecast"}],
        },
    )
    orchestrator = PlanningCore(
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


def test_helloagents_hotel_tool_results_use_groksearch_answer_without_fetch(monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_call(self, client, tool_name, arguments, *, role_name):
        del self, client, role_name
        calls.append((tool_name, arguments))
        if tool_name == "answer":
            return {
                "answer": "Stay near Hotel Alpha or Hotel Beta for a quiet, transit-friendly Kyoto base.",
                "sources": [
                    {"url": "https://stay.example.test/hotel-alpha", "title": "Hotel Alpha"},
                    {"url": "https://stay.example.test/hotel-beta", "title": "Hotel Beta"},
                ],
            }
        raise AssertionError(f"Unexpected MCP tool: {tool_name}")

    monkeypatch.setattr(PlanningCore, "_call_mcp_tool", fake_call)
    monkeypatch.setattr(
        planning_core_module,
        "search_documents",
        lambda query, destination, manual_links, *, interests=None, social_context="general", search_service_config=None, xhs_source_enabled=True: [],
    )
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator._collect_hotel_tool_results(
        SimpleNamespace(config=SearchServiceConfig(provider="groksearch", transport="mcp", base_url="https://groksearch.example.test/mcp", api_key="test-key")),
        {"answer", "web_search", "web_fetch"},
        {
            "trip_request": {"destination": "Kyoto", "accommodation_preference": "Quiet boutique hotel"},
            "planning_brief": {"destination": "Kyoto", "accommodation": "Quiet boutique hotel"},
            "candidate_hotels": [{"name": "Hotel Alpha"}, {"name": "Hotel Beta"}],
        },
    )

    assert result["search_tool"] == "answer"
    assert result["research_tool"] == "answer"
    assert "answer" in result
    assert "search" not in result
    assert "crawl_tool" not in result
    assert "crawl" not in result
    assert result["citations"] == [
        "https://stay.example.test/hotel-alpha",
        "https://stay.example.test/hotel-beta",
    ]
    assert [name for name, _ in calls] == ["answer"]
    assert calls[0][1]["include_text"] is True


def test_helloagents_transport_tool_results_use_groksearch_answer_without_fetch(monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_call(self, client, tool_name, arguments, *, role_name):
        del self, client, role_name
        calls.append((tool_name, arguments))
        if tool_name == "answer":
            return {
                "answer": "Use rail between Osaka and Kyoto, then rely on local transit passes for city movement.",
                "sources": [
                    {"url": "https://transport.example.test/rail-fares", "title": "Rail fares"},
                    {"url": "https://transport.example.test/local-pass", "title": "Local pass"},
                ],
            }
        raise AssertionError(f"Unexpected MCP tool: {tool_name}")

    monkeypatch.setattr(PlanningCore, "_call_mcp_tool", fake_call)
    monkeypatch.setattr(
        planning_core_module,
        "search_documents",
        lambda query, destination, manual_links, *, interests=None, social_context="general", search_service_config=None, xhs_source_enabled=True: [],
    )
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    result = orchestrator._collect_transport_tool_results(
        SimpleNamespace(config=SearchServiceConfig(provider="groksearch", transport="mcp", base_url="https://groksearch.example.test/mcp", api_key="test-key")),
        {"answer", "web_search", "web_fetch"},
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

    assert result["search_tool"] == "answer"
    assert result["research_tool"] == "answer"
    assert "answer" in result
    assert "search" not in result
    assert "crawl_tool" not in result
    assert "crawl" not in result
    assert result["citations"] == [
        "https://transport.example.test/rail-fares",
        "https://transport.example.test/local-pass",
    ]
    assert [name for name, _ in calls] == ["answer"]
    assert calls[0][1]["include_text"] is True


def test_helloagents_extract_urls_from_text_payload():
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    urls = orchestrator._extract_urls_from_search_result(
        {
            "text": "Title: Example\nURL: https://example.com/one\nMore text https://example.com/two?ref=travel.",
            "content": "Markdown citation [[1]](https://example.com/dirty)[[1]] should be cleaned.",
        }
    )

    assert urls == ["https://example.com/one", "https://example.com/two?ref=travel", "https://example.com/dirty"]


def test_helloagents_role_prompt_payload_strips_tool_url_metadata():
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )

    raw_payload = {
        "trip_request": {"destination": "Kyoto"},
        "tool_results": {
            "citations": ["https://sources.example.test/noise"],
            "crawl_urls": ["https://stay.example.test/hotel-alpha"],
            "search": {
                "sources": [{"url": "https://stay.example.test/hotel-alpha", "title": "Hotel Alpha"}],
                "content": "Hotel Alpha has strong reviews: https://stay.example.test/hotel-alpha",
            },
        },
    }

    prompt_payload = orchestrator._build_role_prompt_payload(raw_payload)
    serialized_tool_results = json.dumps(prompt_payload["tool_results"], ensure_ascii=False)

    assert "citations" not in prompt_payload["tool_results"]
    assert "crawl_urls" not in prompt_payload["tool_results"]
    assert "https://" not in serialized_tool_results
    assert "Hotel Alpha" in serialized_tool_results
    assert raw_payload["tool_results"]["citations"] == ["https://sources.example.test/noise"]


def test_helloagents_hotel_prompt_payload_compacts_large_tool_results():
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )
    long_page = "Hotel Alpha central location with food street access. " * 800

    prompt_payload = orchestrator._build_role_prompt_payload(
        {
            "trip_request": {"destination": "Shantou"},
            "tool_results": {
                "search_tool": "web_search",
                "search_query": "Shantou downtown hotel food street",
                "search": {
                    "content": "Use MIXC or Small Park as stay bases.",
                    "sources": [
                        {
                            "url": "https://stay.example.test/alpha",
                            "title": "Hotel Alpha",
                            "snippet": "Central, walkable to food streets.",
                        }
                    ],
                },
                "crawl_tool": "web_fetch",
                "crawl_urls": ["https://stay.example.test/alpha"],
                "crawl": {
                    "results": [
                        {
                            "url": "https://stay.example.test/alpha",
                            "title": "Hotel Alpha page",
                            "text": long_page,
                        }
                    ]
                },
            },
        },
        role_name="hotel_specialist",
    )

    tool_results = prompt_payload["tool_results"]
    serialized = json.dumps(tool_results, ensure_ascii=False)
    assert "search" not in tool_results
    assert "crawl" not in tool_results
    assert "evidence_brief" in tool_results
    assert "Hotel Alpha central location" in serialized
    assert len(serialized) < 2200
    assert len(json.dumps(prompt_payload, ensure_ascii=False)) < 3000


def test_helloagents_transport_prompt_payload_compacts_large_tool_results():
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )
    long_page = "Rail fare table and station transfer details. " * 700

    prompt_payload = orchestrator._build_role_prompt_payload(
        {
            "trip_request": {"origin": "Guangzhou", "destination": "Shantou"},
            "tool_results": {
                "search_tool": "web_search",
                "search_query": "Guangzhou to Shantou rail fares transfer",
                "search": {
                    "content": "Direct rail is the practical intercity option.",
                    "sources": [
                        {
                            "url": "https://transport.example.test/rail",
                            "title": "Rail fares",
                            "snippet": "Fast trains connect Guangzhou and Shantou.",
                        }
                    ],
                },
                "crawl_tool": "web_fetch",
                "crawl_urls": ["https://transport.example.test/rail"],
                "crawl": {
                    "results": [
                        {
                            "url": "https://transport.example.test/rail",
                            "title": "Rail fare table",
                            "text": long_page,
                        }
                    ]
                },
                "citations": ["https://transport.example.test/rail"],
            },
        },
        role_name="transport_specialist",
    )

    tool_results = prompt_payload["tool_results"]
    serialized = json.dumps(tool_results, ensure_ascii=False)
    assert "search" not in tool_results
    assert "crawl" not in tool_results
    assert "evidence_brief" in tool_results
    assert "Rail fare table" in serialized
    assert len(serialized) < 2200
    assert len(json.dumps(prompt_payload, ensure_ascii=False)) < 3000


def test_helloagents_poi_prompt_payload_uses_compact_evidence_brief():
    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )
    long_crawl_text = "大理古城、洱海、苍山、喜洲古镇。 " * 500

    prompt_payload = orchestrator._build_role_prompt_payload(
        {
            "trip_request": {"destination": "大理"},
            "tool_results": {
                "search_tool": "web_search",
                "search_query": "大理 POI 美食 评分",
                "poi_source": "web_search_crawl",
                "search": {
                    "content": "大理古城和洱海适合慢节奏旅行。",
                    "sources": [
                        {"url": "https://example.test/dali-guide", "title": "大理旅行攻略", "snippet": "大理古城、洱海、喜洲古镇。"},
                    ],
                },
                "crawl_tool": "web_fetch",
                "crawl_urls": ["https://example.test/dali-guide"],
                "crawl": {"text": long_crawl_text},
                "grounding_docs": [
                    {
                        "title": "大理古城与洱海路线",
                        "url": "https://example.test/local-note",
                        "summary": "大理古城、洱海和北门菜市场是高频点。",
                        "place_name": "大理古城",
                        "category": "city walk",
                    }
                ],
            },
        },
        role_name="poi_specialist",
    )

    tool_results = prompt_payload["tool_results"]
    assert "evidence_brief" in tool_results
    assert "search" not in tool_results
    assert "crawl" not in tool_results
    assert set(tool_results["citations"]) == {"https://example.test/local-note", "https://example.test/dali-guide"}
    serialized = json.dumps(tool_results, ensure_ascii=False)
    assert len(serialized) < 2200
    assert "大理古城" in serialized
    assert "truncated" not in serialized.lower()


def test_helloagents_poi_grounding_accepts_lightweight_top_pois_shape():
    payload = {
        "title": "去大理值得去的POI推荐列表",
        "update": "2026年6月综合全网信息",
        "best_season": "3-5月，9-11月",
        "recommended_duration": "4-7天",
        "general_tips": "适合慢节奏和环海玩法。",
        "top_pois": [
            {
                "name": "大理古城",
                "kind": "district",
                "area": "大理古城片区",
                "highlights": ["南门城楼", "洋人街", "白族民居", "夜景咖啡馆", "这条应该被截断"],
                "reason": "大理旅行起点与灵魂。",
                "suggested_time": "0.5-1天",
                "confidence": "high",
                "source_url": "https://example.test/dali-ancient-city",
            },
            {
                "name": "洱海",
                "kind": "attraction",
                "area": "环海区域",
                "highlights": ["生态廊道骑行", "双廊", "日落"],
                "reason": "大理风花雪月核心。",
                "suggested_time": "2-3天",
                "confidence": "medium",
            },
            {
                "name": "大理古城",
                "kind": "district",
                "highlights": ["重复名称应被去重"],
            },
            {
                "name": "",
                "kind": "attraction",
                "highlights": ["空名称应被丢弃"],
            },
            {
                "name": "this is a very long explanatory sentence that should not be accepted as a poi name because it is not a place",
                "kind": "attraction",
                "highlights": ["过长名称应被丢弃"],
            },
        ],
    }

    grounding = PoiGrounding.model_validate(payload)

    assert grounding.title == "去大理值得去的POI推荐列表"
    assert len(grounding.top_pois) == 2
    assert [poi.name for poi in grounding.featured_pois] == ["大理古城", "洱海"]
    assert grounding.featured_pois[0].kind == "mixed_area"
    assert grounding.featured_pois[1].kind == "attraction"
    assert grounding.featured_pois[0].area == "大理古城片区"
    assert grounding.featured_pois[1].area == "环海区域"
    assert grounding.featured_pois[0].reason == "大理旅行起点与灵魂。"
    assert grounding.featured_pois[0].highlights == ["南门城楼", "洋人街", "白族民居", "夜景咖啡馆"]
    assert grounding.featured_pois[0].confidence == "high"
    assert grounding.featured_pois[0].source_urls == ["https://example.test/dali-ancient-city"]
    assert grounding.featured_pois[0].evidence_notes == []
    assert grounding.featured_pois[1].confidence == "low"
    assert grounding.poi_risks

    orchestrator = PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )
    snapshot = orchestrator._build_poi_output_snapshot(grounding)
    assert snapshot["featured_pois"][0]["highlights"] == ["南门城楼", "洋人街", "白族民居", "夜景咖啡馆"]

    collection = orchestrator._build_poi_collection(grounding)
    assert collection["pois"][0] == {
        "kind": "mixed-area",
        "name": "大理古城",
        "area": "大理古城片区",
        "highlights": ["南门城楼", "洋人街", "白族民居", "夜景咖啡馆"],
        "reason": "大理旅行起点与灵魂。",
        "suggested_time": "0.5-1天",
        "confidence": "high",
        "source_url": "https://example.test/dali-ancient-city",
        "source_urls": ["https://example.test/dali-ancient-city"],
        "evidence_notes": [],
        "caveats": [],
        "booking_info": None,
        "visit_requirements": None,
    }


def test_helloagents_poi_grounding_rejects_generic_homepage_evidence_and_keeps_detail_pages():
    grounding = PoiGrounding.model_validate(
        {
            "top_pois": [
                {
                    "name": "汕头小公园",
                    "kind": "district",
                    "confidence": "high",
                    "source_urls": [
                        "https://www.shantou.gov.cn/",
                        "https://www.xiaohongshu.com/explore/note-123",
                        "https://www.mafengwo.cn/poi/12345.html",
                    ],
                },
                {
                    "name": "汕头开埠文化陈列馆",
                    "kind": "attraction",
                    "confidence": "high",
                    "source_url": "https://www.shantou.gov.cn/",
                },
            ]
        }
    )

    assert grounding.featured_pois[0].source_urls == [
        "https://www.xiaohongshu.com/explore/note-123",
        "https://www.mafengwo.cn/poi/12345.html",
    ]
    assert grounding.featured_pois[0].confidence == "high"
    assert grounding.featured_pois[1].source_urls == []
    assert grounding.featured_pois[1].confidence == "low"

    ranking_grounding = PoiGrounding.model_validate(
        {
            "top_pois": [
                {
                    "name": "老妈宫戏台",
                    "kind": "attraction",
                    "confidence": "medium",
                    "source_urls": ["https://www.amap.com/ranking/shantou/scenic"],
                }
            ]
        }
    )
    assert ranking_grounding.featured_pois[0].source_urls == ["https://www.amap.com/ranking/shantou/scenic"]


def test_helloagents_poi_grounding_keeps_shared_regional_guide_for_multiple_pois():
    shared_url = "https://travel.example.test/shantou-old-town-guide"
    grounding = PoiGrounding.model_validate(
        {
            "top_pois": [
                {"name": "小公园开埠区", "kind": "district", "source_urls": [shared_url]},
                {"name": "侨批文物馆", "kind": "attraction", "source_urls": [shared_url]},
                {"name": "老妈宫戏台", "kind": "attraction", "source_urls": [shared_url]},
            ]
        }
    )

    assert [poi.source_urls for poi in grounding.featured_pois] == [[shared_url], [shared_url], [shared_url]]



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


def test_parse_planning_response_normalizes_natural_language_times():
    content = json.dumps(
        {
            "summary": "Dali trip.",
            "total_budget_estimate": 6800,
            "risks": [],
            "days": [
                {
                    "title": "Arrival day",
                    "summary": "Rail arrival and hotel check-in.",
                    "total_cost": 1200,
                    "items": [
                        {
                            "type": "transport",
                            "name": "Rail to Dali",
                            "start_time": "\u6839\u636e\u6240\u9009\u8f66\u6b21",
                            "end_time": "\u9884\u8ba1\u508d\u665a\u524d\u62b5\u8fbe",
                            "location": "Dali",
                            "score": 0.8,
                            "note": "Confirm the exact train before booking.",
                        },
                        {
                            "type": "transfer",
                            "name": "Transfer to hotel",
                            "start_time": "\u62b5\u8fbe\u540e",
                            "end_time": "\u7ea640-60\u5206\u949f",
                            "location": "Dali",
                            "score": 0.8,
                            "note": "",
                        },
                        {
                            "type": "hotel",
                            "name": "Hotel check-in",
                            "start_time": "\u5165\u4f4f",
                            "end_time": "\u79bb\u5e97",
                            "location": "Dali",
                            "score": 0.8,
                            "note": "",
                        },
                    ],
                }
            ],
        }
    )

    payload = parse_planning_response(content)

    assert [(item.start_time, item.end_time) for item in payload.days[0].items] == [
        ("09:00", "17:30"),
        ("18:00", "19:00"),
        ("19:30", "20:00"),
    ]
    assert "Original timing hint: start_time=" in payload.days[0].items[0].note


def test_parse_planning_response_normalizes_unknown_boolean_hints():
    content = json.dumps(
        {
            "summary": "Shanghai trip.",
            "total_budget_estimate": 6800,
            "risks": [],
            "transport_booking_summary": {
                "summary": "Rail is suitable.",
                "booking_required": "unknown",
            },
            "days": [
                {
                    "title": "City walk",
                    "summary": "Museum and waterfront.",
                    "total_cost": 1200,
                    "items": [
                        {
                            "type": "sight",
                            "name": "Shanghai Museum",
                            "start_time": "09:00",
                            "end_time": "11:00",
                            "location": "Shanghai",
                            "score": 0.9,
                            "note": "Start with a cultural anchor.",
                            "booking_info": {
                                "booking_required": "unknown",
                                "reservation_required": "required",
                            },
                            "visit_requirements": {
                                "reservation_policy": "unknown",
                                "timed_entry": "unknown",
                                "identity_required": "not_required",
                            },
                        }
                    ],
                }
            ],
        }
    )

    payload = parse_planning_response(content)
    item = payload.days[0].items[0]

    assert payload.transport_booking_summary is not None
    assert payload.transport_booking_summary.booking_required is False
    assert item.booking_info is not None
    assert item.booking_info.booking_required is False
    assert item.booking_info.reservation_required is True
    assert item.visit_requirements is not None
    assert item.visit_requirements.timed_entry is False
    assert item.visit_requirements.identity_required is False


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
