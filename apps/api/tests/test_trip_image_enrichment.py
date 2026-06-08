import importlib

from travelmind_api.agents.base import (
    AgentTrace,
    PlannedDay,
    PlannedItem,
    PlannedLocationReference,
    PlanningRequest,
    PlanningResult,
)
from travelmind_api.services.llm import LlmConfig
from travelmind_api.services.maps.base import GeoPoint


def _search_connector_module():
    return importlib.import_module("travelmind_api.services.search_connector")


def _trip_image_enrichment_module():
    return importlib.import_module("travelmind_api.services.trip_image_enrichment")


def _tavily_search_config(**overrides):
    search_connector = _search_connector_module()
    payload = {
        "provider": "tavily",
        "transport": "api",
        "base_url": "https://api.tavily.com/search",
        "api_key": "test-key",
    }
    payload.update(overrides)
    return search_connector.SearchServiceConfig(**payload)


def _enrich_plan_images(*args, **kwargs):
    return _trip_image_enrichment_module().enrich_plan_images(*args, **kwargs)


def _image_search_outcome(**kwargs):
    return _trip_image_enrichment_module().ImageSearchOutcome(**kwargs)


def _planning_request() -> PlanningRequest:
    return PlanningRequest(
        trip_id="trip_123",
        title="Kyoto calm days",
        origin="Shanghai",
        destination="Kyoto",
        start_date="2026-05-14",  # type: ignore[arg-type]
        end_date="2026-05-16",  # type: ignore[arg-type]
        budget=4800,
        travelers=2,
        interests=["temples", "coffee"],
        accommodation_preference="Quiet boutique hotel",
        pace="balanced",
        transport_mode="rail",
    )


def _plan() -> PlanningResult:
    return PlanningResult(
        summary="Kyoto plan",
        total_budget_estimate=4700,
        risks=[],
        days=[
            PlannedDay(
                day_index=1,
                title="Day 1",
                summary="Temple day",
                total_cost=1200,
                items=[
                    PlannedItem(
                        id="item_ginkaku",
                        type="sight",
                        name="Ginkaku-ji",
                        start_time="09:00",
                        end_time="11:00",
                        location="Kyoto",
                        score=0.92,
                        note="Start with a calm landmark.",
                        location_ref=PlannedLocationReference(
                            provider="stub",
                            poi_id="poi_1",
                            name="Ginkaku-ji",
                            city="Kyoto",
                            category="temple",
                            summary="A scenic eastern Kyoto landmark.",
                            address="Kyoto",
                            coordinates=GeoPoint(lat=35.0272, lng=135.7982),
                        ),
                    ),
                    PlannedItem(
                        id="item_lunch",
                        type="meal",
                        name="Coffee stop",
                        start_time="12:00",
                        end_time="13:00",
                        location="Kyoto",
                        score=0.8,
                        note="Coffee break.",
                    ),
                ],
            )
        ],
        trace=AgentTrace(provider="helloagents-poc", workflow_id="wf_123", notes=[]),
    )


def test_enrich_plan_images_directly_uses_tavily_without_image_llm(monkeypatch):
    config = LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses")

    def fail_llm(*args, **kwargs):
        raise AssertionError("direct Tavily image enrichment must not call image LLM roles")

    monkeypatch.setattr(
        "travelmind_api.services.trip_image_enrichment.OpenAICompatibleClient.create_chat_completion",
        fail_llm,
    )
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.available_tools", lambda self: {"search"})

    def fake_call_operation(self, name, arguments):
        assert self.config.provider == "tavily"
        assert self.config.image_include_domains == ["hk.trip.com", "pixabay.com", "pexels.com"]
        assert name == "search"
        assert arguments["include_images"] is True
        assert arguments["include_image_descriptions"] is True
        assert arguments["num_results"] == 6
        assert "Ginkaku-ji" in arguments["query"]
        return {
            "images": [{"url": "https://cdn.example.com/ginkaku-top.jpg", "description": "Top image"}],
            "results": [
                {
                    "title": "Ginkaku-ji guide",
                    "url": "https://example.com/ginkaku",
                    "images": [{"url": "https://cdn.example.com/ginkaku-1.jpg", "description": "Temple exterior"}],
                }
            ],
        }

    monkeypatch.setattr(
        "travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.call_operation",
        fake_call_operation,
    )

    result = _enrich_plan_images(
        _plan(),
        _planning_request(),
        llm_config=config,
        search_service=_tavily_search_config(),
    )

    image_item = result.days[0].items[0]
    meal_item = result.days[0].items[1]
    run_keys = [run.key for run in result.trace.agent_runs]
    specialist_run = next(run for run in result.trace.agent_runs if run.key == "attraction_image_specialist")
    assert image_item.image_priority_tier is None
    assert image_item.image_status == "completed"
    assert image_item.image_urls == ["https://cdn.example.com/ginkaku-1.jpg"]
    assert image_item.image_failure_reason is None
    assert meal_item.image_status == "skipped"
    assert "image_curator" not in run_keys
    assert "image_reviewer" not in run_keys
    assert any("curator and reviewer skipped" in note for note in specialist_run.notes)


