"""Safe schema diagnostics: field paths and validator codes, never input values."""
from __future__ import annotations

import re
from typing import Any


def schema_validation_issues(error: Any, *, limit: int = 20) -> list[dict[str, Any]]:
    # Both parser generations wrap Pydantic errors. Do not serialize str(error),
    # ctx, msg or input: validators may include user text or source credentials.
    from travelmind_api.services.llm.parser import LlmPlanningPayload

    schema = LlmPlanningPayload.model_json_schema()
    names: set[str] = set()

    def collect(node):
        if isinstance(node, dict):
            names.update(node.get("properties", {}))
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect(schema)
    seen = set()
    for _ in range(5):
        if error is None or id(error) in seen:
            break
        seen.add(id(error))
        if callable(getattr(error, "errors", None)):
            rows = error.errors(include_input=False, include_context=False, include_url=False)
            issues = []
            for row in rows[:limit]:
                path = [part if (isinstance(part, int) and not isinstance(part, bool)) or part in names else "?"
                        for part in row.get("loc", ())[:12]]
                code = str(row.get("type", "validation_error"))
                if not re.fullmatch(r"[a-z_]{1,80}", code):
                    code = "validation_error"
                issues.append({"path": path, "code": code})
            return issues
        saved = getattr(error, "issues", None)
        if isinstance(saved, list):
            return saved[:limit]
        error = error.__cause__ or error.__context__
    return []
