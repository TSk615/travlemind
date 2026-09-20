from __future__ import annotations

import json
from datetime import date, timedelta
from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

from travelmind_api.agents.base import PlanningRequest
from travelmind_api.agents.runtime import WorkflowRuntime
from travelmind_api.agents.stub import StubOrchestrator
from travelmind_api.agents.workflows.trip_generation import (
    TripGenerationDependencies,
    build_brief_probe_graph,
    build_initial_state,
)
from travelmind_api.core.config import Settings
from travelmind_api.services.llm.config import LlmEndpointConfig
from travelmind_api.services.llm.role_invoker import RoleInvocation, RoleInvocationResult
from travelmind_api.services.workflow_store import workflow_checkpointer


def _request(*, trip_id: str = "trip-recovery") -> PlanningRequest:
    return PlanningRequest(
        trip_id=trip_id,
        user_id="user-recovery",
        title="Kyoto recovery",
        origin="Osaka",
        destination="Kyoto",
        start_date=date(2026, 10, 10),
        end_date=date(2026, 10, 11),
        budget=5000,
        travelers=2,
        interests=["temples", "coffee"],
        accommodation_preference="quiet hotel",
        pace="balanced",
        transport_mode="rail",
        locale="en-US",
    )


def _endpoint() -> LlmEndpointConfig:
    return LlmEndpointConfig(
        base_url="https://llm.example.test/v1",
        api_key="checkpoint-secret",
        model="test-model",
        wire_api="responses",
        provider_protocol="openai",
    )


def _brief_result(invocation: RoleInvocation) -> RoleInvocationResult:
    return RoleInvocationResult(
        request_id="llmreq-recovered",
        role_name=invocation.role_name,
        content=json.dumps(
            {
                "destination": "Kyoto",
                "trip_days": 2,
                "budget_band": "midrange",
                "budget_is_hard_constraint": True,
                "budget_priority": "transport",
                "allow_budget_flex": False,
                "pace": "balanced",
                "must_have": ["temples"],
                "avoid": [],
                "transport": "rail",
                "accommodation": "quiet hotel",
                "interests": ["temples", "coffee"],
                "planning_constraints": [],
            }
        ),
        model=invocation.endpoint.model,
        provider_protocol=invocation.endpoint.provider_protocol,
        wire_api=invocation.endpoint.wire_api,
        endpoint_host="llm.example.test",
        prompt_version=invocation.prompt_version,
        latency_ms=1,
        citations=[],
        usage=None,
    )


def test_sqlite_checkpointer_resumes_after_connection_restart(tmp_path):
    checkpoint_path = tmp_path / "workflow-checkpoints.db"
    settings = Settings(environment="test", workflow_checkpoint_url=str(checkpoint_path))
    endpoint = _endpoint()
    request = _request()
    run_id = "run-process-restart"

    class FailingInvoker:
        def invoke(self, invocation: RoleInvocation) -> RoleInvocationResult:
            raise RuntimeError("simulated worker exit")

    with workflow_checkpointer(settings) as saver:
        dependencies = TripGenerationDependencies(
            role_invoker=FailingInvoker(),
            brief_endpoint=endpoint,
            runtime=WorkflowRuntime(run_id=run_id),
        )
        graph = build_brief_probe_graph(dependencies, checkpointer=saver)
        initial = build_initial_state(request, run_id=run_id, brief_endpoint=endpoint)
        with pytest.raises(RuntimeError, match="simulated worker exit"):
            graph.invoke(initial, config={"configurable": {"thread_id": run_id}})

    calls: list[str] = []

    class RecoveredInvoker:
        def invoke(self, invocation: RoleInvocation) -> RoleInvocationResult:
            calls.append(invocation.role_name)
            return _brief_result(invocation)

    with workflow_checkpointer(settings) as saver:
        dependencies = TripGenerationDependencies(
            role_invoker=RecoveredInvoker(),
            brief_endpoint=endpoint,
            runtime=WorkflowRuntime(run_id=run_id),
        )
        graph = build_brief_probe_graph(dependencies, checkpointer=saver)
        result = graph.invoke(None, config={"configurable": {"thread_id": run_id}})
        persisted = graph.get_state({"configurable": {"thread_id": run_id}}).values

    assert result["planning_brief"]["destination"] == "Kyoto"
    assert calls == ["brief_parser"]
    assert "checkpoint-secret" not in json.dumps(persisted, sort_keys=True)


