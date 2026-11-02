from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from travelmind_api.agents.base import (
    AgentTrace,
    PlannedDay,
    PlannedItem,
    PlanningRequest,
    PlanningResult,
    RefinementContext,
)
from travelmind_api.agents.planning_core import PlanningCore
from travelmind_api.agents.factory import build_orchestrator
from travelmind_api.agents.langgraph_orchestrator import LangGraphOrchestrator
from travelmind_api.agents.provider import normalize_agent_provider, select_agent_provider_for_new_job
from travelmind_api.agents.runtime import WorkflowCancelled, WorkflowRuntime
from travelmind_api.agents.workflows.trip_generation import (
    TripGenerationDependencies,
    build_brief_probe_graph,
    build_initial_state,
)
from travelmind_api.agents.workflows.trip_refinement import validate_refinement_target
from travelmind_api.prompts.roles.planning import build_brief_parser_prompt as build_legacy_brief_prompt
from travelmind_api.prompts.roles.trip import build_brief_parser_prompt
from travelmind_api.core.config import Settings
from travelmind_api.services.llm.config import LlmConfig
from travelmind_api.services.llm.config import LlmEndpointConfig
from travelmind_api.services.llm.role_invoker import (
    OpenAICompatibleRoleInvoker,
    RoleInvocation,
    RoleInvocationResult,
    get_role_invocation_failure_metadata,
)
from travelmind_api.services.planning.payloads import build_trip_request_payload
from travelmind_api.services.planning.role_models import PlanningBrief
from travelmind_api.services.maps.stub import StubMapsPoiProvider


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
    assert PlanningBrief is PlanningBrief
    assert build_legacy_brief_prompt() == build_brief_parser_prompt()
    assert PlanningCore(None)._build_trip_payload(_request()) == build_trip_request_payload(_request())


def test_result_assembly_is_owned_by_framework_neutral_planning_service():
    assert (
        PlanningCore._build_result_from_payload.__module__
        == "travelmind_api.services.planning.result_builder"
    )
    assert (
        PlanningCore._build_role_prompt_payload.__module__
        == "travelmind_api.services.planning.payloads"
    )


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


def test_openai_compatible_role_invoker_preserves_known_usage_and_retries():
    class FakeClient:
        def __init__(self, _config):
            self.last_citations = []
            self.last_usage = {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}
            self.last_retry_count = 1
            self.last_request_count = 2

        def create_chat_completion(self, **_kwargs):
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

    assert result.usage == {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}
    assert result.retry_count == 1
    assert result.request_count == 2
    assert result.checkpoint_metadata()["usage"]["total_tokens"] == 20


def test_role_invocation_failure_keeps_original_exception_and_sanitized_telemetry():
    class FailingClient:
        def __init__(self, _config):
            self.last_citations = ["https://example.test/partial"]
            self.last_usage = None
            self.last_retry_count = 1
            self.last_request_count = 2

        def create_chat_completion(self, **_kwargs):
            raise httpx.ReadTimeout("upstream timed out")

    invoker = OpenAICompatibleRoleInvoker(client_factory=FailingClient)
    with pytest.raises(httpx.ReadTimeout) as caught:
        invoker.invoke(
            RoleInvocation(
                role_name="brief_parser",
                prompt_version="trip.brief_parser.test",
                system_prompt="Return JSON.",
                input_payload={"trip_request": {"destination": "京都"}},
                endpoint=_endpoint(api_key="must-not-be-logged"),
            )
        )

    metadata = get_role_invocation_failure_metadata(caught.value)
    assert metadata["request_id"].startswith("llmreq_")
    assert metadata["endpoint_host"] == "llm.example.test"
    assert metadata["retry_count"] == 1
    assert metadata["request_count"] == 2
    assert metadata["usage"] is None
    assert "must-not-be-logged" not in json.dumps(metadata)


