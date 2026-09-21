from __future__ import annotations

from pathlib import Path

import pytest

from travelmind_api.agents.base import AgentRunStep, AgentTrace
from travelmind_api.services.llm.config import LlmConfig, LlmEndpointConfig
from travelmind_api.services.workflow_evaluation import (
    REQUIRED_REPLAY_CATEGORIES,
    ReplayDefinition,
    ReplayObservation,
    build_replay_artifact,
    estimate_trace_cost_usd,
    evaluate_replay_gate,
    hard_constraint_violations,
    load_replay_artifact,
    load_replay_cases,
    replay_configuration_fingerprint,
)


FIXTURE = Path(__file__).parent / "fixtures" / "langgraph-replay-cases.json"
CONFIG_FINGERPRINT = "a" * 64


def _trace_with_usage(*usage_rows):
    return AgentTrace(
        provider="langgraph",
        workflow_id="run-cost",
        notes=[],
        agent_runs=[
            AgentRunStep(
                key=f"role-{index}",
                title="Role",
                description="Role",
                usage=usage,
            )
            for index, usage in enumerate(usage_rows)
        ],
    )


def test_trace_cost_uses_all_role_usage_and_missing_usage_stays_unknown():
    trace = _trace_with_usage(
        {"prompt_tokens": 1000, "completion_tokens": 500},
        {"prompt_tokens": 2000, "completion_tokens": 1000},
    )
    assert estimate_trace_cost_usd(
        trace,
        input_cost_per_million=2,
        output_cost_per_million=8,
    ) == 0.018
    assert estimate_trace_cost_usd(
        _trace_with_usage({"prompt_tokens": 1, "completion_tokens": 1}, None),
        input_cost_per_million=2,
        output_cost_per_million=8,
    ) is None


def test_trace_cost_rejects_invalid_prices():
    trace = _trace_with_usage({"prompt_tokens": 1, "completion_tokens": 1})
    for invalid_price in (-1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="finite and non-negative"):
            estimate_trace_cost_usd(
                trace,
                input_cost_per_million=invalid_price,
                output_cost_per_million=1,
            )


def test_trace_cost_treats_invalid_usage_as_unknown():
    for invalid_usage in (-1.0, float("nan"), float("inf")):
        trace = _trace_with_usage(
            {"prompt_tokens": invalid_usage, "completion_tokens": 1},
        )
        assert estimate_trace_cost_usd(
            trace,
            input_cost_per_million=1,
            output_cost_per_million=1,
        ) is None


def test_replay_observation_rejects_non_finite_metrics():
    valid = {
        "case_id": "case-finite",
        "provider": "langgraph",
        "success": True,
        "quality_score": 1.0,
        "latency_ms": 1.0,
        "cost_usd": 1.0,
    }
    for field, invalid_value in (
        ("quality_score", float("nan")),
        ("latency_ms", float("inf")),
        ("cost_usd", float("inf")),
    ):
        with pytest.raises(ValueError):
            ReplayObservation.model_validate({**valid, field: invalid_value})


def _observations(cases, provider: str, *, latency_ms: float, cost_usd: float):
    return [
        ReplayObservation(
            case_id=case.id,
            provider=provider,
            success=True,
            hard_violations=[],
            quality_score=0.95,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        )
        for case in cases
    ]


def _evaluate(cases, baseline, candidate, **kwargs):
    kwargs.setdefault("baseline_configuration_fingerprint", CONFIG_FINGERPRINT)
    kwargs.setdefault("candidate_configuration_fingerprint", CONFIG_FINGERPRINT)
    return evaluate_replay_gate(cases, baseline, candidate, **kwargs)