def test_parallel_successful_branch_is_not_repeated_after_other_branch_fails(tmp_path):
    class ParallelState(TypedDict, total=False):
        left: str
        right: str
        joined: bool

    checkpoint_path = tmp_path / "parallel-checkpoints.db"
    settings = Settings(environment="test", workflow_checkpoint_url=str(checkpoint_path))
    calls = {"left": 0, "right": 0, "join": 0}
    fail_right = True

    def build_graph(saver):
        def left(_state):
            calls["left"] += 1
            return {"left": "preserved"}

        def right(_state):
            calls["right"] += 1
            if fail_right:
                raise RuntimeError("right branch failed")
            return {"right": "recovered"}

        def join(_state):
            calls["join"] += 1
            return {"joined": True}

        builder = StateGraph(ParallelState)
        builder.add_node("left", left)
        builder.add_node("right", right)
        builder.add_node("join", join)
        builder.add_edge(START, "left")
        builder.add_edge(START, "right")
        builder.add_edge(["left", "right"], "join")
        builder.add_edge("join", END)
        return builder.compile(checkpointer=saver)

    config = {"configurable": {"thread_id": "run-parallel-recovery"}}
    with workflow_checkpointer(settings) as saver:
        with pytest.raises(RuntimeError, match="right branch failed"):
            build_graph(saver).invoke({}, config=config)

    fail_right = False
    with workflow_checkpointer(settings) as saver:
        result = build_graph(saver).invoke(None, config=config)

    assert result == {"left": "preserved", "right": "recovered", "joined": True}
    assert calls == {"left": 1, "right": 2, "join": 1}


def _register_and_create_trip(client):
    registration = client.post(
        "/api/v1/auth/register",
        json={"name": "Workflow Tester", "email": "workflow@example.com", "password": "supersecure123"},
    )
    assert registration.status_code == 200, registration.text
    start = date.today() + timedelta(days=30)
    response = client.post(
        "/api/v1/trips",
        json={
            "title": "Durable Kyoto",
            "origin": "Shanghai",
            "destination": "Kyoto",
            "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=1)).isoformat(),
            "budget": 5000,
            "travelers": 2,
            "interests": ["temples"],
            "accommodation_preference": "quiet",
            "pace": "balanced",
            "transport_mode": "rail",
        },
    )
    assert response.status_code == 200, response.text
    return registration.json()["data"]["id"], response.json()["data"]["id"]


def _create_bound_run(user_id: str, trip_id: str):
    from travelmind_api.core.database import SessionLocal
    from travelmind_api.db.models import Trip
    from travelmind_api.services.job_service import create_job
    from travelmind_api.services.workflow_store import bind_workflow_run

    with SessionLocal() as session:
        trip = session.get(Trip, trip_id)
        job = create_job(
            session,
            job_type="trip.generate",
            owner_user_id=user_id,
            trip_id=trip_id,
            payload={"trip_id": trip_id},
        )
        run = bind_workflow_run(session, job=job, trip=trip, provider="langgraph")
        assert run is not None
        session.commit()
        return job.id, run.id


def test_workflow_commit_is_idempotent_and_creates_one_image_job(client):
    from travelmind_api.core.database import SessionLocal
    from travelmind_api.db.models import JobRecord, WorkflowRun
    from travelmind_api.jobs.handlers import _commit_langgraph_trip_result

    user_id, trip_id = _register_and_create_trip(client)
    first_job_id, run_id = _create_bound_run(user_id, trip_id)
    result = StubOrchestrator().plan_trip(_request(trip_id=trip_id))
    state = {"input_fingerprint": "a" * 64, "role_results": {}}

    first = _commit_langgraph_trip_result(
        job_id=first_job_id,
        run_id=run_id,
        result=result,
        graph_state=state,
    )
    second = _commit_langgraph_trip_result(
        job_id=first_job_id,
        run_id=run_id,
        result=result,
        graph_state=state,
    )

    assert second == first
    with SessionLocal() as session:
        run = session.get(WorkflowRun, run_id)
        assert run is not None
        assert run.committed_job_id == first_job_id
        assert run.input_fingerprint == "a" * 64
        image_jobs = (
            session.query(JobRecord)
            .filter(JobRecord.trip_id == trip_id, JobRecord.type == "trip.image_enrich")
            .all()
        )
        assert len(image_jobs) == 1
        assert image_jobs[0].id == first["followup_job_id"]


