from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import fmean
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from travelmind_api.agents.base import AgentTrace, PlanningRequest, PlanningResult
from travelmind_api.agents.workflows.trip_refinement import validate_refinement_target
from travelmind_api.services.execution_validation import validate_timeline
from travelmind_api.services.llm.parser import LlmPlanningPayload


REQUIRED_REPLAY_CATEGORIES = frozenset(
    {
        "single_city",
        "multi_city",
        "overnight_transport",
        "low_budget",
        "hotel_preference",
        "poi_closure",
        "future_weather",
        "insufficient_evidence",
        "day_refinement",
        "no_upstream",
    }
)


def estimate_trace_cost_usd(
    trace: AgentTrace,
    *,
    input_cost_per_million: float,
    output_cost_per_million: float,
) -> float | None:
    """Estimate known model cost; return unknown if any recorded role lacks usage."""

    prices = (input_cost_per_million, output_cost_per_million)
    if any(not math.isfinite(price) or price < 0 for price in prices):
        raise ValueError("model token prices must be finite and non-negative")
    if not trace.agent_runs:
        return None

    prompt_tokens = 0.0
    completion_tokens = 0.0
    for run in trace.agent_runs:
        usage = run.usage
        if not isinstance(usage, dict):
            return None
        raw_prompt = usage.get("prompt_tokens", usage.get("input_tokens", usage.get("promptTokenCount")))
        raw_completion = usage.get(
            "completion_tokens",
            usage.get("output_tokens", usage.get("candidatesTokenCount")),
        )
        try:
            parsed_prompt = float(raw_prompt)
            parsed_completion = float(raw_completion)
        except (TypeError, ValueError):
            return None
        if any(
            not math.isfinite(value) or value < 0
            for value in (parsed_prompt, parsed_completion)
        ):
            return None
        prompt_tokens += parsed_prompt
        completion_tokens += parsed_completion

    estimated_cost = (
        prompt_tokens * input_cost_per_million / 1_000_000
        + completion_tokens * output_cost_per_million / 1_000_000
    )
    return round(estimated_cost, 8) if math.isfinite(estimated_cost) else None


class ReplayDefinition(BaseModel):
    id: str = Field(min_length=1)
    categories: set[str] = Field(min_length=1)
    request_overrides: dict[str, Any] = Field(default_factory=dict)
    operation: Literal["generate", "refine"] = "generate"
    refinement: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_refinement(self) -> "ReplayDefinition":
        if self.operation == "refine" and not isinstance(self.refinement, dict):
            raise ValueError("refine replay cases require refinement settings")
        if self.operation == "refine":
            refinement = dict(self.refinement or {})
            scope, day_index = validate_refinement_target(
                str(refinement.get("scope") or ""),
                refinement.get("day_index"),
            )
            refinement["scope"] = scope
            refinement["day_index"] = day_index
            self.refinement = refinement
        return self


class ReplayCase(BaseModel):
    id: str
    categories: set[str]
    request: PlanningRequest
    operation: Literal["generate", "refine"] = "generate"
    refinement: dict[str, Any] | None = None
    controlled_now: datetime


class ReplayObservation(BaseModel):
    case_id: str
    provider: str
    success: bool
    hard_violations: list[str] = Field(default_factory=list)
    quality_score: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    latency_ms: float = Field(ge=0.0, allow_inf_nan=False)
    cost_usd: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    error: str | None = None


@dataclass(frozen=True)
class ReplayMetrics:
    case_count: int
    success_rate: float
    mean_quality_score: float
    hard_violation_count: int
    p95_latency_ms: float
    total_cost_usd: float | None
    cost_source: Literal["trace_usage", "measured_total", "unknown"]


@dataclass(frozen=True)
class ReplayGateReport:
    passed: bool
    failures: list[str]
    baseline: ReplayMetrics
    candidate: ReplayMetrics

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "failures": list(self.failures),
            "baseline": asdict(self.baseline),
            "candidate": asdict(self.candidate),
        }


