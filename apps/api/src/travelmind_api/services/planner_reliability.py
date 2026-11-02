"""Bounded generation recovery: formatting cannot consume content repair."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from travelmind_api.services.model_json import ModelJsonError, parse_model_json_object

MAX_FORMAT_REPAIRS = 1
MAX_SEMANTIC_REPAIRS = 1
MAX_PLANNER_REQUESTS = 3


def repair_counts(state: dict[str, Any]) -> tuple[int, int]:
    """Read new counters, conservatively recognize a saved legacy format repair."""
    if "format_repair_count" in state or "semantic_repair_count" in state:
        return int(state.get("format_repair_count", 0)), int(state.get("semantic_repair_count", 0))
    total = int(state.get("repair_count", 0))
    attempts = state.get("planner_attempts") or []
    formatted = int(total > 0 and any(a.get("parse_error") for a in attempts[:-1]))
    return formatted, max(0, total - formatted)


def can_repair(state: dict[str, Any], kind: str | None = None) -> bool:
    kind = kind or ("format" if state.get("planning_parse_error") else "semantic")
    formatted, semantic = repair_counts(state)
    if formatted + semantic >= MAX_PLANNER_REQUESTS - 1:
        return False
    if kind == "format":
        # Never regenerate the whole plan to rescue a malformed semantic patch.
        return formatted < MAX_FORMAT_REPAIRS and semantic == 0
    if kind == "semantic":
        return semantic < MAX_SEMANTIC_REPAIRS
    raise ValueError("Unknown planner repair kind")


def repair_update(state: dict[str, Any]) -> dict[str, int]:
    kind = "format" if state.get("planning_parse_error") else "semantic"
    if not can_repair(state, kind):
        raise ValueError("Planner repair budget exhausted (" + kind + ")")
    formatted, semantic = repair_counts(state)
    formatted += int(kind == "format")
    semantic += int(kind == "semantic")
    return {"format_repair_count": formatted, "semantic_repair_count": semantic,
            "repair_count": formatted + semantic}


def decode_plan(orchestrator, result, transport):
    """Strictly parse a complete object before legacy schema normalization.

    Never fix JSON interiors or silently accept duplicate keys. Checkpoints only
    carry error codes, length and hashes, not rejected raw model completions.
    """
    from travelmind_api.services.llm.parser import parse_planning_response
    try:
        raw = parse_model_json_object(result.content)
    except ModelJsonError as exc:
        return {}, {"code": exc.code, **({"offset": exc.offset} if exc.offset is not None else {})}
    try:
        plan = parse_planning_response(json.dumps(raw, ensure_ascii=False))
    except ValueError:
        return {}, {"code": "schema_validation_failed"}
    return orchestrator._normalize_draft(plan, transport).model_dump(mode="json"), None


def attempt_metadata(result, error, *, kind="draft"):
    return {**result.checkpoint_metadata(), "repair_kind": kind,
            "response_chars": len(result.content),
            "response_sha256": hashlib.sha256(result.content.encode()).hexdigest(),
            "parse_status": "rejected" if error else "accepted", "parse_error": error}


def duplicate_visit_constraints(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Identify repeated non-transport visits; the model must choose the repair.

    This does not delete, replace or retime any item. Existing full validators
    remain authoritative, including canonical POI and evidence checks.
    """
    transport = {"transport", "transit", "local_transport", "transfer", "rail", "flight", "ferry", "metro", "subway", "bus", "taxi", "walk_transfer"}
    seen = {}
    conflicts = []
    for di, day in enumerate(payload.get("days", []), 1):
        for ii, item in enumerate(day.get("items", []), 1):
            name = str(item.get("name") or "").strip()
            if not name or str(item.get("type") or "").lower() in transport:
                continue
            key = "".join(c for c in name.casefold() if c.isalnum())
            ref = item.get("item_ref") or f"d{di}i{ii}"
            if key in seen and seen[key][0] != di:
                conflicts.append({"poi_name": name, "keep_item_ref": seen[key][1], "replace_item_ref": ref,
                                  "instruction": "保留首次安排；将后续重复项替换为原候选中有来源且路线可行的不同景点，不得改名伪装、编造或删除校验。"})
            else:
                seen.setdefault(key, (di, ref))
    return conflicts
