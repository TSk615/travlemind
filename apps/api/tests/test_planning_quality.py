from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from travelmind_api.agents.base import *
from travelmind_api.agents.planning_core import PlanningCore
from travelmind_api.services.budgeting import enrich_plan_with_budget
from travelmind_api.services.execution_validation import validate_timeline
from travelmind_api.services.hotel_evidence import verify_hotel_pages
from travelmind_api.services.image_validation import inspect_image_bytes, validate_image_url
from travelmind_api.services.llm.parser import LlmPlanningPayload, parse_planning_response
from travelmind_api.services.llm.parser import LlmBookingInfo
from travelmind_api.services.llm.localization import planning_payload_needs_language_repair
from travelmind_api.services.planning_details import TransportLeg, TransportServiceCandidate
from travelmind_api.services.planning.role_models import (
    DailyForecast,
    HotelCandidate,
    HotelRecommendation,
    PoiGrounding,
    ResearchPoi,
    TransportGuidance,
    WeatherGuidance,
)
from travelmind_api.services.poi_operation_evidence import verify_poi_open_days
from travelmind_api.services.search_connector import SearchServiceConfig
from travelmind_api.services.transport_evidence import verify_transport_candidate_pages
from travelmind_api.services.weather_evidence import has_unsupported_weather_condition, verify_daily_forecast_pages
from travelmind_api.services.trip_image_enrichment import _extract_tavily_image_candidates, _rank_tavily_image_candidates


def request():
    return PlanningRequest(trip_id="qa", title="上海", origin="广州", destination="上海",
                           start_date="2026-09-20", end_date="2026-09-22", budget=6800,
                           travelers=2, interests=[], accommodation_preference="中档", pace="balanced", transport_mode="rail")


def item(name, start="09:00", end="10:00", **kw):
    return PlannedItem(id=name, name=name, type=kw.pop("type", "sight"), start_time=start,
                       end_time=end, location="上海", score=.8, note="", **kw)


def test_image_entity_and_source_merge():
    payload = {"images": [{"url": "https://cdn.example.org/correct.jpg", "description": "上海博物馆"}], "results": [
        {"url": "https://travel.example.org/police", "title": "上海公安博物館", "images": ["https://cdn.example.org/wrong.jpg"]},
        {"url": "https://travel.example.org/museum", "title": "上海博物館", "images": ["https://cdn.example.org/correct.jpg"]},
    ]}
    ranked = _rank_tavily_image_candidates(_extract_tavily_image_candidates(payload), item("上海博物馆"), request())
    assert len(ranked) == 1
    assert ranked[0].source_url == "https://travel.example.org/museum"


def test_image_bytes_must_decode_and_be_large_enough():
    with pytest.raises(Exception):
        inspect_image_bytes(b"<html>Forbidden</html>")
    buffer = BytesIO()
    Image.new("RGB", (800, 600)).save(buffer, format="PNG")
    assert inspect_image_bytes(buffer.getvalue())["width"] == 800
    buffer = BytesIO()
    Image.new("RGB", (32, 32)).save(buffer, format="PNG")
    with pytest.raises(ValueError):
        inspect_image_bytes(buffer.getvalue())
    assert validate_image_url("http://127.0.0.1/secret")[0] is None


def test_cross_day_clocks_survive_and_overlap_is_rejected():
    import json
    raw = {"summary": "跨夜交通", "days": [
        {"title": "出发", "items": [{"type": "transport", "name": "高铁", "start_time": "18:30",
                                    "end_time": "06:00", "end_day_offset": 1}]},
        {"title": "抵达", "items": [{"type": "sight", "name": "外滩", "start_time": "05:30", "end_time": "07:00"}]}
    ]}
    payload = parse_planning_response(json.dumps(raw))
    assert payload.days[0].items[0].end_time == "06:00"
    assert any("时间重叠" in error for error in validate_timeline(payload, request(), TransportGuidance()))


def test_poi_open_day_evidence_marks_non_holiday_monday_closed(monkeypatch):
    poi = ResearchPoi(name="故宫博物院", source_urls=["https://www.dpm.org.cn/Visit.html"])
    grounding = PoiGrounding(featured_pois=[poi])
    monkeypatch.setattr(
        "travelmind_api.services.poi_operation_evidence.ConfiguredSearchGateway.call_operation",
        lambda *_args, **_kwargs: {"results": [{
            "url": "https://www.dpm.org.cn/Visit.html",
            "title": "故宫博物院参观须知",
            "raw_content": "故宫博物院除法定节假日外每周一闭馆。",
        }]},
    )
    config = SearchServiceConfig(provider="tavily", transport="api", base_url="https://api.example.org", api_key="test")
    verified = verify_poi_open_days(
        grounding, start_date=date(2026, 9, 20), end_date=date(2026, 9, 22), search_config=config
    )
    assert any("2026-09-21" in note and "周一闭馆" in note for note in verified.featured_pois[0].evidence_notes)


def test_poi_open_day_evidence_respects_known_public_holiday_exception(monkeypatch):
    poi = ResearchPoi(name="示例博物馆", source_urls=["https://museum.example.org/visit"])
    grounding = PoiGrounding(featured_pois=[poi])
    monkeypatch.setattr(
        "travelmind_api.services.poi_operation_evidence.ConfiguredSearchGateway.call_operation",
        lambda *_args, **_kwargs: {"results": [{
            "url": "https://museum.example.org/visit",
            "title": "示例博物馆开放时间",
            "raw_content": "示例博物馆除法定节假日外每周一闭馆。",
        }]},
    )
    config = SearchServiceConfig(provider="tavily", transport="api", base_url="https://api.example.org", api_key="test")
    verified = verify_poi_open_days(
        grounding, start_date=date(2026, 2, 16), end_date=date(2026, 2, 16), search_config=config
    )
    assert verified.featured_pois[0].evidence_notes == []


