"""Evaluate two recorded workflow replay runs against the P5 quality gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from travelmind_api.services.workflow_evaluation import (
    evaluate_replay_gate,
    load_observations,
    load_replay_cases,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="apps/api/tests/fixtures/langgraph-replay-cases.json")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--allow-missing-cost", action="store_true")
    args = parser.parse_args()
    report = evaluate_replay_gate(
        load_replay_cases(args.cases),
        load_observations(args.baseline),
        load_observations(args.candidate),
        require_cost=not args.allow_missing_cost,
    )
    rendered = json.dumps(report.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if not report.passed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