def test_langgraph_failed_role_log_includes_invocation_telemetry_without_secrets():
    events: list[tuple[str, dict[str, object]]] = []

    class FailingClient:
        def __init__(self, _config):
            self.last_citations = []
            self.last_usage = {"prompt_tokens": 9}
            self.last_retry_count = 1
            self.last_request_count = 2

        def create_chat_completion(self, **_kwargs):
            raise httpx.ReadTimeout("upstream timed out")

    orchestrator = LangGraphOrchestrator(
        LlmConfig(
            base_url="https://llm.example.test/v1",
            api_key="must-not-be-logged",
            model="test-model",
            wire_api="responses",
        ),
        role_invoker=OpenAICompatibleRoleInvoker(client_factory=FailingClient),
    )
    orchestrator._log_event = lambda event, **payload: events.append((event, payload))

    with pytest.raises(httpx.ReadTimeout):
        orchestrator.plan_trip(_request())

    failure = next(payload for event, payload in events if event == "langgraph_role_failed")
    assert failure["role"] == "brief_parser"
    assert failure["request_id"].startswith("llmreq_")
    assert failure["retry_count"] == 1
    assert failure["request_count"] == 2
    assert failure["usage"] == {"prompt_tokens": 9}
    assert "must-not-be-logged" not in json.dumps(failure)


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


@pytest.mark.parametrize(
    ("scope", "day_index", "message"),
    [
        ("day_plan", None, "day_index is required"),
        ("budget", 1, "day_index is only allowed"),
        ("unknown", None, "Unsupported refinement scope"),
        ("day_plan", 0, "greater than or equal to 1"),
    ],
)
def test_refinement_target_invariant_is_enforced_below_the_http_layer(scope, day_index, message):
    with pytest.raises(ValueError, match=message):
        validate_refinement_target(scope, day_index)

    assert validate_refinement_target("day_plan", 2) == ("day_plan", 2)
    assert validate_refinement_target("trip", None) == ("trip", None)


def test_langgraph_provider_normalizes_and_factory_builds_new_orchestrator():
    assert normalize_agent_provider("langgraph-workflow") == "langgraph"
    orchestrator = build_orchestrator(
        Settings(agent_provider="langgraph"),
        llm_config=LlmConfig(
            base_url="https://llm.example.test/v1",
            api_key="test-key",
            model="test-model",
            wire_api="responses",
        ),
        agent_provider="langgraph",
    )
    assert isinstance(orchestrator, LangGraphOrchestrator)


def test_langgraph_rollout_assignment_is_deterministic_and_honors_boundaries():
    assert select_agent_provider_for_new_job(
        "langgraph",
        rollout_key="job-1",
        langgraph_rollout_percent=0,
        fallback_provider="standard",
    ) == "standard"
    assert select_agent_provider_for_new_job(
        "langgraph",
        rollout_key="job-1",
        langgraph_rollout_percent=100,
        fallback_provider="standard",
    ) == "langgraph"
    assert select_agent_provider_for_new_job(
        "standard",
        rollout_key="job-1",
        langgraph_rollout_percent=100,
        fallback_provider="standard",
    ) == "standard"

    assignments = [
        select_agent_provider_for_new_job(
            "langgraph",
            rollout_key=f"job-{index}",
            langgraph_rollout_percent=50,
            fallback_provider="standard",
        )
        for index in range(100)
    ]
    assert assignments == [
        select_agent_provider_for_new_job(
            "langgraph",
            rollout_key=f"job-{index}",
            langgraph_rollout_percent=50,
            fallback_provider="standard",
        )
        for index in range(100)
    ]
    assert {"langgraph", "standard"}.issubset(set(assignments))


def test_partial_langgraph_rollout_requires_a_stable_job_key():
    with pytest.raises(ValueError, match="rollout_key"):
        select_agent_provider_for_new_job(
            "langgraph",
            rollout_key="",
            langgraph_rollout_percent=50,
            fallback_provider="standard",
        )


@pytest.mark.parametrize(
    ("initial_percent", "next_percent", "expected_provider"),
    [(0, 100, "standard"), (100, 0, "langgraph")],
)
def test_job_provider_snapshot_survives_rollout_switch(
    monkeypatch,
    initial_percent,
    next_percent,
    expected_provider,
):
    import travelmind_api.jobs.handlers as handlers

    job = SimpleNamespace(id="job-snapshot", payload_json={})
    user = SimpleNamespace(llm_agent_provider="langgraph")
    monkeypatch.setattr(
        handlers,
        "settings",
        Settings(
            langgraph_rollout_percent=initial_percent,
            langgraph_rollout_fallback_provider="standard",
        ),
    )
    first = handlers._resolve_job_agent_provider(user=user, job=job, existing_run=None)
    monkeypatch.setattr(
        handlers,
        "settings",
        Settings(
            langgraph_rollout_percent=next_percent,
            langgraph_rollout_fallback_provider="standard",
        ),
    )
    retry = handlers._resolve_job_agent_provider(user=user, job=job, existing_run=None)

    assert first == expected_provider
    assert retry == first
    assert job.payload_json["workflow_provider"] == expected_provider