def test_poi_open_day_evidence_discovers_official_page_when_guides_are_insufficient(monkeypatch):
    poi = ResearchPoi(name="恭王府", source_urls=["https://travel.qunar.com/p-cs299914-beijing-jingdian"])
    grounding = PoiGrounding(featured_pois=[poi])

    def fake_call(_self, operation, arguments):
        if operation == "search":
            return {"results": [{
                "url": "https://ticket.pgm.org.cn/visit.html",
                "title": "恭王府博物馆参观须知",
                "content": "开放时间与门票预约",
            }]}
        return {"results": [{
            "url": "https://ticket.pgm.org.cn/visit.html",
            "title": "恭王府博物馆参观须知",
            "raw_content": "恭王府博物馆除法定节假日外每周一闭馆。",
        }]}

    monkeypatch.setattr(
        "travelmind_api.services.poi_operation_evidence.ConfiguredSearchGateway.call_operation", fake_call,
    )
    config = SearchServiceConfig(provider="tavily", transport="api", base_url="https://api.example.org", api_key="test")
    verified = verify_poi_open_days(
        grounding, start_date=date(2026, 9, 20), end_date=date(2026, 9, 22), search_config=config
    )
    verified_poi = verified.featured_pois[0]
    assert "https://ticket.pgm.org.cn/visit.html" in verified_poi.source_urls
    assert any("2026-09-21" in note and "周一闭馆" in note for note in verified_poi.evidence_notes)


def test_planner_poi_collection_keeps_open_day_evidence():
    poi = ResearchPoi(
        name="故宫博物院",
        evidence_notes=["开放日来源复核：2026-09-21（周一）落在周一闭馆规则内。"],
        caveats=["须提前预约。"],
    )
    collection = PlanningCore(None)._build_poi_collection(PoiGrounding(featured_pois=[poi]))
    assert "周一闭馆" in collection["pois"][0]["evidence_notes"][0]
    assert collection["pois"][0]["caveats"] == ["须提前预约。"]


def test_high_transport_budget_and_dated_ledger():
    plan = PlanningResult(summary="上海", total_budget_estimate=6800, risks=[], trace=AgentTrace(provider="qa", workflow_id="qa", notes=[]),
                          days=[PlannedDay(day_index=index, title=str(index), summary="", total_cost=0,
                                           items=[item("酒店", type="lodging", booking_info=BookingInfo(estimated_price=1800))] if index == 2 else [])
                                for index in (1, 2, 3)],
                          transport_booking_summary=TransportBookingSummary(
                              estimated_intercity_cost=3800, estimated_local_transport_cost=120,
                              notes=["高铁在预算30%以内"], legs=[
                                  TransportLeg(scope="outbound", origin="广州", destination="上海", departure_date="2026-09-20", estimated_total=1900),
                                  TransportLeg(scope="return", origin="上海", destination="广州", departure_date="2026-09-22", estimated_total=1900),
                                  TransportLeg(scope="local", origin="酒店", destination="景点", departure_date="2026-09-21", estimated_total=120),
                              ]))
    result = enrich_plan_with_budget(plan, request())
    assert [day.total_cost for day in result.days] == [1900, 1920, 1900]
    assert result.budget_summary.breakdown.accommodation == 1800
    assert result.total_budget_estimate == 5720
    assert sum(line.amount for line in result.budget_summary.line_items) == 5720
    assert result.budget_summary.transport_budget_ratio == .5765
    assert "30%" not in " ".join(result.transport_booking_summary.notes)
    assert result.budget_summary.incomplete  # Dining is not priced.


def test_intercity_transport_item_is_not_counted_twice():
    plan = PlanningResult(
        summary="预算约9200元。",
        total_budget_estimate=9200,
        risks=["建议把剩余约4902元作为机动费用。"],
        trace=AgentTrace(provider="qa", workflow_id="qa", notes=[]),
        days=[PlannedDay(
            day_index=1,
            title="抵达",
            summary="",
            total_cost=1898,
            items=[item(
                "G246",
                type="intercity_transport",
                booking_info=BookingInfo(
                    estimated_price=1898,
                    price_status="estimated",
                    price_label="二等座949元/人，2人合计约1898元",
                    transport_scope="outbound",
                ),
            )],
        )],
        transport_booking_summary=TransportBookingSummary(
            estimated_intercity_cost=1900,
            estimated_local_transport_cost=0,
            legs=[TransportLeg(
                scope="outbound",
                origin="广州南",
                destination="上海虹桥",
                departure_date="2026-09-20",
                estimated_total=1900,
            )],
        ),
    )
    result = enrich_plan_with_budget(plan, request())
    assert result.total_budget_estimate == 1900
    assert result.days[0].total_cost == 1900
    assert result.budget_summary.breakdown.transport == 1900
    assert result.budget_summary.breakdown.other == 0
    assert "合计约1900元" in result.days[0].items[0].booking_info.price_label
    assert any("剩余约4900元" in risk for risk in result.risks)


