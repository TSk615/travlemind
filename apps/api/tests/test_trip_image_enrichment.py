import importlib
import pytest
from concurrent.futures import TimeoutError as FuturesTimeoutError

from travelmind_api.agents.base import (
    AgentTrace,
    PlannedDay,
    PlannedItem,
    PlannedLocationReference,
    PlanningRequest,
    PlanningResult,
)
from travelmind_api.services.maps.base import GeoPoint


@pytest.fixture(autouse=True)
def mock_image_download(monkeypatch):
    # These tests cover selection. Byte decoding/HTTP failure has separate tests.
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.validate_image_url",
                        lambda url: ({"width": 800, "height": 600, "sha256": url}, None))


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
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.available_tools", lambda self: {"search"})

    def fake_call_operation(self, name, arguments):
        assert self.config.provider == "tavily"
        assert self.config.image_include_domains == ["hk.trip.com", "pixabay.com", "pexels.com"]
        assert name == "search"
        assert arguments["include_images"] is True
        assert arguments["include_image_descriptions"] is True
        assert arguments["num_results"] == 6
        assert "Ginkaku-ji" in arguments["query"]
        assert "landmark photo" in arguments["query"]
        return {
            "images": [{"url": "https://cdn.example.com/ginkaku-top.jpg", "description": "Top image"}],
            "results": [
                {
                    "title": "Ginkaku-ji logo",
                    "url": "https://example.com/ginkaku-logo",
                    "images": [{"url": "https://cdn.example.com/logo.svg", "description": "Ginkaku-ji logo"}],
                },
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
    assert any("视觉复核未配置" in note for note in specialist_run.notes)


def test_enrich_plan_images_marks_pending_failed_when_tavily_missing(monkeypatch):
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment._resolve_tavily_image_search_config", lambda search_service: None)

    result = _enrich_plan_images(
        _plan(),
        _planning_request(),
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
            type="sight",
            name="Philosopher's Path",
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
            id="item_activity",
            type="activity",
            name="Nishiki Market",
            start_time="15:30",
            end_time="16:30",
            location="Kyoto",
            score=0.84,
            note="Named district activity, but not a sight item in the first image enrichment pass.",
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

        def result(self, timeout=None):
            return self._result

    class FakeExecutor:
        def __init__(self, max_workers, thread_name_prefix):
            self.max_workers = max_workers
            self.thread_name_prefix = thread_name_prefix

        def submit(self, fn, *args, **kwargs):
            submitted_item_ids.append(args[2].id)
            return FakeFuture(fn(*args, **kwargs))

        def shutdown(self, wait=True, cancel_futures=False):
            return None

    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment._search_item_images_direct", fake_search_item_images_direct)
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.ThreadPoolExecutor", FakeExecutor)

    result = _enrich_plan_images(
        plan,
        _planning_request(),
        search_service=_tavily_search_config(),
    )

    assert set(submitted_item_ids) == {"item_ginkaku", "item_walk"}
    assert set(processed_item_ids) == {"item_ginkaku", "item_walk"}
    assert next(item for item in result.days[0].items if item.id == "item_activity").image_status == "skipped"
    assert next(item for item in result.days[0].items if item.id == "item_generic_walk").image_status == "skipped"
    specialist_run = next(run for run in result.trace.agent_runs if run.key == "attraction_image_specialist")
    assert any("source extraction, preferred domains, then open search" in note for note in specialist_run.notes)


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
        assert "center zone" not in arguments["query"]
        assert "food" not in arguments["query"]
        assert "Stub POI" not in arguments["query"]
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
        search_service=_tavily_search_config(),
    )

    image_item = result.days[0].items[0]
    assert image_item.image_status == "completed"
    assert image_item.image_urls == ["https://cdn.example.com/the-bund.jpg"]


def test_enrich_plan_images_builds_readable_chinese_sight_query(monkeypatch):
    captured_query = ""
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
                        name="外滩",
                        start_time="18:00",
                        end_time="19:00",
                        location="黄浦区",
                        score=0.9,
                        note="Focus on skyline and riverfront views.",
                    )
                ],
            )
        ],
        trace=AgentTrace(provider="helloagents-poc", workflow_id="wf_bund_zh", notes=[]),
    )

    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.available_tools", lambda self: {"search"})

    def fake_call_operation(self, name, arguments):
        nonlocal captured_query
        captured_query = arguments["query"]
        return {
            "results": [
                {
                    "title": "外滩旅游指南",
                    "url": "https://example.com/shanghai/bund",
                    "images": [{"url": "https://cdn.example.com/bund.jpg", "description": "上海外滩实景照片"}],
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
            trip_id="trip_bund_zh",
            title="上海夜景",
            origin="杭州",
            destination="上海",
            start_date="2026-05-14",  # type: ignore[arg-type]
            end_date="2026-05-14",  # type: ignore[arg-type]
            budget=2000,
            travelers=2,
            interests=["夜景"],
            accommodation_preference="外滩酒店",
            pace="balanced",
            transport_mode="metro",
            locale="zh-CN",
        ),
        search_service=_tavily_search_config(),
    )

    assert '"外滩"' in captured_query
    assert "上海" in captured_query
    assert "实景照片" in captured_query
    assert "旅游" not in captured_query
    assert "景点" not in captured_query
    assert "����" not in captured_query
    assert result.days[0].items[0].image_status == "completed"


def test_enrich_plan_images_reuses_duplicate_sight_search(monkeypatch):
    calls: list[str] = []
    plan = _plan()
    plan.days[0].items.append(
        PlannedItem(
            id="item_ginkaku_repeat",
            type="sight",
            name="Ginkaku-ji",
            start_time="15:00",
            end_time="16:00",
            location="Kyoto",
            score=0.88,
            note="Return for late light.",
        )
    )

    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.available_tools", lambda self: {"search"})

    def fake_call_operation(self, name, arguments):
        calls.append(arguments["query"])
        return {
            "results": [
                {
                    "title": "Ginkaku-ji guide",
                    "url": "https://example.com/ginkaku",
                    "images": [{"url": "https://cdn.example.com/ginkaku-1.jpg", "description": "Ginkaku-ji temple"}],
                }
            ]
        }

    monkeypatch.setattr(
        "travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.call_operation",
        fake_call_operation,
    )

    result = _enrich_plan_images(
        plan,
        _planning_request(),
        search_service=_tavily_search_config(),
    )

    first = result.days[0].items[0]
    repeat = result.days[0].items[-1]
    assert len(calls) == 1
    assert first.image_status == "completed"
    assert repeat.image_status == "completed"
    assert repeat.image_urls == first.image_urls


def test_enrich_plan_images_fails_when_candidates_do_not_match_sight(monkeypatch):
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.available_tools", lambda self: {"search"})
    monkeypatch.setattr(
        "travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.call_operation",
        lambda self, name, arguments: {
            "results": [
                {
                    "title": "Kyoto travel overview",
                    "url": "https://example.com/kyoto",
                    "images": [{"url": "https://cdn.example.com/kyoto-generic.jpg", "description": "Generic city skyline"}],
                }
            ]
        },
    )

    result = _enrich_plan_images(
        _plan(),
        _planning_request(),
        search_service=_tavily_search_config(),
    )

    image_item = result.days[0].items[0]
    assert image_item.image_status == "failed"
    assert image_item.image_urls == []
    assert "未通过相关性、加载或视觉审核" in image_item.image_failure_reason


def test_enrich_plan_images_rejects_untraceable_top_level_candidate(monkeypatch):
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.available_tools", lambda self: {"search"})
    monkeypatch.setattr(
        "travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.call_operation",
        lambda self, name, arguments: {
            "images": [
                {
                    "url": "https://ak-d.tripcdn.com/images/zhongyang-street-good.jpg",
                    "title": "哈尔滨中央大街 | Trip.com",
                    "description": "A decorative iron archway with the words Zhongyang Street.",
                }
            ],
            "results": [
                {
                    "title": "长白瀑布赏牡丹推荐 | Trip Moments",
                    "url": "https://hk.trip.com/moments/theme/poi-changbai-waterfall",
                    "content": "中央大街附近旅行灵感集合。",
                    "images": [
                        {
                            "url": "https://dimg04.tripcdn.com/images/changbai-waterfall-wrong.png",
                            "description": "A travel page image that is not Zhongyang Street.",
                        }
                    ],
                }
            ],
        },
    )

    plan = PlanningResult(
        summary="Harbin plan",
        total_budget_estimate=2400,
        risks=[],
        days=[
            PlannedDay(
                day_index=1,
                title="Day 1",
                summary="Central street.",
                total_cost=1000,
                items=[
                    PlannedItem(
                        id="item_zhongyang",
                        type="sight",
                        name="中央大街",
                        start_time="18:00",
                        end_time="19:00",
                        location="道里区",
                        score=0.9,
                        note="Classic Harbin street.",
                    )
                ],
            )
        ],
        trace=AgentTrace(provider="helloagents-poc", workflow_id="wf_zhongyang", notes=[]),
    )

    result = _enrich_plan_images(
        plan,
        PlanningRequest(
            trip_id="trip_harbin",
            title="哈尔滨",
            origin="广州",
            destination="哈尔滨",
            start_date="2026-05-14",  # type: ignore[arg-type]
            end_date="2026-05-14",  # type: ignore[arg-type]
            budget=2000,
            travelers=2,
            interests=["街区"],
            accommodation_preference="中央大街附近",
            pace="balanced",
            transport_mode="metro",
            locale="zh-CN",
        ),
        search_service=_tavily_search_config(),
    )

    image_item = result.days[0].items[0]
    assert image_item.image_status == "failed"
    assert image_item.image_urls == []


def test_enrich_plan_images_does_not_guess_top_level_image_source(monkeypatch):
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
        search_service=_tavily_search_config(),
    )

    image_item = result.days[0].items[0]
    assert image_item.image_status == "failed"
    assert image_item.image_urls == []


