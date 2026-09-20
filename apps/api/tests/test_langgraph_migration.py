from __future__ import annotations

import json
from datetime import date

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from travelmind_api.agents.base import PlanningRequest
from travelmind_api.agents.helloagents import HelloAgentsBrief, HelloAgentsOrchestrator
from travelmind_api.agents.runtime import WorkflowCancelled, WorkflowRuntime
from travelmind_api.agents.workflows.trip_generation import (
    TripGenerationDependencies,
    build_brief_probe_graph,
    build_initial_state,
)
from travelmind_api.prompts.roles.helloagents import build_brief_parser_prompt as build_legacy_brief_prompt
from travelmind_api.prompts.roles.trip import build_brief_parser_prompt
from travelmind_api.services.llm.config import LlmEndpointConfig
from travelmind_api.services.llm.role_invoker import (
    OpenAICompatibleRoleInvoker,
    RoleInvocation,
    RoleInvocationResult,
)
from travelmind_api.services.planning.payloads import build_trip_request_payload
from travelmind_api.services.planning.role_models import PlanningBrief


def _request() -> PlanningRequest:
    return PlanningRequest(
        trip_id="trip-langgraph-probe",
        user_id="user-1",
        title="京都周末",
        origin="上海",
        destination="京都",
        start_date=date(2026, 10, 10),
        end_date=date(2026, 10, 11),
        budget=8000,
        travelers=2,
        interests=["寺庙", "咖啡"],
        accommodation_preference="安静精品酒店",
        pace="balanced",
        transport_mode="rail",
        locale="zh-CN",
    )


def _endpoint(*, api_key: str = "secret-key", model: str = "test-model") -> LlmEndpointConfig:
    return LlmEndpointConfig(
        base_url="https://llm.example.test/v1",
        api_key=api_key,
        model=model,
        wire_api="responses",
        provider_protocol="openai",
    )


class _RecordingInvoker:
    def __init__(self) -> None:
        self.calls: list[RoleInvocation] = []

    def invoke(self, invocation: RoleInvocation) -> RoleInvocationResult:
        self.calls.append(invocation)
        return RoleInvocationResult(
            request_id="llmreq-test",
            role_name=invocation.role_name,
            content=json.dumps(
                {
                    "destination": "京都",
                    "trip_days": 2,
                    "budget_band": "midrange",
                    "budget_is_hard_constraint": True,
                    "budget_priority": "交通与门票优先",
                    "allow_budget_flex": False,
                    "pace": "balanced",
                    "must_have": ["寺庙"],
                    "avoid": ["频繁折返"],
                    "transport": "rail",
                    "accommodation": "安静精品酒店",
                    "interests": ["寺庙", "咖啡"],
                    "planning_constraints": ["路线连续"],
                },
                ensure_ascii=False,
            ),
            model=invocation.endpoint.model,
            provider_protocol=invocation.endpoint.provider_protocol,
            wire_api=invocation.endpoint.wire_api,
            endpoint_host="llm.example.test",
            prompt_version=invocation.prompt_version,
            latency_ms=12,
            citations=["https://example.test/source"],
            usage=None,
        )


def test_framework_neutral_brief_schema_and_prompt_remain_legacy_compatible():
    assert HelloAgentsBrief is PlanningBrief
    assert build_legacy_brief_prompt() == build_brief_parser_prompt()
    assert HelloAgentsOrchestrator(None)._build_trip_payload(_request()) == build_trip_request_payload(_request())


def test_openai_compatible_role_invoker_preserves_citations_and_unknown_usage():
    clients = []

    class FakeClient:
        def __init__(self, config):
            self.config = config
            self.last_citations = []
            self.messages = []
            clients.append(self)

        def create_chat_completion(self, *, messages, temperature, max_tokens, stream):
            self.messages = messages
            self.last_citations = ["https://example.test/a", "https://example.test/a"]
            return '{"destination":"京都","trip_days":2}'

    result = OpenAICompatibleRoleInvoker(client_factory=FakeClient).invoke(
        RoleInvocation(
            role_name="brief_parser",
            prompt_version="trip.brief_parser.test",
            system_prompt="Return JSON.",
            input_payload={"trip_request": {"destination": "京都"}},
            endpoint=_endpoint(),
        )
    )

    assert result.content.startswith("{")
    assert result.citations == ["https://example.test/a"]
    assert result.usage is None
    assert result.endpoint_host == "llm.example.test"
    assert "secret-key" not in json.dumps(result.checkpoint_metadata())
    assert clients[0].messages[0] == {"role": "system", "content": "Return JSON."}


def test_brief_probe_runs_without_helloagents_and_checkpoint_state_excludes_credentials():
    invoker = _RecordingInvoker()
    progress = []
    runtime = WorkflowRuntime(
        run_id="run-brief-probe",
        owner_user_id="user-1",
        progress_callback=lambda *args: progress.append(args),
    )
    endpoint = _endpoint(api_key="must-never-enter-checkpoint")
    checkpointer = InMemorySaver()
    dependencies = TripGenerationDependencies(
        role_invoker=invoker,
        brief_endpoint=endpoint,
        runtime=runtime,
    )
    graph = build_brief_probe_graph(dependencies, checkpointer=checkpointer)
    initial_state = build_initial_state(_request(), run_id=runtime.run_id, brief_endpoint=endpoint)
    config = {"configurable": {"thread_id": runtime.run_id}}

    result = graph.invoke(initial_state, config=config)
    restored = graph.get_state(config).values

    assert result["planning_brief"]["destination"] == "京都"
    assert restored["planning_brief"] == result["planning_brief"]
    assert restored["role_results"]["brief_parser"]["usage"] is None
    assert restored["role_results"]["brief_parser"]["citations"] == ["https://example.test/source"]
    assert progress == [("brief_parser", "Brief parser", "Compresses the trip input into a compact planning brief.", 24)]
    assert len(invoker.calls) == 1
    serialized_state = json.dumps(restored, ensure_ascii=False, sort_keys=True)
    assert "must-never-enter-checkpoint" not in serialized_state
    assert "user-1" not in serialized_state


def test_brief_probe_fingerprint_tracks_model_but_not_api_key():
    request = _request()
    first = build_initial_state(request, run_id="run-a", brief_endpoint=_endpoint(api_key="key-a"))
    same = build_initial_state(request, run_id="run-b", brief_endpoint=_endpoint(api_key="key-b"))
    changed = build_initial_state(
        request,
        run_id="run-c",
        brief_endpoint=_endpoint(api_key="key-c", model="different-model"),
    )

    assert first["input_fingerprint"] == same["input_fingerprint"]
    assert first["input_fingerprint"] != changed["input_fingerprint"]


def test_runtime_checks_cancellation_before_progress_callback():
    called = []
    runtime = WorkflowRuntime(
        run_id="run-cancelled",
        progress_callback=lambda *args: called.append(args),
        cancellation_check=lambda: True,
    )

    with pytest.raises(WorkflowCancelled):
        runtime.emit_progress("brief_parser", "Brief parser", "Cancelled", 24)
    assert called == []