def test_hotel_simplified_traditional_and_independent_evidence(monkeypatch):
    candidate = HotelCandidate(name="上海隐居繁华武康路公馆", city="上海", address="武康路100号",
                                          source_urls=["https://hotel.example.org/shanghai/detail"])
    hotel = HotelRecommendation(final_recommended_hotel=candidate)
    monkeypatch.setattr("travelmind_api.services.hotel_evidence.ConfiguredSearchGateway.call_operation",
                        lambda *args: {"results": [{"url": candidate.source_urls[0],
                            "raw_content": "# 上海隱居繁華武康路公館\n地址：上海武康路100號"}]})
    config = SearchServiceConfig(provider="tavily", transport="api", base_url="https://api.example.org", api_key="test")
    verified = verify_hotel_pages(hotel, config)
    assert verified.final_recommended_hotel.identity_status == "page_verified"
    assert candidate.identity_status == "model_reported"  # No mutation of raw model evidence.
    monkeypatch.setattr("travelmind_api.services.hotel_evidence.ConfiguredSearchGateway.call_operation",
                        lambda *args: {"results": []})
    assert verify_hotel_pages(hotel, config).final_recommended_hotel.identity_status == "unverified"


def test_early_checkin_without_evidence_fails():
    payload = LlmPlanningPayload(summary="上海", days=[{"title": "入住", "items": [
        {"type": "lodging", "name": "酒店入住", "start_time": "08:00", "end_time": "09:00"}
    ]}])
    assert any("提前入住未确认" in error for error in validate_timeline(payload, request(), TransportGuidance()))


def test_visual_review_only_accepts_explicit_complete_verdicts(monkeypatch):
    import json
    from travelmind_api.services.image_review import review_images
    from travelmind_api.services.llm.config import LlmConfig

    config = LlmConfig(base_url="https://model.example.org/v1", api_key="test", model="vision")
    candidate = SimpleNamespace(source_title="武康路", image_description="实景")
    candidates = [(candidate, {"preview_data_url": "data:image/jpeg;base64,test"})] * 2
    rows = [{"index": 0, "verdict": "accept", "reason": "实景"},
            {"index": 1, "verdict": "reject", "reason": "攻略封面"}]
    monkeypatch.setattr("travelmind_api.services.image_review.OpenAICompatibleClient.create_chat_completion",
                        lambda *args, **kwargs: json.dumps({"images": rows}))
    assert len(review_images(config, "武康路", "上海", candidates)[0]) == 1
    rows.pop()
    assert review_images(config, "武康路", "上海", candidates)[0] == []


def test_hotel_fetch_failure_cannot_become_verified():
    from travelmind_api.agents.planning_core import PlanningCore

    candidate = HotelCandidate(name="上海示例酒店", city="上海",
        source_urls=["https://hotel.example.org/detail/1"], source_page_titles=["上海示例酒店"])
    hotel = verify_hotel_pages(HotelRecommendation(final_recommended_hotel=candidate), None)
    assert not PlanningCore._is_verified_hotel_candidate(hotel.final_recommended_hotel, destination="上海")


def test_promoted_hotel_is_removed_from_alternative_candidates():
    candidate = HotelCandidate(
        name="上海示例酒店", city="上海", identity_status="page_verified",
        source_urls=["https://hotel.example.org/detail/1"], verified_source_urls=["https://hotel.example.org/detail/1"],
    )
    hotel = HotelRecommendation(hotel_candidates=[candidate])
    sanitized = PlanningCore(None)._sanitize_hotel_recommendation(hotel, destination="上海")
    assert sanitized.final_recommended_hotel.name == "上海示例酒店"
    assert sanitized.hotel_candidates == []


def test_verified_homestay_does_not_replace_explicit_hotel_preference():
    candidate = HotelCandidate(
        name="上海示例民宿", city="上海", hotel_type="历史洋房民宿", identity_status="page_verified",
        source_urls=["https://hotel.example.org/detail/1"], verified_source_urls=["https://hotel.example.org/detail/1"],
    )
    sanitized = PlanningCore(None)._sanitize_hotel_recommendation(
        HotelRecommendation(final_recommended_hotel=candidate),
        destination="上海",
        accommodation_preference="安静、交通方便的中档酒店",
    )
    assert sanitized.final_recommended_hotel is None
    assert any("住宿类型与用户偏好不一致" in risk for risk in sanitized.hotel_risks)


def test_image_fallback_preserves_configured_domains(monkeypatch):
    from travelmind_api.services.trip_image_enrichment import _resolve_tavily_image_search_config

    values = {"TRAVELMIND_TAVILY_API_KEY": "test", "TRAVELMIND_IMAGE_SEARCH_INCLUDE_DOMAINS": "travel.example.org"}
    monkeypatch.setattr("travelmind_api.services.trip_image_enrichment.get_env", lambda key: values.get(key))
    config = _resolve_tavily_image_search_config(None)
    assert config.image_include_domains == ["travel.example.org"]


def test_multi_day_local_transport_keeps_total_and_drops_ambiguous_unit_price():
    leg = TransportLeg.model_validate({"scope": "local", "origin": "上海市区", "destination": "上海市区",
        "departure_date": "2026-09-20", "arrival_date": "2026-09-22", "passenger_count": 2,
        "estimated_total": 200, "unit_price": 30})
    assert leg.estimated_total == 200
    assert leg.unit_price is None
    assert "口径不一致" in leg.pricing_note


def test_transport_service_candidate_keeps_static_timetable_fields():
    candidate = TransportServiceCandidate.model_validate({
        "scope": "outbound", "mode": "high_speed_rail", "train_no": "G246",
        "origin": "广州南", "destination": "上海虹桥", "departure_date": "2026-09-20",
        "dep_time": "8:27", "arrival_date": "2026-09-20", "arr_time": "15:03",
        "duration_minutes": 396, "fare_class": "二等座", "fare_amount": 949,
        "price_status": "estimated", "availability_status": "unknown", "schedule_status": "reference",
        "query_time": "2026-09-14 16:00+08:00",
        "source_url": "https://example.test/guangzhounan-shanghaihongqiao",
    })
    assert candidate.service_number == "G246"
    assert candidate.departure_time == "08:27"
    assert candidate.arrival_time == "15:03"
    assert candidate.availability_status == "unknown"


