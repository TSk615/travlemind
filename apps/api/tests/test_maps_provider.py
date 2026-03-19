from datetime import date

from travelmind_api.agents.base import PlanningRequest
from travelmind_api.agents.stub import StubOrchestrator
from travelmind_api.services.maps import StubMapsPoiProvider, poi_to_route_stop



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