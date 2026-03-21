import json
from datetime import date

import httpx

from travelmind_api.agents.base import PlanningRequest, PlanningResult
from travelmind_api.agents.factory import build_orchestrator
from travelmind_api.agents.openai_compatible import OpenAICompatibleOrchestrator
from travelmind_api.agents.stub import StubOrchestrator
from travelmind_api.core.config import Settings
from travelmind_api.services.llm import LlmConfig, OpenAICompatibleClient
from travelmind_api.services.maps import StubMapsPoiProvider



def _planning_request() -> PlanningRequest:
    return PlanningRequest(
        trip_id="trip_test",
        title="Kyoto calm days",
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