def test_replay_configuration_fingerprint_is_secret_safe_and_covers_every_route(tmp_path):
    default = {
        "base_url": "https://primary.example.test/v1",
        "api_key": "primary-secret",
        "model": "gpt-primary",
        "wire_api": "responses",
    }
    poi = LlmEndpointConfig(
        base_url="https://search.example.test/v1",
        api_key="search-secret",
        model="Console/grok-4.20-multi-agent-0309",
        wire_api="responses",
    )
    config = LlmConfig(**default, role_overrides={"poi_specialist": poi})
    fingerprint = replay_configuration_fingerprint(config)
    assert fingerprint == replay_configuration_fingerprint(config.model_copy(deep=True))

    for changed in (
        config.model_copy(update={"model": "gpt-other"}),
        config.model_copy(update={"api_key": "other-primary-secret"}),
        config.model_copy(update={"base_url": "https://other.example.test/v1"}),
        config.model_copy(
            update={
                "role_overrides": {
                    "poi_specialist": poi.model_copy(update={"model": "Console/grok-other"})
                }
            }
        ),
    ):
        assert replay_configuration_fingerprint(changed) != fingerprint

    artifact = build_replay_artifact("langgraph", [], config)
    path = tmp_path / "artifact.json"
    rendered = artifact.model_dump_json()
    path.write_text(rendered, encoding="utf-8")
    assert "primary-secret" not in rendered
    assert "search-secret" not in rendered
    assert "primary.example.test" not in rendered
    assert "search.example.test" not in rendered
    assert load_replay_artifact(path).configuration_fingerprint == fingerprint


def test_replay_fixture_has_thirty_controlled_cases_and_required_coverage():
    cases = load_replay_cases(FIXTURE)
    assert len(cases) == 30
    assert set().union(*(case.categories for case in cases)) >= REQUIRED_REPLAY_CATEGORIES
    assert all(case.request.planning_generated_at == case.controlled_now for case in cases)
    assert all(case.request.start_date >= case.controlled_now.date() for case in cases)
    assert sum(case.operation == "refine" for case in cases) == 2
    assert all(
        case.refinement and case.refinement["scope"] == "day_plan"
        for case in cases
        if case.operation == "refine"
    )


def test_replay_hard_gate_runs_all_cases_against_deterministic_contract():
    from travelmind_api.agents.stub import StubOrchestrator

    orchestrator = StubOrchestrator()
    for case in load_replay_cases(FIXTURE):
        original = orchestrator.plan_trip(case.request)
        if case.operation == "refine":
            refinement = case.refinement or {}
            result = orchestrator.refine_trip(
                case.request,
                original,
                instruction=str(refinement["instruction"]),
                scope=str(refinement["scope"]),
                day_index=int(refinement["day_index"]),
            )
        else:
            result = original
        assert hard_constraint_violations(case, result, original_plan=original) == [], case.id


def test_replay_definition_rejects_obsolete_refinement_scope():
    with pytest.raises(ValueError, match="Unsupported refinement scope"):
        ReplayDefinition.model_validate(
            {
                "id": "obsolete-day-scope",
                "categories": ["day_refinement"],
                "operation": "refine",
                "refinement": {"scope": "day", "day_index": 1, "instruction": "Adjust day one."},
            }
        )


def test_replay_hard_gate_detects_changes_outside_day_plan_scope():
    from travelmind_api.agents.stub import StubOrchestrator

    case = next(case for case in load_replay_cases(FIXTURE) if case.id == "refine-day-two-preserve")
    original = StubOrchestrator().plan_trip(case.request)
    candidate = original.model_copy(deep=True)
    candidate.days[0].title = "Unexpected replacement"

    violations = hard_constraint_violations(case, candidate, original_plan=original)

    assert "day 1 changed outside day-refinement scope" in violations


def test_replay_quality_gate_accepts_equal_quality_within_ten_percent_limits():
    cases = load_replay_cases(FIXTURE)
    baseline = _observations(cases, "retained-deployment", latency_ms=1000, cost_usd=0.10)
    candidate = _observations(cases, "langgraph", latency_ms=1099, cost_usd=0.109)

    report = _evaluate(cases, baseline, candidate)

    assert report.passed is True
    assert report.failures == []
    assert report.candidate.case_count == 30
    assert report.candidate.hard_violation_count == 0


def test_replay_quality_gate_rejects_hard_violation_and_missing_cost():
    cases = load_replay_cases(FIXTURE)
    baseline = _observations(cases, "retained-deployment", latency_ms=1000, cost_usd=0.10)
    candidate = _observations(cases, "langgraph", latency_ms=900, cost_usd=0.09)
    candidate[0] = candidate[0].model_copy(
        update={"hard_violations": ["closed POI scheduled"], "cost_usd": None}
    )

    report = _evaluate(cases, baseline, candidate)

    assert report.passed is False
    assert "candidate has 1 hard-constraint violation(s)" in report.failures
    assert "cost comparison is incomplete" in report.failures


