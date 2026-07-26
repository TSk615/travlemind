from datetime import date

import httpx
import pytest

from travelmind_api.agents.base import PlanningRequest
from travelmind_api.agents.stub import StubOrchestrator
from travelmind_api.services.maps import AmapMapsPoiProvider, StubMapsPoiProvider, build_maps_provider, poi_to_route_stop


def test_build_maps_provider_defaults_to_stub(monkeypatch):
    monkeypatch.delenv("TRAVELMIND_MAPS_PROVIDER", raising=False)

    provider = build_maps_provider()

    assert isinstance(provider, StubMapsPoiProvider)


def test_build_maps_provider_returns_amap_when_configured(monkeypatch):
    monkeypatch.setenv("TRAVELMIND_MAPS_PROVIDER", "amap")
    monkeypatch.setenv("TRAVELMIND_AMAP_API_KEY", "test-amap-key")
    monkeypatch.setenv("TRAVELMIND_AMAP_BASE_URL", "https://maps.example.test")
    monkeypatch.setenv("TRAVELMIND_AMAP_TIMEOUT_SECONDS", "3")

    provider = build_maps_provider()

    assert isinstance(provider, AmapMapsPoiProvider)


def test_build_maps_provider_requires_amap_key(monkeypatch):
    monkeypatch.setenv("TRAVELMIND_MAPS_PROVIDER", "amap")
    monkeypatch.delenv("TRAVELMIND_AMAP_API_KEY", raising=False)

    with pytest.raises(ValueError, match="TRAVELMIND_AMAP_API_KEY"):
        build_maps_provider()


def test_amap_maps_provider_maps_poi_search_payload():
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        assert request.url.params["key"] == "test-amap-key"
        assert request.url.params["keywords"] == "小公园历史文化街区"
        assert request.url.params["city"] == "汕头"
        return httpx.Response(
            200,
            json={
                "status": "1",
                "pois": [
                    {
                        "id": "B0TEST001",
                        "name": "小公园历史文化街区",
                        "type": "风景名胜;风景名胜相关;旅游景点",
                        "typecode": "110000",
                        "pname": "广东省",
                        "cityname": "汕头市",
                        "adname": "金平区",
                        "address": "升平路与国平路交叉口附近",
                        "location": "116.681972,23.354091",
                        "tel": "0754-12345678",
                        "website": "https://example.test/xiaogongyuan",
                        "opentime_today": "全天开放",
                    }
                ],
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = AmapMapsPoiProvider(api_key="test-amap-key", base_url="https://maps.example.test", http_client=http_client)
    try:
        results = provider.search_pois("小公园历史文化街区", "汕头", limit=3)
    finally:
        http_client.close()

    assert len(seen_requests) == 1
    assert len(results) == 1
    first = results[0]
    assert first.provider == "amap"
    assert first.name == "小公园历史文化街区"
    assert first.city == "汕头市"
    assert first.location.address.district == "金平区"
    assert first.location.coordinates.lat == 23.354091
    assert first.location.coordinates.lng == 116.681972

    detail = provider.get_poi_detail(first.id)
    assert detail is not None
    assert detail.raw_payload["source"] == "amap"
    assert detail.official_url == "https://example.test/xiaogongyuan"

    origin = poi_to_route_stop(first)
    destination = poi_to_route_stop(first.model_copy(update={"id": "B0TEST002", "name": "西堤公园"}))
    estimate = provider.estimate_route(origin, destination, "walking")
    assert estimate.provider == "amap"
    assert estimate.duration_minutes >= 3



def test_stub_maps_provider_returns_structured_poi_and_routes():
    provider = StubMapsPoiProvider()

    search_results = provider.search_pois("coffee walk", "Kyoto")
    assert search_results
    first = search_results[0]
    assert first.provider == "stub-maps"
    assert first.location.address.city == "Kyoto"
    assert first.location.coordinates.lat

    detail = provider.get_poi_detail(first.id)
    assert detail is not None
    assert detail.official_url
    assert detail.raw_payload["source"] == "stub-curated"

    generic_results = provider.search_pois("food", "Osaka")
    assert generic_results
    assert generic_results[0].provider == "stub-maps"
    assert generic_results[0].city == "Osaka"

    origin = poi_to_route_stop(search_results[0])
    destination = poi_to_route_stop(search_results[1])
    estimate = provider.estimate_route(origin, destination, "walking")
    assert estimate.distance_meters > 0
    assert estimate.duration_minutes > 0
    assert len(estimate.polyline) == 3

    matrix = provider.batch_route_matrix([origin, destination], mode="walking")
    assert matrix.provider == "stub-maps"
    assert len(matrix.cells) == 4
    assert any(cell.distance_meters == 0 for cell in matrix.cells if cell.origin_stop_id == cell.destination_stop_id)



def test_stub_orchestrator_consumes_structured_map_provider_data():
    provider = StubMapsPoiProvider()
    orchestrator = StubOrchestrator(maps_provider=provider)
    request = PlanningRequest(
        trip_id="trip_test",
        title="Kyoto calm days",
        origin="Shanghai",
        destination="Kyoto",
        start_date=date(2026, 4, 14),
        end_date=date(2026, 4, 15),
        budget=4800,
        travelers=2,
        interests=["temples", "coffee"],
        accommodation_preference="Quiet boutique hotel",
        pace="balanced",
        transport_mode="rail",
    )

    result = orchestrator.plan_trip(request)

    assert result.days
    first_day = result.days[0]
    assert len(first_day.items) == 3
    assert first_day.items[0].location_ref is not None
    assert first_day.items[0].location_ref.provider == "stub-maps"
    assert first_day.items[0].location_ref.coordinates is not None
    assert first_day.items[1].route_from_previous is not None
    assert first_day.items[1].route_from_previous.mode == "transit"
    assert first_day.items[1].route_from_previous.distance_meters > 0
    assert any("structured POI and route references" in note for note in result.trace.notes)