def test_existing_workflow_run_provider_wins_over_job_snapshot_and_rollout(monkeypatch):
    import travelmind_api.jobs.handlers as handlers

    job = SimpleNamespace(id="job-existing-run", payload_json={"workflow_provider": "standard"})
    user = SimpleNamespace(llm_agent_provider="standard")
    existing_run = SimpleNamespace(provider="langgraph")
    monkeypatch.setattr(
        handlers,
        "settings",
        Settings(langgraph_rollout_percent=0, langgraph_rollout_fallback_provider="standard"),
    )

    resolved = handlers._resolve_job_agent_provider(
        user=user,
        job=job,
        existing_run=existing_run,
    )

    assert resolved == "langgraph"
    assert job.payload_json["workflow_provider"] == "standard"


def test_settings_rejects_invalid_langgraph_rollout_percentage():
    with pytest.raises(ValueError, match="less than or equal to 100"):
        Settings(langgraph_rollout_percent=101)


def test_langgraph_orchestrator_runs_six_roles_without_helloagents_runtime(monkeypatch):
    from test_llm_orchestrator import _fake_planning_core_module
    import travelmind_api.agents.langgraph_orchestrator as langgraph_module

    calls: list[str] = []
    invocations: list[RoleInvocation] = []
    limited_endpoints: list[tuple[str, str, str]] = []
    fake_module = _fake_planning_core_module(calls)

    class RecordingLimiter:
        @contextmanager
        def acquire(self, identity, *, timeout_seconds, cancellation_check=None):
            assert timeout_seconds > 0
            if cancellation_check is not None:
                cancellation_check()
            limited_endpoints.append(identity)
            yield

    class FixtureRoleInvoker:
        def invoke(self, invocation: RoleInvocation) -> RoleInvocationResult:
            invocations.append(invocation)
            agent = fake_module.SimpleAgent(
                name=invocation.role_name,
                llm=SimpleNamespace(kwargs={}),
                system_prompt=invocation.system_prompt,
            )
            content = agent.run(json.dumps(dict(invocation.input_payload), ensure_ascii=False))
            return RoleInvocationResult(
                request_id=f"llmreq-{invocation.role_name}",
                role_name=invocation.role_name,
                content=content,
                model=invocation.endpoint.model,
                provider_protocol=invocation.endpoint.provider_protocol,
                wire_api=invocation.endpoint.wire_api,
                endpoint_host="llm.example.test",
                prompt_version=invocation.prompt_version,
                latency_ms=1,
                citations=[],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                retry_count=1,
                request_count=2,
            )

    monkeypatch.setattr(langgraph_module, "verify_daily_forecast_pages", lambda value, _config: value)
    monkeypatch.setattr(langgraph_module, "verify_transport_candidate_pages", lambda value, _config: value)
    monkeypatch.setattr(langgraph_module, "verify_hotel_pages", lambda value, _config: value)
    monkeypatch.setattr(
        langgraph_module,
        "verify_poi_open_days",
        lambda value, **_kwargs: value,
    )
    request = _request().model_copy(
        update={
            "title": "Kyoto weekend",
            "origin": "Osaka",
            "destination": "Kyoto",
            "start_date": date(2026, 4, 14),
            "end_date": date(2026, 4, 15),
            "interests": ["temples", "coffee"],
            "accommodation_preference": "Quiet boutique hotel",
            "locale": "en-US",
        }
    )
    orchestrator = LangGraphOrchestrator(
        LlmConfig(
            base_url="https://llm.example.test/v1",
            api_key="test-key",
            model="Web/grok-chat-fast",
            wire_api="responses",
        ),
        maps_provider=StubMapsPoiProvider(),
        role_invoker=FixtureRoleInvoker(),
        concurrency_limiter=RecordingLimiter(),
    )

    result = orchestrator.plan_trip(request)
    checkpoint = orchestrator.get_graph_state()

    assert result.trace.provider == "langgraph"
    assert result.trace.license_notice is None
    assert len(result.days) == 2
    assert calls[0] == "brief_parser"
    assert set(calls[1:3]) == {"poi_specialist", "weather_specialist"}
    assert set(calls[3:5]) == {"hotel_specialist", "transport_specialist"}
    assert calls[-1] == "itinerary_planner"
    assert len(invocations) == 6
    assert next(call for call in invocations if call.role_name == "poi_specialist").max_request_attempts == 1
    assert next(call for call in invocations if call.role_name == "poi_specialist").endpoint.timeout_seconds > 299
    assert next(call for call in invocations if call.role_name == "itinerary_planner").endpoint.timeout_seconds > 299
    assert all(
        call.endpoint.timeout_seconds > 119
        for call in invocations
        if call.role_name not in {"poi_specialist", "itinerary_planner"}
    )
    assert checkpoint is not None
    assert checkpoint["repair_count"] == 0
    assert set(checkpoint["role_results"]) == set(calls)
    assert all(run.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15} for run in result.trace.agent_runs)
    assert all(run.retry_count == 1 for run in result.trace.agent_runs)
    assert all(run.request_count == 2 for run in result.trace.agent_runs)
    assert not any(run.cache_reused for run in result.trace.agent_runs)
    assert len(limited_endpoints) == 4
    assert {identity[2] for identity in limited_endpoints} == {"test-key"}
    serialized = json.dumps(checkpoint, ensure_ascii=False, sort_keys=True)
    assert "test-key" not in serialized
    assert "user-1" not in serialized

    orchestrator._mark_reused_agent_runs(
        result,
        {"brief_parser": {"request_id": "llmreq-brief_parser"}},
    )
    assert next(run for run in result.trace.agent_runs if run.key == "brief_parser").cache_reused is True
    assert not any(run.cache_reused for run in result.trace.agent_runs if run.key != "brief_parser")


