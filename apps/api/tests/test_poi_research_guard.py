from types import SimpleNamespace

import pytest

from travelmind_api.services.poi_research_guard import ensure_usable_poi_research, PoiResearchUnavailableError


@pytest.mark.parametrize("grounding", [{}, {"top_pois": [], "featured_pois": []}, {"top_pois": [{"name": " "}]}])
def test_empty_research_is_rejected_before_planning(grounding):
    with pytest.raises(PoiResearchUnavailableError, match="避免给出空白行程"):
        ensure_usable_poi_research(grounding)


def test_either_top_or_featured_real_candidates_are_accepted_without_rewriting():
    data = {"top_pois": [{"name": "小公园"}]}
    ensure_usable_poi_research(data)
    ensure_usable_poi_research(SimpleNamespace(top_pois=[], featured_pois=[SimpleNamespace(name="小公园")]))
    assert data == {"top_pois": [{"name": "小公园"}]}

def test_empty_structured_role_result_is_rejected_at_orchestrator_boundary(monkeypatch):
    from travelmind_api.agents.langgraph_orchestrator import LangGraphOrchestrator
    orchestrator = object.__new__(LangGraphOrchestrator)
    monkeypatch.setattr(orchestrator, "_request", lambda: None)
    monkeypatch.setattr(orchestrator, "_build_poi_research_payload", lambda request, brief: {})
    monkeypatch.setattr(orchestrator, "_invoke_workflow_role", lambda *args: (SimpleNamespace(content='{}'), {}))
    with pytest.raises(PoiResearchUnavailableError):
        orchestrator.research_pois({"planning_brief": {"destination": "汕头", "trip_days": 5}})
