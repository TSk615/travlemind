from __future__ import annotations

from importlib.util import find_spec

from travelmind_api.agents.base import ExportDraft, PlanningRequest, PlanningResult, SourceSummary
from travelmind_api.agents.stub import StubOrchestrator
from travelmind_api.services.maps.base import MapsPoiProvider


class HelloAgentsOrchestrator:
    def __init__(self, maps_provider: MapsPoiProvider | None = None) -> None:
        self._fallback = StubOrchestrator(maps_provider=maps_provider)
        self._helloagents_available = find_spec("helloagents") is not None

    def plan_trip(self, request: PlanningRequest) -> PlanningResult:
        result = self._fallback.plan_trip(request)
        result.trace.provider = "helloagents-poc"
        result.trace.notes.append("Executed through the HelloAgents PoC adapter boundary.")
        if self._helloagents_available:
            result.trace.notes.append("The helloagents package is installed, but the MVP keeps deterministic fallback behavior.")
        result.trace.license_notice = "PoC adapter only. Do not ship a commercial release while this adapter remains in production."
        return result

    def summarize_sources(self, destination: str, findings: list[str]) -> SourceSummary:
        return self._fallback.summarize_sources(destination, findings)

    def draft_export_payload(self, request: PlanningRequest, plan: PlanningResult) -> ExportDraft:
        draft = self._fallback.draft_export_payload(request, plan)
        draft.sections.append("Agent provider: helloagents-poc")
        return draft