def test_shared_endpoint_queue_wait_does_not_consume_role_request_budget(monkeypatch):
    import travelmind_api.agents.langgraph_orchestrator as langgraph_module

    clock = [1000.0]
    limiter_timeouts: list[float] = []
    invocations: list[RoleInvocation] = []

    class WaitingLimiter:
        @contextmanager
        def acquire(self, _identity, *, timeout_seconds, cancellation_check=None):
            limiter_timeouts.append(timeout_seconds)
            if cancellation_check is not None:
                cancellation_check()
            clock[0] += 100.0
            yield

    class DelayedInvoker:
        def invoke(self, invocation: RoleInvocation) -> RoleInvocationResult:
            invocations.append(invocation)
            clock[0] += 119.0
            return RoleInvocationResult(
                request_id="llmreq-transport",
                role_name=invocation.role_name,
                content="{}",
                model=invocation.endpoint.model,
                provider_protocol=invocation.endpoint.provider_protocol,
                wire_api=invocation.endpoint.wire_api,
                endpoint_host="llm.example.test",
                prompt_version=invocation.prompt_version,
                latency_ms=119_000,
                citations=[],
                usage=None,
            )

    config = LlmConfig(
        base_url="https://llm.example.test/v1",
        api_key="shared-key",
        model="Console/grok-4.20-0309-reasoning",
        wire_api="responses",
    )
    orchestrator = LangGraphOrchestrator(
        config,
        maps_provider=StubMapsPoiProvider(),
        role_invoker=DelayedInvoker(),
        concurrency_limiter=WaitingLimiter(),
    )
    request = _request()
    orchestrator._workflow_runtime = WorkflowRuntime(run_id="run-queue-budget")
    orchestrator._workflow_request = request
    orchestrator._workflow_role_configs = orchestrator._build_role_configs(request)
    orchestrator._workflow_llm_configs = orchestrator._build_role_llm_configs()
    weather_endpoint = orchestrator._effective_role_endpoint(
        orchestrator._workflow_role_configs["weather_specialist"],
        orchestrator._workflow_llm_configs["weather_specialist"],
    )
    assert orchestrator._role_queue_wait_timeout_seconds("weather_specialist", weather_endpoint) == pytest.approx(300.0)
    monkeypatch.setattr(langgraph_module.time, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(orchestrator, "_augment_payload_with_tool_results", lambda _role, payload: payload)
    monkeypatch.setattr(
        orchestrator,
        "_build_role_prompt_payload",
        lambda payload, *, role_name: {"role": role_name, **payload},
    )

    result, _metadata = orchestrator._invoke_workflow_role("transport_specialist", {})

    assert result.role_name == "transport_specialist"
    assert limiter_timeouts == [pytest.approx(120.0)]
    assert invocations[0].endpoint.timeout_seconds == pytest.approx(120.0)
    assert clock[0] == pytest.approx(1219.0)


def test_langgraph_orchestrator_repairs_one_invalid_draft(monkeypatch):
    from test_llm_orchestrator import _fake_planning_core_module
    import travelmind_api.agents.langgraph_orchestrator as langgraph_module

    calls: list[str] = []
    fake_module = _fake_planning_core_module(calls)
    planner_calls = 0

    class RepairingFixtureInvoker:
        def invoke(self, invocation: RoleInvocation) -> RoleInvocationResult:
            nonlocal planner_calls
            agent = fake_module.SimpleAgent(
                name=invocation.role_name,
                llm=SimpleNamespace(kwargs={}),
                system_prompt=invocation.system_prompt,
            )
            content = agent.run(json.dumps(dict(invocation.input_payload), ensure_ascii=False))
            if invocation.role_name == "itinerary_planner":
                planner_calls += 1
                if planner_calls == 1:
                    invalid = json.loads(content)
                    invalid["days"][0]["items"][1]["start_time"] = "10:30"
                    content = json.dumps(invalid)
                elif invocation.input_payload.get("repair_mode") == "slot-patch.v1":
                    # The fixture model follows the new local patch wire contract.
                    reference = json.loads(content)
                    updates = []
                    for ref, allowed in invocation.input_payload["repair_contract"]["allowed_item_fields"].items():
                        day, index = map(int, ref.removeprefix("d").split("i"))
                        item = reference["days"][day - 1]["items"][index - 1]
                        changes = {key: value for key, value in item.items() if key in allowed}
                        updates.append({"item_ref": ref, "changes": changes})
                    content = json.dumps({"item_updates": updates})
            return RoleInvocationResult(
                request_id=f"llmreq-{invocation.role_name}-{planner_calls}",
                role_name=invocation.role_name,
                content=content,
                model=invocation.endpoint.model,
                provider_protocol=invocation.endpoint.provider_protocol,
                wire_api=invocation.endpoint.wire_api,
                endpoint_host="llm.example.test",
                prompt_version=invocation.prompt_version,
                latency_ms=1,
                citations=[],
                usage=None,
            )

    monkeypatch.setattr(langgraph_module, "verify_daily_forecast_pages", lambda value, _config: value)
    monkeypatch.setattr(langgraph_module, "verify_transport_candidate_pages", lambda value, _config: value)
    monkeypatch.setattr(langgraph_module, "verify_hotel_pages", lambda value, _config: value)
    monkeypatch.setattr(langgraph_module, "verify_poi_open_days", lambda value, **_kwargs: value)
    request = _request().model_copy(
        update={
            "title": "Kyoto weekend",
            "origin": "Osaka",
            "destination": "Kyoto",
            "start_date": date(2026, 4, 14),
            "end_date": date(2026, 4, 15),
            "interests": ["temples", "coffee"],
            "accommodation_preference": "Quiet boutique hotel",
            "locale": "en-US",
        }
    )
    orchestrator = LangGraphOrchestrator(
        LlmConfig(
            base_url="https://llm.example.test/v1",
            api_key="test-key",
            model="test-model",
            wire_api="responses",
        ),
        maps_provider=StubMapsPoiProvider(),
        role_invoker=RepairingFixtureInvoker(),
    )

    result = orchestrator.plan_trip(request)
    checkpoint = orchestrator.get_graph_state()

    assert len(result.days) == 2
    assert planner_calls == 2
    assert checkpoint is not None
    assert checkpoint["repair_count"] == 1
    assert checkpoint["validation_errors"] == []
    assert any("required one deterministic-validation repair" in note for note in result.trace.notes)


def test_langgraph_day_refinement_preserves_other_days_and_uses_server_context():
    current = StubMapsPoiProvider()

    request = _request().model_copy(update={"locale": "en-US"})
    current_plan = PlanningResult(
        summary="Existing two-day itinerary.",
        total_budget_estimate=2000,
        risks=[],
        days=[
            PlannedDay(
                day_index=1,
                title="Original day 1",
                summary="Keep this day unchanged.",
                total_cost=1000,
                items=[
                    PlannedItem(
                        id="item-original-day-1",
                        type="sight",
                        name="Original Temple",
                        start_time="09:00",
                        end_time="11:00",
                        location="Kyoto",
                        score=0.9,
                        note="Original note.",
                    )
                ],
            ),
            PlannedDay(
                day_index=2,
                title="Original day 2",
                summary="This day may change.",
                total_cost=1000,
                items=[
                    PlannedItem(
                        id="item-original-day-2",
                        type="sight",
                        name="Original Garden",
                        start_time="09:00",
                        end_time="11:00",
                        location="Kyoto",
                        score=0.8,
                        note="Original second-day note.",
                    )
                ],
            ),
        ],
        trace=AgentTrace(provider="fixture", workflow_id="fixture", notes=[]),
    )
    invocations: list[RoleInvocation] = []

    class RefineInvoker:
        def invoke(self, invocation: RoleInvocation) -> RoleInvocationResult:
            invocations.append(invocation)
            payload = {
                "summary": "Refined only the selected day.",
                "total_budget_estimate": 4500,
                "risks": [],
                "days": [
                    {
                        "title": "MUST NOT REPLACE DAY 1",
                        "summary": "The model attempted to replace an unaffected day.",
                        "total_cost": 1000,
                        "items": [
                            {
                                "type": "sight",
                                "name": "Wrong day one stop",
                                "start_time": "09:00",
                                "end_time": "11:00",
                                "location": "Kyoto",
                                "score": 0.5,
                                "note": "Must be discarded.",
                            }
                        ],
                    },
                    {
                        "title": "Refined day 2",
                        "summary": "A slower second day.",
                        "total_cost": 900,
                        "items": [
                            {
                                "type": "sight",
                                "name": "Kyoto Garden",
                                "start_time": "10:00",
                                "end_time": "12:00",
                                "location": "Kyoto",
                                "score": 0.9,
                                "note": "A slower replacement.",
                            }
                        ],
                    },
                ],
            }
            return RoleInvocationResult(
                request_id="llmreq-refine",
                role_name=invocation.role_name,
                content=json.dumps(payload),
                model=invocation.endpoint.model,
                provider_protocol=invocation.endpoint.provider_protocol,
                wire_api=invocation.endpoint.wire_api,
                endpoint_host="llm.example.test",
                prompt_version=invocation.prompt_version,
                latency_ms=1,
                citations=["https://guide.example.test/kyoto"],
                usage=None,
            )

    orchestrator = LangGraphOrchestrator(
        LlmConfig(
            base_url="https://llm.example.test/v1",
            api_key="test-key",
            model="test-model",
            wire_api="responses",
        ),
        maps_provider=current,
        role_invoker=RefineInvoker(),
    )
    orchestrator.set_execution_context(run_id="run-refine-day-2")
    refined = orchestrator.refine_trip(
        request,
        current_plan,
        instruction="Make day 2 slower.",
        scope="day_plan",
        day_index=2,
        context=RefinementContext(
            messages=[{"role": "user", "text": "Prefer gardens."}],
            uploaded_guides=[{"title": "My Kyoto guide", "content": "Use quiet gardens."}],
            community_sources=[{"title": "Kyoto slow trip", "itinerary_summary": "Avoid rushing."}],
        ),
    )

    assert refined.days[0].model_dump(mode="json") == current_plan.days[0].model_dump(mode="json")
    assert refined.days[1].title == "Refined day 2"
    assert refined.trace.provider == "langgraph"
    assert any(note == "Refined day 2." for note in refined.trace.notes)
    assert len(invocations) == 1
    serialized_input = json.dumps(dict(invocations[0].input_payload), ensure_ascii=False)
    assert "My Kyoto guide" in serialized_input
    assert "Kyoto slow trip" in serialized_input