def test_enrich_plan_images_marks_pending_failed_when_tavily_missing(monkeypatch):
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment._resolve_tavily_image_search_config", lambda search_service: None)

    result = _enrich_plan_images(
        _plan(),
        _planning_request(),
        llm_config=None,
        search_service=None,
    )

    image_item = result.days[0].items[0]
    specialist_run = next(run for run in result.trace.agent_runs if run.key == "attraction_image_specialist")
    assert image_item.image_status == "failed"
    assert image_item.image_failure_reason == "Tavily image search is not configured."
    assert specialist_run.status == "failed"


def test_enrich_plan_images_processes_all_pending_visual_items_in_parallel(monkeypatch):
    submitted_item_ids: list[str] = []
    processed_item_ids: list[str] = []

    plan = _plan()
    plan.days[0].items.append(
        PlannedItem(
            id="item_walk",
            type="explore",
            name="Philosopher's Path walk",
            start_time="14:00",
            end_time="15:30",
            location="Kyoto",
            score=0.86,
            note="Scenic slow walk.",
            location_ref=PlannedLocationReference(
                provider="maps",
                poi_id="poi_2",
                name="Philosopher's Path",
                city="Kyoto",
                category="walk",
                summary="A scenic canal-side walking route.",
                address="Kyoto",
                coordinates=GeoPoint(lat=35.02, lng=135.79),
            ),
        )
    )
    plan.days[0].items.append(
        PlannedItem(
            id="item_generic_walk",
            type="explore",
            name="Slow evening walk",
            start_time="16:00",
            end_time="17:00",
            location="Kyoto",
            score=0.8,
            note="Free time without a structured scenic anchor.",
        )
    )

    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.available_tools", lambda self: {"search"})

    def fake_search_item_images_direct(search_service, request, item):
        processed_item_ids.append(item.id)
        return _image_search_outcome(
            item_id=item.id,
            image_urls=[f"https://cdn.example.com/{item.id}.jpg"],
            source_urls=[f"https://example.com/{item.id}"],
            status="completed",
            candidate_count_raw=4,
            candidate_count_after_rules=4,
            candidate_count_after_review=1,
            review_mode="direct_tavily",
            review_summary="Direct Tavily candidate selection.",
        )

    class FakeFuture:
        def __init__(self, result):
            self._result = result

        def result(self):
            return self._result

    class FakeExecutor:
        def __init__(self, max_workers, thread_name_prefix):
            self.max_workers = max_workers
            self.thread_name_prefix = thread_name_prefix

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, *args, **kwargs):
            submitted_item_ids.append(args[2].id)
            return FakeFuture(fn(*args, **kwargs))

    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment._search_item_images_direct", fake_search_item_images_direct)
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.ThreadPoolExecutor", FakeExecutor)

    result = _enrich_plan_images(
        plan,
        _planning_request(),
        llm_config=None,
        search_service=_tavily_search_config(),
    )

    assert set(submitted_item_ids) == {"item_ginkaku", "item_walk"}
    assert set(processed_item_ids) == {"item_ginkaku", "item_walk"}
    assert next(item for item in result.days[0].items if item.id == "item_generic_walk").image_status == "skipped"
    specialist_run = next(run for run in result.trace.agent_runs if run.key == "attraction_image_specialist")
    assert any("direct pending items parallel" in note for note in specialist_run.notes)