def test_enrich_plan_images_ranks_candidates_by_relevance_score(monkeypatch):
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.available_tools", lambda self: {"search"})
    monkeypatch.setattr(
        "travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.call_operation",
        lambda self, name, arguments: {
            # Raw order puts the weak top-level candidate first; ranking must promote
            # the richer result candidate (destination + category + travel-domain source).
            "images": [{"url": "https://cdn.example.com/ginkaku-lowscore.jpg", "description": "Ginkaku-ji"}],
            "results": [
                {
                    "title": "Ginkaku-ji official travel guide Kyoto",
                    "url": "https://tourism.example.org/ginkaku",
                    "images": [
                        {
                            "url": "https://cdn.example.com/ginkaku-highscore.jpg",
                            "description": "Ginkaku-ji temple exterior",
                        }
                    ],
                }
            ],
        },
    )

    result = _enrich_plan_images(
        _plan(),
        _planning_request(),
        search_service=_tavily_search_config(),
    )

    image_item = result.days[0].items[0]
    assert image_item.image_status == "completed"
    assert image_item.image_urls == ["https://cdn.example.com/ginkaku-highscore.jpg"]


def test_enrich_plan_images_rerun_keeps_existing_images_without_research(monkeypatch):
    plan = _plan()
    existing_item = plan.days[0].items[0]
    existing_item.image_urls = ["https://cdn.example.com/existing-ginkaku.jpg"]
    existing_item.image_source_urls = ["https://example.com/existing-ginkaku"]
    existing_item.image_status = "completed"
    plan.days[0].items.append(
        PlannedItem(
            id="item_kiyomizu",
            type="sight",
            name="Kiyomizu-dera",
            start_time="13:00",
            end_time="15:00",
            location="Kyoto",
            score=0.9,
            note="Afternoon temple.",
        )
    )

    queries: list[str] = []
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.available_tools", lambda self: {"search"})

    def fake_call_operation(self, name, arguments):
        queries.append(arguments["query"])
        assert "Ginkaku" not in arguments["query"]
        return {
            "results": [
                {
                    "title": "Kiyomizu-dera guide",
                    "url": "https://example.com/kiyomizu",
                    "images": [{"url": "https://cdn.example.com/kiyomizu-1.jpg", "description": "Kiyomizu-dera temple"}],
                }
            ]
        }

    monkeypatch.setattr(
        "travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.call_operation",
        fake_call_operation,
    )

    result = _enrich_plan_images(
        plan,
        _planning_request(),
        search_service=_tavily_search_config(),
    )

    first = result.days[0].items[0]
    kiyomizu = next(item for item in result.days[0].items if item.id == "item_kiyomizu")
    assert len(queries) == 1
    assert first.image_status == "completed"
    assert first.image_urls == ["https://cdn.example.com/existing-ginkaku.jpg"]
    assert first.image_source_urls == ["https://example.com/existing-ginkaku"]
    assert first.image_failure_reason is None
    assert kiyomizu.image_status == "completed"
    assert kiyomizu.image_urls == ["https://cdn.example.com/kiyomizu-1.jpg"]