def test_transport_candidate_page_tuple_cannot_mix_adjacent_train_rows(monkeypatch):
    source = "https://rail.example.org/shanghai-guangzhou"
    candidates = [
        TransportServiceCandidate(scope="return", mode="rail", service_number="G251", origin="上海虹桥",
            destination="广州南", departure_date="2026-09-22", departure_time="14:00",
            arrival_time="20:14", schedule_checked_at="2026-09-15 10:00+08:00", source_url=source),
        TransportServiceCandidate(scope="return", mode="rail", service_number="G253", origin="上海虹桥",
            destination="广州南", departure_date="2026-09-22", departure_time="16:00",
            arrival_time="22:27", schedule_checked_at="2026-09-15 10:00+08:00", source_url=source),
        TransportServiceCandidate(scope="return", mode="rail", service_number="G255", origin="上海虹桥",
            destination="广州南", departure_date="2026-09-22", departure_time="09:07",
            arrival_time="14:14", schedule_checked_at="2026-09-15 10:00+08:00", source_url=source),
    ]
    page = (
        "14:00 上海虹桥 6小时14分 G251 20:14 广州北 "
        "16:00 上海虹桥 6小时27分 G253 22:27 广州南 "
        "09:07 上海南 5小时07分 G255 14:14 厦门北"
    )
    monkeypatch.setattr("travelmind_api.services.transport_evidence.ConfiguredSearchGateway.call_operation",
                        lambda *args: {"results": [{"url": source, "raw_content": page}]})
    config = SearchServiceConfig(provider="tavily", transport="api", base_url="https://api.example.org", api_key="test")
    verified = verify_transport_candidate_pages(TransportGuidance(service_candidates=candidates), config)
    assert [candidate.service_number for candidate in verified.service_candidates] == ["G253"]
    assert verified.service_candidates[0].evidence_status == "verified"
    assert "G251" in " ".join(verified.notes)


def test_transport_candidates_remain_referenced_when_page_extraction_fails(monkeypatch):
    candidate = TransportServiceCandidate(scope="outbound", mode="rail", service_number="G246",
        origin="广州南", destination="上海虹桥", departure_date="2026-09-20", departure_time="08:27",
        arrival_time="15:03", schedule_checked_at="2026-09-15 10:00+08:00",
        source_url="https://rail.example.org/guangzhou-shanghai")
    monkeypatch.setattr("travelmind_api.services.transport_evidence.ConfiguredSearchGateway.call_operation",
                        lambda *args: (_ for _ in ()).throw(RuntimeError("timeout")))
    config = SearchServiceConfig(provider="tavily", transport="api", base_url="https://api.example.org", api_key="test")
    verified = verify_transport_candidate_pages(TransportGuidance(service_candidates=[candidate]), config)
    assert [row.service_number for row in verified.service_candidates] == ["G246"]
    assert verified.service_candidates[0].evidence_status == "referenced"
    assert "待确认参考" in " ".join(verified.notes)


def test_transport_candidate_accepts_one_complete_markdown_row(monkeypatch):
    source = "https://rail.example.org/guangzhou-shanghai"
    candidate = TransportServiceCandidate(scope="outbound", mode="rail", service_number="G246",
        origin="广州南", destination="上海虹桥", departure_date="2026-09-20", departure_time="08:27",
        arrival_time="15:03", schedule_checked_at="2026-09-15 10:00+08:00", source_url=source)
    monkeypatch.setattr("travelmind_api.services.transport_evidence.ConfiguredSearchGateway.call_operation",
                        lambda *args: {"results": [{"url": source,
                            "raw_content": "| 车次 | 出发站 | 发车 | 到达站 | 到达 |\n| G246 | 广州南 | 08:27 | 上海虹桥 | 15:03 |"}]})
    config = SearchServiceConfig(provider="tavily", transport="api", base_url="https://api.example.org", api_key="test")
    verified = verify_transport_candidate_pages(TransportGuidance(service_candidates=[candidate]), config)
    assert [row.service_number for row in verified.service_candidates] == ["G246"]
    assert verified.service_candidates[0].evidence_status == "verified"


def test_transport_candidate_falls_back_to_single_service_detail_page(monkeypatch):
    route = "https://rail.example.org/shanghai-guangzhou"
    detail = "https://rail.example.org/trains/G253"
    candidate = TransportServiceCandidate(scope="return", mode="rail", service_number="G253",
        origin="上海虹桥", destination="广州南", departure_date="2026-09-22", departure_time="16:00",
        arrival_time="22:27", schedule_checked_at="2026-09-15 10:00+08:00", source_url=route)

    def operation(_self, name, arguments):
        if name == "search":
            return {"results": [{"url": detail, "title": "G253次列车时刻表", "content": "上海虹桥至广州南"}]}
        urls = arguments["urls"]
        if route in urls:
            return {"results": [{"url": route, "raw_content": "上海至广州线路班次列表"}]}
        return {"results": [{"url": detail,
            "raw_content": "| G253 | 上海虹桥 | 16:00 | 广州南 | 22:27 |"}]}

    monkeypatch.setattr("travelmind_api.services.transport_evidence.ConfiguredSearchGateway.call_operation", operation)
    config = SearchServiceConfig(provider="tavily", transport="api", base_url="https://api.example.org", api_key="test")
    verified = verify_transport_candidate_pages(TransportGuidance(service_candidates=[candidate]), config)
    assert [row.service_number for row in verified.service_candidates] == ["G253"]
    assert verified.service_candidates[0].source_url == detail
    assert verified.service_candidates[0].evidence_status == "verified"