def test_replay_quality_gate_accepts_explicit_isolated_billing_totals():
    cases = load_replay_cases(FIXTURE)
    baseline = _observations(cases, "helloagents", latency_ms=1000, cost_usd=0.10)
    candidate = _observations(cases, "langgraph", latency_ms=1000, cost_usd=0.10)
    baseline = [item.model_copy(update={"cost_usd": None}) for item in baseline]

    report = _evaluate(
        cases,
        baseline,
        candidate,
        expected_baseline_provider="helloagents",
        expected_candidate_provider="langgraph",
        baseline_total_cost_usd=3.0,
        candidate_total_cost_usd=3.0,
    )

    assert report.passed is True
    assert report.baseline.total_cost_usd == 3.0
    assert report.candidate.total_cost_usd == 3.0
    assert report.baseline.cost_source == "measured_total"
    assert report.candidate.cost_source == "measured_total"


@pytest.mark.parametrize("invalid_cost", [-0.01, float("nan"), float("inf")])
def test_replay_quality_gate_rejects_invalid_measured_cost(invalid_cost):
    cases = load_replay_cases(FIXTURE)
    baseline = _observations(cases, "helloagents", latency_ms=1000, cost_usd=0.10)
    candidate = _observations(cases, "langgraph", latency_ms=1000, cost_usd=0.10)

    with pytest.raises(ValueError, match="finite and non-negative"):
        _evaluate(cases, baseline, candidate, baseline_total_cost_usd=invalid_cost)


def test_replay_quality_gate_rejects_latency_and_cost_regressions():
    cases = load_replay_cases(FIXTURE)
    baseline = _observations(cases, "retained-deployment", latency_ms=1000, cost_usd=0.10)
    candidate = _observations(cases, "langgraph", latency_ms=1200, cost_usd=0.12)

    report = _evaluate(cases, baseline, candidate)

    assert report.passed is False
    assert report.baseline.cost_source == "trace_usage"
    assert report.candidate.cost_source == "trace_usage"
    assert "candidate p95 latency regressed by more than the allowed ratio" in report.failures
    assert "candidate cost regressed by more than the allowed ratio" in report.failures


def test_replay_quality_gate_rejects_provider_mismatch_and_mixed_provider_artifacts():
    cases = load_replay_cases(FIXTURE)
    baseline = _observations(cases, "standard", latency_ms=1000, cost_usd=0.10)
    candidate = _observations(cases, "langgraph", latency_ms=1000, cost_usd=0.10)
    candidate[0] = candidate[0].model_copy(update={"provider": "standard"})

    report = _evaluate(
        cases,
        baseline,
        candidate,
        expected_baseline_provider="retained-deployment",
        expected_candidate_provider="langgraph",
    )

    assert report.passed is False
    assert not any("baseline contains multiple providers" in item for item in report.failures)
    assert any("baseline provider mismatch" in item for item in report.failures)
    assert any("candidate contains multiple providers" in item for item in report.failures)
    assert any("candidate provider mismatch" in item for item in report.failures)


def test_replay_quality_gate_rejects_missing_and_mismatched_configuration_fingerprints():
    cases = load_replay_cases(FIXTURE)
    baseline = _observations(cases, "retained-deployment", latency_ms=1000, cost_usd=0.10)
    candidate = _observations(cases, "langgraph", latency_ms=1000, cost_usd=0.10)

    missing = evaluate_replay_gate(
        cases,
        baseline,
        candidate,
        baseline_configuration_fingerprint=None,
        candidate_configuration_fingerprint="b" * 64,
    )
    assert missing.passed is False
    assert "baseline configuration fingerprint is missing" in missing.failures

    mismatched = evaluate_replay_gate(
        cases,
        baseline,
        candidate,
        baseline_configuration_fingerprint="a" * 64,
        candidate_configuration_fingerprint="b" * 64,
    )
    assert mismatched.passed is False
    assert "baseline and candidate configuration fingerprints do not match" in mismatched.failures
    assert mismatched.configuration_match is False