def load_replay_cases(path: str | Path) -> list[ReplayCase]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    controlled_now = datetime.fromisoformat(str(payload["controlled_now"]))
    defaults = dict(payload.get("request_defaults") or {})
    cases: list[ReplayCase] = []
    for raw in payload.get("cases") or []:
        definition = ReplayDefinition.model_validate(raw)
        request_payload = {**defaults, **definition.request_overrides}
        request_payload.setdefault("trip_id", definition.id)
        request_payload.setdefault("title", str(request_payload.get("destination") or definition.id))
        request_payload["planning_generated_at"] = controlled_now
        cases.append(
            ReplayCase(
                id=definition.id,
                categories=definition.categories,
                request=PlanningRequest.model_validate(request_payload),
                operation=definition.operation,
                refinement=definition.refinement,
                controlled_now=controlled_now,
            )
        )
    validate_replay_case_set(cases)
    return cases


def validate_replay_case_set(cases: list[ReplayCase]) -> None:
    if len(cases) < 30:
        raise ValueError(f"replay suite requires at least 30 cases; received {len(cases)}")
    identifiers = [case.id for case in cases]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("replay case IDs must be unique")
    covered = set().union(*(case.categories for case in cases)) if cases else set()
    missing = sorted(REQUIRED_REPLAY_CATEGORIES - covered)
    if missing:
        raise ValueError(f"replay suite is missing required categories: {', '.join(missing)}")
    for case in cases:
        if case.request.start_date < case.controlled_now.date():
            raise ValueError(f"replay case {case.id} starts before its controlled clock")


def hard_constraint_violations(
    case: ReplayCase,
    result: PlanningResult,
    *,
    original_plan: PlanningResult | None = None,
) -> list[str]:
    request = case.request
    violations: list[str] = []
    expected_days = (request.end_date - request.start_date).days + 1
    if len(result.days) != expected_days:
        violations.append(f"expected {expected_days} days, received {len(result.days)}")
    day_indexes = [day.day_index for day in result.days]
    if day_indexes != list(range(1, len(result.days) + 1)):
        violations.append("day indexes are not contiguous and one-based")
    if result.total_budget_estimate > request.budget + 0.01:
        violations.append(
            f"budget exceeded: estimate={result.total_budget_estimate:.2f}, limit={request.budget:.2f}"
        )
    if result.budget_summary is not None:
        line_total = round(sum(item.amount for item in result.budget_summary.line_items), 2)
        estimate = round(result.budget_summary.estimated_total, 2)
        if line_total != estimate:
            violations.append(f"budget ledger mismatch: lines={line_total:.2f}, estimate={estimate:.2f}")
        if round(result.total_budget_estimate, 2) != estimate:
            violations.append("top-level and budget-summary totals differ")

    try:
        payload = LlmPlanningPayload.model_validate(
            {
                "summary": result.summary,
                "total_budget_estimate": result.total_budget_estimate,
                "days": [day.model_dump(mode="json") for day in result.days],
                "risks": result.risks,
                "transport_booking_summary": (
                    result.transport_booking_summary.model_dump(mode="json")
                    if result.transport_booking_summary is not None
                    else None
                ),
            }
        )
        transport = result.transport_booking_summary or SimpleNamespace(
            legs=[], station_buffer_minutes=45, departure_transfer_minutes=60
        )
        if not hasattr(transport, "station_buffer_minutes"):
            transport = SimpleNamespace(
                legs=transport.legs,
                station_buffer_minutes=45,
                departure_transfer_minutes=60,
            )
        violations.extend(validate_timeline(payload, request, transport))
    except Exception as exc:
        violations.append(f"result contract validation failed: {type(exc).__name__}: {exc}")

    if case.operation == "refine" and original_plan is not None:
        refinement = case.refinement or {}
        if refinement.get("scope") == "day_plan":
            target = int(refinement.get("day_index") or 0)
            original_by_day = {day.day_index: day.model_dump(mode="json") for day in original_plan.days}
            result_by_day = {day.day_index: day.model_dump(mode="json") for day in result.days}
            for day_index, original_day in original_by_day.items():
                if day_index != target and result_by_day.get(day_index) != original_day:
                    violations.append(f"day {day_index} changed outside day-refinement scope")
    return list(dict.fromkeys(violations))


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def summarize_observations(
    observations: list[ReplayObservation],
    *,
    total_cost_usd: float | None = None,
) -> ReplayMetrics:
    if total_cost_usd is not None and (not math.isfinite(total_cost_usd) or total_cost_usd < 0):
        raise ValueError("measured replay cost must be finite and non-negative")
    costs = [item.cost_usd for item in observations]
    trace_cost_is_complete = bool(observations) and all(value is not None for value in costs)
    if total_cost_usd is not None:
        resolved_cost = round(total_cost_usd, 6)
        cost_source: Literal["trace_usage", "measured_total", "unknown"] = "measured_total"
    elif trace_cost_is_complete:
        resolved_cost = round(sum(float(value) for value in costs if value is not None), 6)
        cost_source = "trace_usage"
    else:
        resolved_cost = None
        cost_source = "unknown"
    return ReplayMetrics(
        case_count=len(observations),
        success_rate=fmean(1.0 if item.success else 0.0 for item in observations) if observations else 0.0,
        mean_quality_score=fmean(item.quality_score for item in observations) if observations else 0.0,
        hard_violation_count=sum(len(item.hard_violations) for item in observations),
        p95_latency_ms=_p95([item.latency_ms for item in observations]),
        total_cost_usd=resolved_cost,
        cost_source=cost_source,
    )


