import importlib
import json

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


def test_enrich_plan_images_adds_curator_and_tavily_runs(monkeypatch):
    config = LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses")

    monkeypatch.setattr(
        "travelmind_api.services.trip_image_enrichment.OpenAICompatibleClient.create_chat_completion",
        lambda self, *, messages, temperature=0.2, max_tokens=None: (
            json.dumps(
                {
                    "items": [
                        {
                            "item_id": "item_ginkaku",
                            "priority_tier": "high",
                            "reason": "A city-defining landmark with strong visual identity.",
                            "suggested_image_count": 3,
                        }
                    ]
                }
            )
            if "Image Curator" in messages[0]["content"]
            else json.dumps(
                {
                    "selected_candidates": [
                        {"candidate_id": "c1", "reason": "Clearly shows the temple exterior.", "confidence": "high"}
                    ],
                    "rejected_candidates": [],
                    "summary": "Kept the strongest attraction image candidate.",
                }
            )
        ),
    )
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.available_tools", lambda self: {"search"})

    def fake_call_operation(self, name, arguments):
        assert self.config.provider == "tavily"
        assert name == "search"
        assert "Ginkaku-ji" in arguments["query"]
        assert "official" in arguments["query"]
        assert "photos" in arguments["query"]
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
    assert image_item.image_priority_tier == "high"
    assert image_item.image_status == "completed"
    assert image_item.image_urls
    assert image_item.image_urls[0] == "https://cdn.example.com/ginkaku-1.jpg"
    assert image_item.image_failure_reason is None
    assert meal_item.image_status == "skipped"
    assert [run.key for run in result.trace.agent_runs[-3:]] == ["image_curator", "attraction_image_specialist", "image_reviewer"]
    reviewer_run = next(run for run in result.trace.agent_runs if run.key == "image_reviewer")
    assert reviewer_run.output_summary


def test_enrich_plan_images_falls_back_when_curator_output_is_invalid(monkeypatch):
    config = LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses")
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment._resolve_tavily_image_search_config", lambda search_service: None)

    monkeypatch.setattr(
        "travelmind_api.services.trip_image_enrichment.OpenAICompatibleClient.create_chat_completion",
        lambda self, *, messages, temperature=0.2, max_tokens=None: "not-json",
    )

    result = _enrich_plan_images(
        _plan(),
        _planning_request(),
        llm_config=config,
        search_service=None,
    )

    image_item = result.days[0].items[0]
    curator_run = next(run for run in result.trace.agent_runs if run.key == "image_curator")
    specialist_run = next(run for run in result.trace.agent_runs if run.key == "attraction_image_specialist")
    assert image_item.image_priority_tier in {"high", "medium", "low"}
    assert image_item.image_failure_reason == "Tavily image search is not configured."
    assert curator_run.status == "failed"
    assert specialist_run.status == "failed"