def test_weather_fields_require_same_date_window_in_source(monkeypatch):
    supported_url = "https://weather.example.org/shanghai-15d"
    forecasts = [
        DailyForecast(date="2026-09-20", forecast_type="short_range", condition="多云转晴",
            temperature_min_c="24", temperature_max_c="30", wind="北风小于3级",
            outlook="多云转晴", checked_at="2026-09-15 10:00+08:00", source_urls=[supported_url]),
        DailyForecast(date="2026-09-21", forecast_type="short_range", condition="晴",
            temperature_min_c="23", temperature_max_c="29", wind="北风小于3级",
            outlook="晴", checked_at="2026-09-15 10:00+08:00", source_urls=[supported_url]),
    ]
    page = "09/20\n多云转晴\n30/24℃\n北风<3级\n09/21\n阴转雨\n27/21℃\n东风<3级"
    monkeypatch.setattr("travelmind_api.services.weather_evidence.ConfiguredSearchGateway.call_operation",
                        lambda *args: {"results": [{"url": supported_url, "raw_content": page}]})
    config = SearchServiceConfig(provider="tavily", transport="api", base_url="https://api.example.org", api_key="test")
    verified = verify_daily_forecast_pages(WeatherGuidance(overall_outlook="天气", daily_forecasts=forecasts), config)
    assert verified.daily_forecasts[0].forecast_type == "short_range"
    assert verified.daily_forecasts[0].evidence_status == "verified"
    assert verified.daily_forecasts[0].source_urls == [supported_url]
    assert verified.daily_forecasts[1].forecast_type == "short_range"
    assert verified.daily_forecasts[1].evidence_status == "conflicted"
    assert verified.daily_forecasts[1].condition == ""
    assert verified.daily_forecasts[1].source_urls == [supported_url]
    assert "?" not in verified.daily_forecasts[1].outlook


def test_weather_keeps_dated_sourced_values_as_reference_when_extract_fails(monkeypatch):
    source = "https://weather.example.org/shanghai-15d"
    forecast = DailyForecast(date="2026-09-22", forecast_type="short_range", condition="晴",
        temperature_min_c="21", temperature_max_c="30", checked_at="2026-09-15 10:00+08:00",
        source_urls=[source])
    monkeypatch.setattr("travelmind_api.services.weather_evidence.ConfiguredSearchGateway.call_operation",
                        lambda *args: (_ for _ in ()).throw(RuntimeError("timeout")))
    config = SearchServiceConfig(provider="tavily", transport="api", base_url="https://api.example.org", api_key="test")
    verified = verify_daily_forecast_pages(
        WeatherGuidance(overall_outlook="天气", daily_forecasts=[forecast]), config)
    assert verified.daily_forecasts[0].condition == "晴"
    assert verified.daily_forecasts[0].temperature_max_c == "30"
    assert verified.daily_forecasts[0].evidence_status == "referenced"
    assert verified.daily_forecasts[0].field_evidence["condition"] == "referenced"


def test_weather_condition_is_verified_when_one_of_multiple_sources_supports_it(monkeypatch):
    urls = ["https://weather.example.org/a", "https://weather.example.org/b"]
    forecast = DailyForecast(date="2026-09-22", forecast_type="short_range", condition="多云转晴",
        temperature_min_c="21", temperature_max_c="30", checked_at="2026-09-15 10:00+08:00", source_urls=urls)
    monkeypatch.setattr(
        "travelmind_api.services.weather_evidence.ConfiguredSearchGateway.call_operation",
        lambda *args: {"results": [
            {"url": urls[0], "raw_content": "09/22\n多云转晴\n30/21℃"},
            {"url": urls[1], "raw_content": "09/22\n多云\n30/21℃"},
        ]},
    )
    config = SearchServiceConfig(provider="tavily", transport="api", base_url="https://api.example.org", api_key="test")
    verified = verify_daily_forecast_pages(
        WeatherGuidance(overall_outlook="天气", daily_forecasts=[forecast]), config)
    assert verified.daily_forecasts[0].condition == "多云转晴"
    assert verified.daily_forecasts[0].field_evidence["condition"] == "verified"


def test_weather_drops_unverified_conflicting_condition_claims(monkeypatch):
    source = "https://weather.example.org/shanghai-15d"
    forecast = DailyForecast(
        date="2026-09-22",
        forecast_type="short_range",
        condition="多云转晴",
        temperature_min_c="21",
        temperature_max_c="30",
        wind="北风小于3级",
        risk="部分来源提示阵雨",
        checked_at="2026-09-15 10:00+08:00",
        source_urls=[source],
    )
    monkeypatch.setattr(
        "travelmind_api.services.weather_evidence.ConfiguredSearchGateway.call_operation",
        lambda *args: {"results": [{"url": source, "raw_content": "09/22\n多云转晴\n30/21℃\n北风小于3级"}]},
    )
    config = SearchServiceConfig(provider="tavily", transport="api", base_url="https://api.example.org", api_key="test")
    verified = verify_daily_forecast_pages(
        WeatherGuidance(
            overall_outlook="降水概率较低",
            daily_forecasts=[forecast],
            weather_risks=["22日可能有阵雨", "早晚温差较大"],
        ),
        config,
    )
    assert verified.daily_forecasts[0].risk == ""
    assert verified.weather_risks == ["早晚温差较大"]
    assert "降水概率较低" not in verified.overall_outlook
    assert has_unsupported_weather_condition("可能有阵雨", ["多云转晴"])


