from __future__ import annotations

from collections.abc import Callable

from langgraph.checkpoint.base import BaseCheckpointSaver

from travelmind_api.agents.base import AgentOrchestrator
from travelmind_api.agents.langgraph_orchestrator import LangGraphOrchestrator
from travelmind_api.agents.runtime import RoleProgressCallback
from travelmind_api.agents.openai_compatible import OpenAICompatibleOrchestrator
from travelmind_api.agents.provider import (
    AGENT_PROVIDER_LANGGRAPH,
    normalize_agent_provider,
)
from travelmind_api.agents.stub import StubOrchestrator
from travelmind_api.core.config import Settings
from travelmind_api.services.llm import LlmConfig
from travelmind_api.services.maps import build_maps_provider



def build_orchestrator(
    settings: Settings,
    *,
    llm_config: LlmConfig | None = None,
    agent_provider: str | None = None,
    progress_callback: RoleProgressCallback | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> AgentOrchestrator:
    maps_provider = build_maps_provider()
    resolved_provider = normalize_agent_provider(agent_provider, default=normalize_agent_provider(settings.agent_provider))
    resolved_llm_config = llm_config or LlmConfig.from_env()

    if resolved_provider == AGENT_PROVIDER_LANGGRAPH:
        return LangGraphOrchestrator(
            resolved_llm_config,
            maps_provider=maps_provider,
            progress_callback=progress_callback,
            checkpointer=checkpointer,
        )

    if resolved_llm_config is not None:
        return OpenAICompatibleOrchestrator(resolved_llm_config, maps_provider=maps_provider)

    return StubOrchestrator(maps_provider=maps_provider)
