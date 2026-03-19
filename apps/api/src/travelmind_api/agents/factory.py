from __future__ import annotations

from travelmind_api.agents.base import AgentOrchestrator
from travelmind_api.agents.helloagents import HelloAgentsOrchestrator
from travelmind_api.agents.stub import StubOrchestrator
from travelmind_api.core.config import Settings
from travelmind_api.services.maps import build_maps_provider


def build_orchestrator(settings: Settings) -> AgentOrchestrator:
    maps_provider = build_maps_provider()
    if settings.agent_provider == "helloagents":
        return HelloAgentsOrchestrator(maps_provider=maps_provider)
    return StubOrchestrator(maps_provider=maps_provider)