def test_enrich_plan_images_rerun_keeps_existing_images_when_search_unavailable(monkeypatch):
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment._resolve_tavily_image_search_config", lambda search_service: None)
    plan = _plan()
    existing_item = plan.days[0].items[0]
    existing_item.image_urls = ["https://cdn.example.com/existing-ginkaku.jpg"]
    existing_item.image_source_urls = ["https://example.com/existing-ginkaku"]
    existing_item.image_status = "completed"

    result = _enrich_plan_images(
        plan,
        _planning_request(),
        search_service=None,
    )

    first = result.days[0].items[0]
    assert first.image_status == "completed"
    assert first.image_urls == ["https://cdn.example.com/existing-ginkaku.jpg"]
    assert first.image_failure_reason is None


def test_enrich_plan_images_skips_items_whose_search_times_out(monkeypatch):
    plan = _plan()
    plan.days[0].items.append(
        PlannedItem(
            id="item_kiyomizu",
            type="sight",
            name="Kiyomizu-dera",
            start_time="13:00",
            end_time="15:00",
            location="Kyoto",
            score=0.9,
            note="Afternoon temple.",
        )
    )

    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.ConfiguredSearchGateway.available_tools", lambda self: {"search"})

    def fake_search_item_images_direct(search_service, request, item):
        return _image_search_outcome(
            item_id=item.id,
            image_urls=[f"https://cdn.example.com/{item.id}.jpg"],
            source_urls=[f"https://example.com/{item.id}"],
            status="completed",
        )

    class TimeoutFakeFuture:
        def result(self, timeout=None):
            raise FuturesTimeoutError()

    class FakeFuture:
        def __init__(self, value):
            self._value = value

        def result(self, timeout=None):
            return self._value

    class FakeExecutor:
        def __init__(self, max_workers, thread_name_prefix):
            self.max_workers = max_workers
            self.thread_name_prefix = thread_name_prefix

        def submit(self, fn, *args, **kwargs):
            item = args[2]
            if item.id == "item_ginkaku":
                return TimeoutFakeFuture()
            return FakeFuture(fn(*args, **kwargs))

        def shutdown(self, wait=True, cancel_futures=False):
            return None

    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment._search_item_images_direct", fake_search_item_images_direct)
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.ThreadPoolExecutor", FakeExecutor)

    result = _enrich_plan_images(
        plan,
        _planning_request(),
        search_service=_tavily_search_config(),
    )

    ginkaku = result.days[0].items[0]
    kiyomizu = next(item for item in result.days[0].items if item.id == "item_kiyomizu")
    specialist_run = next(run for run in result.trace.agent_runs if run.key == "attraction_image_specialist")
    assert ginkaku.image_status == "failed"
    assert ginkaku.image_urls == []
    assert "timed out" in ginkaku.image_failure_reason
    assert kiyomizu.image_status == "completed"
    assert kiyomizu.image_urls == ["https://cdn.example.com/item_kiyomizu.jpg"]
    assert specialist_run.status == "partial"