def test_monday_closure_note_is_a_hard_timeline_error():
    payload = LlmPlanningPayload(summary="闭馆冲突", days=[
        {"title": "周日", "items": [{"type": "sight", "name": "外滩", "start_time": "09:00", "end_time": "10:00"}]},
        {"title": "周一", "items": [{"type": "sight", "name": "上海博物馆", "start_time": "09:30",
          "end_time": "11:30", "visit_requirements": {"notes": ["周一闭馆（国定假日除外）"]}}]},
        {"title": "周二", "items": [{"type": "sight", "name": "豫园", "start_time": "09:00", "end_time": "10:00"}]},
    ])
    assert any("当天闭馆" in error for error in validate_timeline(payload, request(), TransportGuidance()))


def test_poi_source_closure_survives_when_planner_drops_the_note():
    payload = LlmPlanningPayload(summary="闭馆冲突", days=[
        {"title": "周日", "items": [{"type": "sight", "name": "外滩", "start_time": "09:00", "end_time": "10:00"}]},
        {"title": "周一", "items": [{"type": "sight", "name": "上海博物馆", "start_time": "09:30", "end_time": "11:30"}]},
        {"title": "周二", "items": [{"type": "sight", "name": "豫园", "start_time": "09:00", "end_time": "10:00"}]},
    ])
    grounding = PoiGrounding(featured_pois=[
        ResearchPoi(name="上海博物馆", visit_requirements=VisitRequirements(notes=["每周一闭馆"]))
    ])
    with pytest.raises(ValueError, match="POI 专家证据注明当天闭馆"):
        PlanningCore(None)._validate_execution_constraints(
            payload, request(), TransportGuidance(), poi_grounding=grounding,
        )


def test_unused_related_pois_are_attached_as_nearby_suggestions():
    source = "https://guide.example.org/bund"
    grounding = PoiGrounding(featured_pois=[
        ResearchPoi(name="外滩", area="黄浦区", source_urls=[source]),
        ResearchPoi(
            name="外白渡桥",
            area="黄浦区",
            reason="可与外滩顺路组合，补充历史桥梁视角。",
            suggested_time="30分钟",
            highlights=["铁桥建筑", "苏州河口"],
            source_urls=[source],
            confidence="high",
        ),
        ResearchPoi(
            name="豫园",
            area="黄浦区",
            reason="古典园林",
            source_urls=["https://guide.example.org/yuyuan"],
        ),
    ])
    hotel = item("上海外滩酒店", type="lodging")
    days = [PlannedDay(day_index=1, title="外滩", summary="", total_cost=0, items=[hotel, item("外滩")])]
    PlanningCore(None)._attach_nearby_poi_suggestions(days, grounding)
    assert hotel.nearby_suggestions == []
    suggestions = days[0].items[1].nearby_suggestions
    assert [row.name for row in suggestions] == ["外白渡桥"]
    assert suggestions[0].source_urls == [source]
    assert suggestions[0].relation_type == "suggested_pair"


def test_unverified_area_level_hotel_price_is_removed_from_budget():
    plan = PlanningResult(summary="住宿", total_budget_estimate=1100, risks=[],
        trace=AgentTrace(provider="qa", workflow_id="qa", notes=[]), days=[
            PlannedDay(day_index=1, title="入住", summary="", total_cost=1100, items=[
                item("黄浦区或徐汇区安静中档酒店", type="lodging",
                     booking_info=BookingInfo(estimated_price=1100, unit_price=1100, price_status="estimated"))
            ])
        ], stay_recommendation=StayRecommendation(recommended_areas=["黄浦区", "徐汇区"]))
    PlanningCore._clear_unverified_lodging_prices(plan)
    result = enrich_plan_with_budget(plan, request())
    booking = result.days[0].items[0].booking_info
    assert booking.estimated_price is None and booking.unit_price is None
    assert result.budget_summary.breakdown.accommodation == 0
    assert any("黄浦区或徐汇区" in value for value in result.budget_summary.unpriced_items)
    assert "当前已计价小计为0元" in result.summary
    assert "最终总费用" in result.summary


def test_unverified_hotel_numeric_risk_is_removed():
    plan = PlanningResult(summary="上海行程。预算估算约1200元，低于6800元硬预算。", total_budget_estimate=1200,
        risks=["酒店未核验，按中档酒店估算1200元。"], trace=AgentTrace(provider="qa", workflow_id="qa", notes=[]),
        days=[PlannedDay(day_index=1, title="入住", summary="", total_cost=1200, items=[
            item("黄浦区中档酒店", type="lodging", booking_info=BookingInfo(estimated_price=1200, price_status="estimated"))
        ])])
    PlanningCore._clear_unverified_lodging_prices(plan)
    result = enrich_plan_with_budget(plan, request())
    assert "1200元" not in " ".join(result.risks)
    assert "低于6800元" not in result.summary


def test_mandatory_reservation_without_official_entry_is_downgraded():
    museum = item("上海博物馆", booking_info=BookingInfo(booking_required=True, reservation_required=True,
        reminder="免费不等于免预约", notes=["请尽快预约名额"]),
        visit_requirements=VisitRequirements(reservation_policy="required", timed_entry=True,
            identity_required=True, advance_booking_note="必须实名预约", notes=["热门时段需预约"]))
    plan = PlanningResult(summary="博物馆", total_budget_estimate=0, risks=[],
        trace=AgentTrace(provider="qa", workflow_id="qa", notes=[]),
        days=[PlannedDay(day_index=1, title="博物馆", summary="", total_cost=0, items=[museum])])
    PlanningCore._downgrade_unverified_reservation_claims(plan)
    assert museum.booking_info.reservation_required is False
    assert museum.booking_info.booking_required is False
    assert museum.visit_requirements.reservation_policy == "check_before_visit"
    assert museum.visit_requirements.timed_entry is False
    assert "出发前核对" in museum.booking_info.reminder