def test_retry_job_reuses_durable_run_without_legacy_checkpoint(client):
    from travelmind_api.core.database import SessionLocal
    from travelmind_api.db.models import JobRecord, WorkflowRun

    user_id, trip_id = _register_and_create_trip(client)
    first_job_id, run_id = _create_bound_run(user_id, trip_id)
    with SessionLocal() as session:
        first_job = session.get(JobRecord, first_job_id)
        first_job.status = "failed"
        first_job.error_message = "simulated worker loss"
        run = session.get(WorkflowRun, run_id)
        run.status = "failed"
        run.failure_message = "simulated worker loss"
        session.commit()

    detail = client.get(f"/api/v1/jobs/{first_job_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["can_resume"] is True
    retry = client.post(f"/api/v1/jobs/{first_job_id}/retry")
    assert retry.status_code == 200, retry.text
    retry_job_id = retry.json()["data"]["job_id"]

    with SessionLocal() as session:
        first_job = session.get(JobRecord, first_job_id)
        retry_job = session.get(JobRecord, retry_job_id)
        run = session.get(WorkflowRun, run_id)
        assert first_job.workflow_run_id == run_id
        assert retry_job.workflow_run_id == run_id
        assert run.original_job_id == first_job_id
        assert run.current_job_id == retry_job_id
        assert retry_job.payload_json["resume_from_job_id"] == first_job_id
        assert "resume_checkpoint" not in retry_job.payload_json


def test_cancelled_workflow_does_not_commit_trip_result(client):
    from travelmind_api.core.database import SessionLocal
    from travelmind_api.db.models import JobRecord, Trip, WorkflowRun
    from travelmind_api.jobs.handlers import JobCancelledError, _commit_langgraph_trip_result

    user_id, trip_id = _register_and_create_trip(client)
    job_id, run_id = _create_bound_run(user_id, trip_id)
    result = StubOrchestrator().plan_trip(_request(trip_id=trip_id))
    with SessionLocal() as session:
        job = session.get(JobRecord, job_id)
        job.status = "cancelled"
        session.commit()

    with pytest.raises(JobCancelledError):
        _commit_langgraph_trip_result(
            job_id=job_id,
            run_id=run_id,
            result=result,
            graph_state={"input_fingerprint": "b" * 64},
        )

    with SessionLocal() as session:
        assert session.get(Trip, trip_id).itinerary_json is None
        assert session.get(WorkflowRun, run_id).status == "cancelled"


def test_stale_workflow_cannot_overwrite_newer_trip_edit(client):
    from travelmind_api.core.database import SessionLocal
    from travelmind_api.db.models import Trip, WorkflowRun
    from travelmind_api.jobs.handlers import _commit_langgraph_trip_result
    from travelmind_api.services.workflow_store import WorkflowCommitConflict

    user_id, trip_id = _register_and_create_trip(client)
    job_id, run_id = _create_bound_run(user_id, trip_id)
    result = StubOrchestrator().plan_trip(_request(trip_id=trip_id))
    with SessionLocal() as session:
        trip = session.get(Trip, trip_id)
        trip.title = "Newer manual title"
        trip.updated_at = trip.updated_at + timedelta(seconds=1)
        session.commit()

    with pytest.raises(WorkflowCommitConflict):
        _commit_langgraph_trip_result(
            job_id=job_id,
            run_id=run_id,
            result=result,
            graph_state={"input_fingerprint": "c" * 64},
        )

    with SessionLocal() as session:
        trip = session.get(Trip, trip_id)
        run = session.get(WorkflowRun, run_id)
        assert trip.itinerary_json is None
        assert trip.title == "Newer manual title"
        assert run.status == "conflicted"
        assert run.committed_at is None