def test_enrich_plan_images_parallelizes_high_priority_only(monkeypatch):
    config = LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses")
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
                provider="stub",
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
            id="item_river",
            type="explore",
            name="Kamo River walk",
            start_time="16:00",
            end_time="17:00",
            location="Kyoto",
            score=0.8,
            note="A lighter scenic stop.",
        )
    )

    monkeypatch.setattr(
        "travelmind_api.services.trip_image_enrichment.OpenAICompatibleClient.create_chat_completion",
        lambda self, *, messages, temperature=0.2, max_tokens=None: (
            json.dumps(
                {
                    "items": [
                        {"item_id": "item_ginkaku", "priority_tier": "high", "reason": "Hero landmark.", "suggested_image_count": 3},
                        {"item_id": "item_walk", "priority_tier": "high", "reason": "Strong scenic walk.", "suggested_image_count": 2},
                        {"item_id": "item_river", "priority_tier": "medium", "reason": "Nice supporting visual.", "suggested_image_count": 1},
                    ]
                }
            )
            if "Image Curator" in messages[0]["content"]
            else json.dumps(
                {
                    "selected_candidates": [{"candidate_id": "c1", "reason": "Good match.", "confidence": "high"}],
                    "rejected_candidates": [],
                    "summary": "Kept the best candidate.",
                }
            )
        ),
    )
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.available_tools", lambda self: {"search"})

    def fake_search_item_images(search_service, request, item, selection, llm_config):
        processed_item_ids.append(item.id)
        return _image_search_outcome(
            item_id=item.id,
            image_urls=[f"https://cdn.example.com/{item.id}.jpg"],
            source_urls=[f"https://example.com/{item.id}"],
            status="completed",
            candidate_count_raw=4,
            candidate_count_after_rules=2,
            candidate_count_after_review=1,
            review_mode="multimodal",
            review_summary="Kept the best candidate.",
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

    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment._search_item_images", fake_search_item_images)
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.ThreadPoolExecutor", FakeExecutor)

    result = _enrich_plan_images(
        plan,
        _planning_request(),
        llm_config=config,
        search_service=_tavily_search_config(),
    )

    assert set(submitted_item_ids) == {"item_ginkaku", "item_walk"}
    assert "item_river" not in submitted_item_ids
    assert set(processed_item_ids) == {"item_ginkaku", "item_walk"}
    specialist_run = next(run for run in result.trace.agent_runs if run.key == "attraction_image_specialist")
    assert any("high tier parallel" in note for note in specialist_run.notes)
    reviewer_run = next(run for run in result.trace.agent_runs if run.key == "image_reviewer")
    assert any("multimodal" in note for note in reviewer_run.notes)
    assert next(item for item in result.days[0].items if item.id == "item_river").image_status == "skipped"


def test_enrich_plan_images_skips_generic_explore_without_structured_anchor(monkeypatch):
    config = LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses")
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
        llm_config=config,
        search_service=None,
    )

    item = result.days[0].items[0]
    assert item.image_status == "skipped"
    assert item.image_priority_tier == "skipped"


def test_enrich_plan_images_filters_page_chrome_images(monkeypatch):
    config = LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses")

    monkeypatch.setattr(
        "travelmind_api.services.trip_image_enrichment.OpenAICompatibleClient.create_chat_completion",
        lambda self, *, messages, temperature=0.2, max_tokens=None: (
            json.dumps(
                {
                    "items": [
                        {
                            "item_id": "item_ginkaku",
                            "priority_tier": "high",
                            "reason": "A city-defining landmark with strong visual identity.",
                            "suggested_image_count": 2,
                        }
                    ]
                }
            )
            if "Image Curator" in messages[0]["content"]
            else json.dumps(
                {
                    "selected_candidates": [
                        {"candidate_id": "c1", "reason": "This is the actual attraction.", "confidence": "high"}
                    ],
                    "rejected_candidates": [{"candidate_id": "c2", "reason": "This is a site logo."}],
                    "summary": "Rejected page chrome and kept the attraction image.",
                }
            )
        ),
    )
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.available_tools", lambda self: {"search"})

    def fake_call_operation(self, name, arguments):
        return {
            "results": [
                {
                    "title": "Ginkaku-ji guide",
                    "url": "https://example.com/ginkaku",
                    "images": [
                        {"url": "https://example.com/assets/logo.png", "description": "Site logo"},
                        {"url": "https://cdn.example.com/ginkaku-hero.jpg", "description": "Ginkaku-ji temple exterior"},
                    ],
                }
            ]
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
    assert image_item.image_status == "completed"
    assert image_item.image_urls == ["https://cdn.example.com/ginkaku-hero.jpg"]


def test_enrich_plan_images_prefers_itinerary_name_over_stub_map_placeholder(monkeypatch):
    config = LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses")
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
                        name="The Bund 二刷或酒店周边商圈漫步",
                        start_time="18:00",
                        end_time="19:00",
                        location="外滩",
                        score=0.9,
                        note="Focus on skyline and riverfront views.",
                        location_ref=PlannedLocationReference(
                            provider="stub-maps",
                            poi_id="stub-1",
                            name="上海 Market Hall",
                            city="上海",
                            category="food",
                            summary="Stub POI for 上海 focused on food.",
                            address="上海 center zone 2",
                            coordinates=GeoPoint(lat=31.23, lng=121.47),
                        ),
                    )
                ],
            )
        ],
        trace=AgentTrace(provider="helloagents-poc", workflow_id="wf_bund", notes=[]),
    )

    monkeypatch.setattr(
        "travelmind_api.services.trip_image_enrichment.OpenAICompatibleClient.create_chat_completion",
        lambda self, *, messages, temperature=0.2, max_tokens=None: (
            json.dumps(
                {
                    "items": [
                        {
                            "item_id": "item_bund",
                            "priority_tier": "high",
                            "reason": "Skyline anchor.",
                            "suggested_image_count": 1,
                        }
                    ]
                }
            )
            if "Image Curator" in messages[0]["content"]
            else json.dumps(
                {
                    "canonical_name": "The Bund",
                    "aliases": ["外滩"],
                    "search_queries": ["\"The Bund\" Shanghai landmark official travel photos"],
                    "reason": "Use the itinerary attraction name, not the stub map placeholder.",
                }
            )
            if "Image Query Planner" in messages[0]["content"]
            else json.dumps(
                {
                    "selected_candidates": [{"candidate_id": "c1", "reason": "Correct Bund skyline image.", "confidence": "high"}],
                    "rejected_candidates": [],
                    "summary": "Selected the attraction image.",
                }
            )
        ),
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
        llm_config=config,
        search_service=_tavily_search_config(),
    )

    image_item = result.days[0].items[0]
    assert image_item.image_status == "completed"
    assert image_item.image_urls == ["https://cdn.example.com/the-bund.jpg"]


