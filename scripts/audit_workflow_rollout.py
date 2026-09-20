"""Read-only rollout/drain audit for LangGraph migration operations."""
from __future__ import annotations

import argparse
import json

from travelmind_api.core.database import SessionLocal
from travelmind_api.services.workflow_rollout import audit_workflow_drain


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-drained",
        action="store_true",
        help="Exit with status 2 when legacy or unknown-provider work is still active.",
    )
    args = parser.parse_args()
    with SessionLocal() as session:
        audit = audit_workflow_drain(session)
    print(json.dumps(audit.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    if args.require_drained and not audit.safe_to_remove_legacy_runtime:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