def evaluate_replay_gate(
    cases: list[ReplayCase],
    baseline: list[ReplayObservation],
    candidate: list[ReplayObservation],
    *,
    max_regression_ratio: float = 0.10,
    require_cost: bool = True,
    expected_baseline_provider: str | None = None,
    expected_candidate_provider: str | None = None,
    baseline_total_cost_usd: float | None = None,
    candidate_total_cost_usd: float | None = None,
) -> ReplayGateReport:
    validate_replay_case_set(cases)
    expected_ids = {case.id for case in cases}
    failures: list[str] = []

    for label, observations in (("baseline", baseline), ("candidate", candidate)):
        observed_ids = [item.case_id for item in observations]
        providers = {str(item.provider).strip() for item in observations if str(item.provider).strip()}
        duplicates = sorted({case_id for case_id in observed_ids if observed_ids.count(case_id) > 1})
        if duplicates:
            failures.append(f"{label} contains duplicate cases: {', '.join(duplicates)}")
        missing = sorted(expected_ids - set(observed_ids))
        unexpected = sorted(set(observed_ids) - expected_ids)
        if missing:
            failures.append(f"{label} is missing cases: {', '.join(missing)}")
        if unexpected:
            failures.append(f"{label} contains unexpected cases: {', '.join(unexpected)}")
        if len(providers) > 1:
            failures.append(f"{label} contains multiple providers: {', '.join(sorted(providers))}")

    if expected_baseline_provider:
        baseline_providers = {str(item.provider).strip() for item in baseline}
        if baseline_providers != {expected_baseline_provider}:
            failures.append(
                "baseline provider mismatch: "
                f"expected {expected_baseline_provider}, received {', '.join(sorted(baseline_providers)) or '<none>'}"
            )
    if expected_candidate_provider:
        candidate_providers = {str(item.provider).strip() for item in candidate}
        if candidate_providers != {expected_candidate_provider}:
            failures.append(
                "candidate provider mismatch: "
                f"expected {expected_candidate_provider}, received {', '.join(sorted(candidate_providers)) or '<none>'}"
            )

    baseline_metrics = summarize_observations(baseline, total_cost_usd=baseline_total_cost_usd)
    candidate_metrics = summarize_observations(candidate, total_cost_usd=candidate_total_cost_usd)
    if candidate_metrics.hard_violation_count:
        failures.append(f"candidate has {candidate_metrics.hard_violation_count} hard-constraint violation(s)")
    if candidate_metrics.success_rate < baseline_metrics.success_rate:
        failures.append("candidate success rate is below baseline")
    if candidate_metrics.mean_quality_score < baseline_metrics.mean_quality_score:
        failures.append("candidate quality score is below baseline")
    performance_limit = baseline_metrics.p95_latency_ms * (1.0 + max_regression_ratio)
    if candidate_metrics.p95_latency_ms > performance_limit:
        failures.append("candidate p95 latency regressed by more than the allowed ratio")

    if baseline_metrics.total_cost_usd is None or candidate_metrics.total_cost_usd is None:
        if require_cost:
            failures.append("cost comparison is incomplete")
    else:
        cost_limit = baseline_metrics.total_cost_usd * (1.0 + max_regression_ratio)
        if candidate_metrics.total_cost_usd > cost_limit:
            failures.append("candidate cost regressed by more than the allowed ratio")

    return ReplayGateReport(
        passed=not failures,
        failures=failures,
        baseline=baseline_metrics,
        candidate=candidate_metrics,
    )


def load_observations(path: str | Path) -> list[ReplayObservation]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("observations") if isinstance(payload, dict) else payload
    return [ReplayObservation.model_validate(item) for item in rows or []]