def test_enrich_plan_images_skips_generic_explore_without_structured_anchor():
    plan = PlanningResult(
        summary="Shanghai plan",
        total_budget_estimate=2400,
        risks=[],
        days=[
            PlannedDay(
                day_index=1,
                title="Day 1",
                summary="Easy evening.",
                total_cost=1000,
                items=[
                    PlannedItem(
                        id="item_generic_walk",
                        type="explore",
                        name="Slow evening walk",
                        start_time="18:00",
                        end_time="19:00",
                        location="The Bund",
                        score=0.75,
                        note="Free time near the river.",
                    )
                ],
            )
        ],
        trace=AgentTrace(provider="helloagents-poc", workflow_id="wf_generic", notes=[]),
    )

    result = _enrich_plan_images(
        plan,
        PlanningRequest(
            trip_id="trip_generic",
            title="Shanghai night",
            origin="Hangzhou",
            destination="Shanghai",
            start_date="2026-05-14",  # type: ignore[arg-type]
            end_date="2026-05-14",  # type: ignore[arg-type]
            budget=2000,
            travelers=2,
            interests=["night views"],
            accommodation_preference="Bund hotel",
            pace="balanced",
            transport_mode="metro",
        ),
        llm_config=None,
        search_service=None,
    )

    item = result.days[0].items[0]
    specialist_run = next(run for run in result.trace.agent_runs if run.key == "attraction_image_specialist")
    assert item.image_status == "skipped"
    assert item.image_priority_tier == "skipped"
    assert specialist_run.status == "completed"


def test_enrich_plan_images_prefers_itinerary_name_over_stub_map_placeholder(monkeypatch):
    plan = PlanningResult(
        summary="Shanghai plan",
        total_budget_estimate=2400,
        risks=[],
        days=[
            PlannedDay(
                day_index=1,
                title="Day 1",
                summary="Bund evening.",
                total_cost=1000,
                items=[
                    PlannedItem(
                        id="item_bund",
                        type="sight",
                        name="The Bund hotel area walk",
                        start_time="18:00",
                        end_time="19:00",
                        location="The Bund",
                        score=0.9,
                        note="Focus on skyline and riverfront views.",
                        location_ref=PlannedLocationReference(
                            provider="stub-maps",
                            poi_id="stub-1",
                            name="Shanghai Market Hall",
                            city="Shanghai",
                            category="food",
                            summary="Stub POI for Shanghai focused on food.",
                            address="Shanghai center zone 2",
                            coordinates=GeoPoint(lat=31.23, lng=121.47),
                        ),
                    )
                ],
            )
        ],
        trace=AgentTrace(provider="helloagents-poc", workflow_id="wf_bund", notes=[]),
    )

    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.available_tools", lambda self: {"search"})

    def fake_call_operation(self, name, arguments):
        assert "The Bund" in arguments["query"]
        assert "Market Hall" not in arguments["query"]
        return {
            "results": [
                {
                    "title": "The Bund guide",
                    "url": "https://example.com/the-bund",
                    "images": [{"url": "https://cdn.example.com/the-bund.jpg", "description": "The Bund skyline"}],
                }
            ]
        }

    monkeypatch.setattr(
        "travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.call_operation",
        fake_call_operation,
    )

    result = _enrich_plan_images(
        plan,
        PlanningRequest(
            trip_id="trip_bund",
            title="Shanghai night",
            origin="Hangzhou",
            destination="Shanghai",
            start_date="2026-05-14",  # type: ignore[arg-type]
            end_date="2026-05-14",  # type: ignore[arg-type]
            budget=2000,
            travelers=2,
            interests=["night views"],
            accommodation_preference="Bund hotel",
            pace="balanced",
            transport_mode="metro",
        ),
        llm_config=None,
        search_service=_tavily_search_config(),
    )

    image_item = result.days[0].items[0]
    assert image_item.image_status == "completed"
    assert image_item.image_urls == ["https://cdn.example.com/the-bund.jpg"]


def test_enrich_plan_images_uses_top_level_images_when_result_images_are_empty(monkeypatch):
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.available_tools", lambda self: {"search"})
    monkeypatch.setattr(
        "travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.call_operation",
        lambda self, name, arguments: {
            "images": [{"url": "https://cdn.example.com/ginkaku-top.jpg", "description": "Ginkaku-ji"}],
            "results": [{"title": "Ginkaku-ji guide", "url": "https://example.com/ginkaku"}],
        },
    )

    result = _enrich_plan_images(
        _plan(),
        _planning_request(),
        llm_config=None,
        search_service=_tavily_search_config(),
    )

    image_item = result.days[0].items[0]
    assert image_item.image_status == "completed"
    assert image_item.image_urls == ["https://cdn.example.com/ginkaku-top.jpg"]