def test_enum_reservation_policy_does_not_trigger_chinese_repair():
    payload = LlmPlanningPayload(summary="上海三日游", days=[{"title": "第一天", "summary": "游览",
        "items": [{"type": "sight", "name": "外滩", "start_time": "09:00", "end_time": "10:00",
                   "note": "沿江游览", "visit_requirements": {"reservation_policy": "required"}}]}])
    assert not planning_payload_needs_language_repair(payload, request())


def test_budget_rewrites_stale_total_in_summary():
    plan = PlanningResult(summary="统一前总估算费用为5240元，餐饮未计入。", total_budget_estimate=5240, risks=[],
        trace=AgentTrace(provider="qa", workflow_id="qa", notes=[]), days=[PlannedDay(day_index=1, title="第一天", summary="",
        total_cost=0, items=[item("酒店", type="lodging", booking_info=BookingInfo(estimated_price=1200, price_status="estimated"))])])
    result = enrich_plan_with_budget(plan, request())
    assert "已计价小计为1200元" in result.summary
    assert "5240元" not in result.summary
    result.total_budget_estimate = 0
    result.days[0].items[0].booking_info.estimated_price = 900
    rerun = enrich_plan_with_budget(result, request())
    assert "已计价小计为900元" in rerun.summary
    assert "1200元" not in rerun.summary


def test_local_transport_items_replace_multi_day_aggregate_leg():
    days = []
    for index in (1, 2, 3):
        days.append(PlannedDay(day_index=index, title=str(index), summary="", total_cost=0, items=[
            item(f"第{index}天市内交通", type="local_transport",
                 booking_info=BookingInfo(estimated_price=80, price_status="estimated", transport_scope="local"))
        ]))
    plan = PlanningResult(summary="交通", total_budget_estimate=240, risks=[],
        trace=AgentTrace(provider="qa", workflow_id="qa", notes=[]), days=days,
        transport_booking_summary=TransportBookingSummary(estimated_intercity_cost=0, estimated_local_transport_cost=240,
            legs=[TransportLeg(scope="local", origin="市区", destination="市区", departure_date="2026-09-20",
                               arrival_date="2026-09-22", estimated_total=240)]))
    result = enrich_plan_with_budget(plan, request())
    assert [day.total_cost for day in result.days] == [80, 80, 80]
    assert result.total_budget_estimate == 240
    assert all(line.category == "transport" for line in result.budget_summary.line_items)
    assert all(
        day.total_cost == sum(float(row.booking_info.estimated_price or 0) for row in day.items if row.booking_info)
        for day in result.days
    )


def test_arrival_transport_scope_is_normalized_to_local():
    assert LlmBookingInfo(transport_scope="arrival").transport_scope == "local"


def test_hotel_to_station_transfer_is_not_treated_as_return_train():
    payload = LlmPlanningPayload(summary="返程", days=[{"title": "返程", "items": [
        {"type": "transport", "name": "酒店至上海虹桥站", "start_time": "10:30", "end_time": "11:00",
         "booking_info": {"transport_scope": "return", "duration_minutes_min": 30}},
        {"type": "transport", "name": "上海虹桥至广州南高铁", "start_time": "14:00", "end_time": "21:00",
         "booking_info": {"transport_scope": "return", "duration_minutes_min": 400}},
    ]}])
    normalized = PlanningCore(None)._mark_unverified_schedules_as_planning_windows(payload, request())
    assert normalized.days[0].items[0].booking_info.transport_scope == "local"
    assert normalized.days[0].items[1].booking_info.transport_scope == "return"


def test_planner_transport_time_is_overwritten_by_evidence_candidate():
    candidate = TransportServiceCandidate(
        scope="outbound", mode="rail", service_number="G246", origin="广州南", destination="上海虹桥",
        departure_date="2026-09-20", departure_time="08:27", arrival_time="15:03",
        schedule_checked_at="2026-09-15 10:00+08:00", source_url="https://rail.example.org/G246",
        evidence_status="referenced", evidence_checked_at="2026-09-15T10:01:00+08:00",
        evidence_reason="正文待复核。",
    )
    payload = LlmPlanningPayload(summary="去程", days=[{"title": "抵达", "items": [
        {"type": "transport", "name": "G246 广州南至上海虹桥站", "start_time": "09:00", "end_time": "16:00",
         "booking_info": {"transport_scope": "outbound", "service_number": "G246",
                          "schedule_status": "reference", "schedule_checked_at": "错误时间",
                          "schedule_source_url": "https://wrong.example.org"}},
    ]}])
    normalized = PlanningCore(None)._mark_unverified_schedules_as_planning_windows(
        payload, request(), TransportGuidance(service_candidates=[candidate]))
    item = normalized.days[0].items[0]
    assert (item.start_time, item.end_time) == ("08:27", "15:03")
    assert item.booking_info.transport_scope == "outbound"
    assert item.booking_info.schedule_source_url == candidate.source_url
    assert item.booking_info.evidence_status == "referenced"


def test_same_service_number_with_wrong_direction_is_not_accepted():
    candidate = TransportServiceCandidate(
        scope="return", mode="rail", service_number="G246", origin="上海虹桥", destination="广州南",
        departure_date="2026-09-20", departure_time="16:00", arrival_time="22:27",
        schedule_checked_at="2026-09-15 10:00+08:00", source_url="https://rail.example.org/G246",
        evidence_status="verified",
    )
    payload = LlmPlanningPayload(summary="去程", days=[{"title": "抵达", "items": [
        {"type": "transport", "name": "G246 广州南至上海虹桥", "start_time": "08:00", "end_time": "15:00",
         "booking_info": {"transport_scope": "outbound", "service_number": "G246",
                          "schedule_status": "reference", "schedule_checked_at": "模型时间",
                          "schedule_source_url": "https://wrong.example.org"}},
    ]}])
    normalized = PlanningCore(None)._mark_unverified_schedules_as_planning_windows(
        payload, request(), TransportGuidance(service_candidates=[candidate]))
    booking = normalized.days[0].items[0].booking_info
    assert booking.service_number is None
    assert booking.transport_scope == "outbound"
    assert booking.schedule_status == "unknown"
    assert booking.evidence_status == "unknown"