def test_enrich_plan_images_uses_multimodal_reviewer_to_reject_generic_city_visuals(monkeypatch):
    config = LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses")

    monkeypatch.setattr(
        "travelmind_api.services.trip_image_enrichment.OpenAICompatibleClient.create_chat_completion",
        lambda self, *, messages, temperature=0.2, max_tokens=None: (
            json.dumps(
                {
                    "items": [
                        {
                            "item_id": "item_ginkaku",
                            "priority_tier": "high",
                            "reason": "A city-defining landmark with strong visual identity.",
                            "suggested_image_count": 2,
                        }
                    ]
                }
            )
            if "Image Curator" in messages[0]["content"]
            else json.dumps(
                {
                    "selected_candidates": [],
                    "rejected_candidates": [
                        {"candidate_id": "c1", "reason": "Generic city skyline rather than the attraction."},
                        {"candidate_id": "c2", "reason": "Event poster, not the attraction itself."},
                    ],
                    "summary": "Rejected all low-confidence candidates.",
                }
            )
        ),
    )
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.available_tools", lambda self: {"search"})
    monkeypatch.setattr(
        "travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.call_operation",
        lambda self, name, arguments: {
            "results": [
                {
                    "title": "Kyoto skyline feature",
                    "url": "https://example.com/kyoto-skyline",
                    "images": [
                        {"url": "https://cdn.example.com/skyline.jpg", "description": "Kyoto skyline at sunset"},
                        {"url": "https://cdn.example.com/poster.jpg", "description": "Festival poster"},
                    ],
                }
            ]
        },
    )

    result = _enrich_plan_images(
        _plan(),
        _planning_request(),
        llm_config=config,
        search_service=_tavily_search_config(),
    )

    image_item = result.days[0].items[0]
    reviewer_run = next(run for run in result.trace.agent_runs if run.key == "image_reviewer")
    assert image_item.image_status == "failed"
    assert image_item.image_urls == []
    assert "multimodal review" in (image_item.image_failure_reason or "").lower()
    assert "Rejected c1" in " ".join(reviewer_run.notes)
