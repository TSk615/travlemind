from __future__ import annotations

AGENT_PROVIDER_STANDARD = "standard"
AGENT_PROVIDER_HELLOAGENTS = "helloagents"
AGENT_PROVIDER_LANGGRAPH = "langgraph"

_VALID_PROVIDERS = {
    AGENT_PROVIDER_STANDARD,
    AGENT_PROVIDER_HELLOAGENTS,
    AGENT_PROVIDER_LANGGRAPH,
    "stub",
    "openai_compatible",
    "openai-compatible",
    "helloagents-poc",
    "langgraph-workflow",
}


def normalize_agent_provider(value: object | None, *, default: str = AGENT_PROVIDER_STANDARD) -> str:
    candidate = str(value or "").strip().lower()
    if candidate in {AGENT_PROVIDER_HELLOAGENTS, "helloagents-poc"}:
        return AGENT_PROVIDER_HELLOAGENTS
    if candidate in {AGENT_PROVIDER_LANGGRAPH, "langgraph-workflow"}:
        return AGENT_PROVIDER_LANGGRAPH
    if candidate in {AGENT_PROVIDER_STANDARD, "stub", "openai_compatible", "openai-compatible", ""}:
        return AGENT_PROVIDER_STANDARD
    return default



def is_supported_agent_provider(value: object | None) -> bool:
    candidate = str(value or "").strip().lower()
    return candidate in _VALID_PROVIDERS
