from __future__ import annotations

from travelmind_api.agents.base import AgentOrchestrator
from travelmind_api.agents.helloagents import HelloAgentsOrchestrator
from travelmind_api.agents.openai_compatible import OpenAICompatibleOrchestrator
from travelmind_api.agents.stub import StubOrchestrator
from travelmind_api.core.config import Settings
from travelmind_api.services.llm import LlmConfig
from travelmind_api.services.maps import build_maps_provider


LEGACY_HELLOAGENTS_PROVIDERS = {"helloagents-poc"}



def build_orchestrator(settings: Settings, *, llm_config: LlmConfig | None = None) -> AgentOrchestrator:
    maps_provider = build_maps_provider()
    resolved_llm_config = llm_config or LlmConfig.from_env()
    if resolved_llm_config is not None:
        return OpenAICompatibleOrchestrator(resolved_llm_config, maps_provider=maps_provider)

    if settings.agent_provider.strip().lower() in LEGACY_HELLOAGENTS_PROVIDERS:
        return HelloAgentsOrchestrator(maps_provider=maps_provider)

    return StubOrchestrator(maps_provider=maps_provider)