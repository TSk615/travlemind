from __future__ import annotations

import hashlib

AGENT_PROVIDER_STANDARD = "standard"
AGENT_PROVIDER_LANGGRAPH = "langgraph"

_VALID_PROVIDERS = {
    AGENT_PROVIDER_STANDARD,
    AGENT_PROVIDER_LANGGRAPH,
    "stub",
    "openai_compatible",
    "openai-compatible",
    "helloagents-poc",
    "langgraph-workflow",
}


def normalize_agent_provider(value: object | None, *, default: str = AGENT_PROVIDER_STANDARD) -> str:
    candidate = str(value or "").strip().lower()
    if candidate in {"helloagents", "helloagents-poc", AGENT_PROVIDER_LANGGRAPH, "langgraph-workflow"}:
        return AGENT_PROVIDER_LANGGRAPH
    if candidate in {AGENT_PROVIDER_STANDARD, "stub", "openai_compatible", "openai-compatible", ""}:
        return AGENT_PROVIDER_STANDARD
    return default



def is_supported_agent_provider(value: object | None) -> bool:
    candidate = str(value or "").strip().lower()
    return candidate in _VALID_PROVIDERS


def select_agent_provider_for_new_job(
    requested_provider: object | None,
    *,
    rollout_key: str,
    langgraph_rollout_percent: int,
    fallback_provider: object | None,
) -> str:
    """Resolve the provider snapshot for a newly created job.

    The stable hash makes rollout assignment deterministic across worker
    retries without storing user identifiers in logs or metrics. Callers must
    persist the returned value on the Job before executing it; existing runs
    must never be reassigned when rollout configuration changes.
    """

    requested = normalize_agent_provider(requested_provider)
    if requested != AGENT_PROVIDER_LANGGRAPH:
        return requested

    percentage = max(0, min(100, int(langgraph_rollout_percent)))
    if percentage == 100:
        return AGENT_PROVIDER_LANGGRAPH
    fallback = normalize_agent_provider(fallback_provider)
    if fallback == AGENT_PROVIDER_LANGGRAPH:
        fallback = AGENT_PROVIDER_STANDARD
    if percentage == 0:
        return fallback

    normalized_key = str(rollout_key or "").strip()
    if not normalized_key:
        raise ValueError("rollout_key is required for partial LangGraph rollout")
    bucket = int.from_bytes(hashlib.sha256(normalized_key.encode("utf-8")).digest()[:8], "big") % 100
    return AGENT_PROVIDER_LANGGRAPH if bucket < percentage else fallback
