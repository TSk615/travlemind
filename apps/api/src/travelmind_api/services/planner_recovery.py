"""Audit metadata for the bounded planner repair; never persist raw completions."""
from __future__ import annotations
import hashlib
from typing import Any


def planner_attempt_metadata(result, error: dict[str, Any] | None) -> dict[str, Any]:
    return {**result.checkpoint_metadata(), "response_chars": len(result.content),
            "response_sha256": hashlib.sha256(result.content.encode()).hexdigest(),
            "parse_status": "rejected" if error else "accepted", "parse_error": error}


def combined_planner_metadata(attempts: list[dict[str, Any]], fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    if not attempts:
        return dict(fallback or {})
    result = dict(attempts[-1])
    result["request_count"] = sum(int(a.get("request_count") or 0) for a in attempts)
    result["retry_count"] = sum(int(a.get("retry_count") or 0) for a in attempts)
    latencies = [a.get("latency_ms") for a in attempts]
    result["latency_ms"] = sum(latencies) if all(isinstance(v, (int, float)) for v in latencies) else None
    usages = [a.get("usage") for a in attempts]
    result["usage"] = None
    if all(isinstance(u, dict) for u in usages):
        totals = {}
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            values = [u.get(field) for u in usages]
            if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
                totals[field] = sum(values)
        result["usage"] = totals or None
    result["citations"] = list(dict.fromkeys(c for a in attempts for c in a.get("citations", [])))
    return result