def test_long_station_wait_is_capped_without_reducing_return_buffer():
    payload = LlmPlanningPayload(summary="返程", days=[{"title": "返程", "items": [
        {"type": "sight", "name": "上海博物馆", "start_time": "09:00", "end_time": "11:30"},
        {"type": "transport", "name": "取行李并前往上海虹桥站", "start_time": "12:20", "end_time": "13:25",
         "booking_info": {"transport_scope": "local", "duration_minutes_min": 65}},
        {"type": "transport", "name": "上海虹桥站安检、检票与候车", "start_time": "13:25", "end_time": "16:00",
         "booking_info": {"transport_scope": "return", "duration_minutes_min": 155}},
        {"type": "transport", "name": "G253 上海虹桥至广州南", "start_time": "16:00", "end_time": "22:27",
         "booking_info": {"transport_scope": "return", "service_number": "G253"}},
    ]}])
    normalized = PlanningCore(None)._normalize_departure_waiting_blocks(
        payload,
        TransportGuidance(station_buffer_minutes=45),
    )
    transfer, waiting = normalized.days[0].items[1:3]
    assert (transfer.start_time, transfer.end_time) == ("13:40", "14:45")
    assert (waiting.start_time, waiting.end_time) == ("14:45", "16:00")
    assert waiting.booking_info.transport_scope == "local"
    assert waiting.booking_info.duration_minutes_min == 75


def test_station_wait_within_cap_is_still_reclassified_as_local_buffer():
    payload = LlmPlanningPayload(summary="返程", days=[{"title": "返程", "items": [
        {"type": "transport", "name": "酒店至北京西站", "start_time": "10:30", "end_time": "11:30",
         "booking_info": {"transport_scope": "local", "duration_minutes_min": 30}},
        {"type": "activity", "name": "北京西站安检检票与候车", "start_time": "11:30", "end_time": "12:30",
         "booking_info": {"transport_scope": "return", "duration_minutes_min": 60}},
        {"type": "transport", "name": "G305 北京西至广州南", "start_time": "12:30", "end_time": "20:13",
         "booking_info": {"transport_scope": "return", "service_number": "G305", "duration_minutes_min": 463}},
    ]}])
    normalized = PlanningCore(None)._normalize_departure_waiting_blocks(
        payload,
        TransportGuidance(station_buffer_minutes=60),
    )
    waiting = normalized.days[0].items[1]
    assert waiting.booking_info.transport_scope == "local"
    assert waiting.booking_info.duration_minutes_min == 60


def test_sparse_arrival_day_is_rejected_when_many_pois_are_available():
    payload = LlmPlanningPayload(summary="过空", days=[
        {"title": "抵达", "items": [
            {"type": "transport", "name": "广州南至上海虹桥高铁", "start_time": "08:00", "end_time": "15:00"},
            {"type": "lodging", "name": "酒店入住", "start_time": "16:00", "end_time": "16:30"},
        ]},
        {"title": "游览", "items": [
            {"type": "sight", "name": "上海博物馆", "start_time": "09:00", "end_time": "11:00"},
            {"type": "sight", "name": "规划展示馆", "start_time": "13:00", "end_time": "15:00"},
            {"type": "sight", "name": "外滩", "start_time": "16:00", "end_time": "18:00"},
        ]},
        {"title": "返程", "items": [
            {"type": "transport", "name": "上海虹桥至广州南高铁", "start_time": "14:00", "end_time": "21:00"},
        ]},
    ])
    with pytest.raises(ValueError, match="内容密度不足"):
        PlanningCore(None)._validate_execution_constraints(
            payload, request(), TransportGuidance(), available_poi_count=14,
        )


def test_overnight_transport_without_offset_gets_deterministic_next_day_offset():
    import json
    raw = {"summary": "返程", "days": [{"title": "返程", "items": [{"type": "transport", "name": "高铁返程窗口",
        "start_time": "17:30", "end_time": "00:30", "booking_info": {"duration_minutes_min": 396}}]}]}
    parsed = parse_planning_response(json.dumps(raw))
    assert parsed.days[0].items[0].end_day_offset == 1


def test_unverified_final_return_window_is_shifted_inside_trip_end():
    payload = LlmPlanningPayload(summary="返程", days=[{"title": "返程", "items": [
        {"type": "sight", "name": "南京路", "start_time": "11:45", "end_time": "12:30"},
        {"type": "transport", "name": "取行李、前往虹桥站并候车", "start_time": "14:45", "end_time": "17:30",
         "booking_info": {"transport_scope": "local"}},
        {"type": "transport", "name": "高铁返程窗口", "start_time": "17:30", "end_time": "00:30",
         "booking_info": {"transport_scope": "return", "duration_minutes_min": 396}},
    ]}])
    orchestrator = PlanningCore(None)
    shifted = orchestrator._mark_unverified_schedules_as_planning_windows(payload, request())
    assert (shifted.days[0].items[-1].start_time, shifted.days[0].items[-1].end_time,
            shifted.days[0].items[-1].end_day_offset) == ("16:45", "23:45", 0)
    assert (shifted.days[0].items[-2].start_time, shifted.days[0].items[-2].end_time) == ("14:00", "16:45")
