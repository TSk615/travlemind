"""Run a controlled replay directly against one orchestrator without saving trips."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from time import perf_counter

from travelmind_api.agents.base import RefinementContext
from travelmind_api.agents.factory import build_orchestrator
from travelmind_api.agents.stub import StubOrchestrator
from travelmind_api.core.config import Settings
from travelmind_api.services.llm import LlmConfig
from travelmind_api.services.workflow_evaluation import (
    ReplayObservation,
    estimate_trace_cost_usd,
    hard_constraint_violations,
    load_replay_cases,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("standard", "langgraph"), required=True)
    parser.add_argument("--cases", default="apps/api/tests/fixtures/langgraph-replay-cases.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument(
        "--input-cost-per-million",
        type=float,
        default=(float(os.environ["TRAVELMIND_REPLAY_INPUT_COST_PER_MILLION"]) if os.getenv("TRAVELMIND_REPLAY_INPUT_COST_PER_MILLION") else None),
    )
    parser.add_argument(
        "--output-cost-per-million",
        type=float,
        default=(float(os.environ["TRAVELMIND_REPLAY_OUTPUT_COST_PER_MILLION"]) if os.getenv("TRAVELMIND_REPLAY_OUTPUT_COST_PER_MILLION") else None),
    )
    args = parser.parse_args()
    if not args.allow_network or os.getenv("TRAVELMIND_REPLAY_ALLOW_NETWORK") != "1":
        raise SystemExit("network replay requires --allow-network and TRAVELMIND_REPLAY_ALLOW_NETWORK=1")

    llm_config = LlmConfig.from_env()
    if llm_config is None:
        raise SystemExit("no replay LLM configuration is available")
    cases = load_replay_cases(args.cases)
    if args.limit > 0:
        cases = cases[: args.limit]

    observations: list[ReplayObservation] = []
    for case in cases:
        started = perf_counter()
        original_plan = None
        try:
            orchestrator = build_orchestrator(
                Settings(agent_provider=args.provider),
                llm_config=llm_config,
                agent_provider=args.provider,
            )
            orchestrator.set_execution_context(
                job_id=f"replay-{case.id}",
                run_id=f"replay-{args.provider}-{case.id}",
            )
            if case.operation == "refine":
                original_plan = StubOrchestrator().plan_trip(case.request)
                refinement = dict(case.refinement or {})
                result = orchestrator.refine_trip(
                    case.request,
                    original_plan,
                    instruction=str(refinement.get("instruction") or "Improve this itinerary."),
                    scope=str(refinement.get("scope") or "full_trip"),
                    day_index=refinement.get("day_index"),
                    context=RefinementContext(),
                )
            else:
                result = orchestrator.plan_trip(case.request)
            violations = hard_constraint_violations(case, result, original_plan=original_plan)
            cost_usd = (
                estimate_trace_cost_usd(
                    result.trace,
                    input_cost_per_million=args.input_cost_per_million,
                    output_cost_per_million=args.output_cost_per_million,
                )
                if args.input_cost_per_million is not None and args.output_cost_per_million is not None
                else None
            )
            observations.append(
                ReplayObservation(
                    case_id=case.id,
                    provider=args.provider,
                    success=True,
                    hard_violations=violations,
                    quality_score=max(0.0, 1.0 - 0.2 * len(violations)),
                    latency_ms=(perf_counter() - started) * 1000,
                    cost_usd=cost_usd,
                )
            )
        except Exception as exc:
            observations.append(
                ReplayObservation(
                    case_id=case.id,
                    provider=args.provider,
                    success=False,
                    hard_violations=[f"execution failed: {type(exc).__name__}"],
                    quality_score=0,
                    latency_ms=(perf_counter() - started) * 1000,
                    cost_usd=None,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {"provider": args.provider, "observations": [item.model_dump(mode="json") for item in observations]},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(str(output))


if __name__ == "__main__":
    main()
