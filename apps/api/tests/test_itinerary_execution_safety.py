import json
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from travelmind_api.agents.base import PlanningRequest
from travelmind_api.agents.planning_core import PlanningCore
from travelmind_api.services.planning.role_models import (
    TransportGuidance,
    WeatherGuidance,
)
from travelmind_api.services.llm import LlmConfig
from travelmind_api.services.llm.parser import parse_planning_response
from travelmind_api.services.maps import StubMapsPoiProvider
from travelmind_api.services.trip_service import validate_trip_dates_for_generation


def _orchestrator() -> PlanningCore:
    return PlanningCore(
        LlmConfig(base_url="https://llm.example.test/v1", api_key="test-key", model="gpt-test", wire_api="responses"),
        maps_provider=StubMapsPoiProvider(),
    )


def _request(*, start_date: date, end_date: date, generated_at: datetime | None = None) -> PlanningRequest:
    return PlanningRequest(
        trip_id="trip_safety",
        title="广州到汕头",
        origin="广州",
        destination="汕头",
        start_date=start_date,
        end_date=end_date,
        budget=6800,
        travelers=2,
        interests=["城市漫步", "海边风景"],
        accommodation_preference="市区酒店",
        pace="balanced",
        transport_mode="rail",
        planning_generated_at=generated_at,
        locale="zh-CN",
    )


def _payload(days: list[dict]):
    return parse_planning_response(
        json.dumps(
            {
                "summary": "可执行性测试",
                "total_budget_estimate": 1000,
                "risks": [],
                "days": days,
            },
            ensure_ascii=False,
        )
    )


def _item(name: str, start: str, end: str, *, item_type: str = "sight", booking_info: dict | None = None) -> dict:
    return {
        "type": item_type,
        "name": name,
        "start_time": start,
        "end_time": end,
        "location": "汕头",
        "score": 0.9,
        "note": "测试项目",
        "booking_info": booking_info,
    }


def test_generation_rejects_a_saved_trip_that_has_expired():
    now = datetime(2026, 9, 8, 17, 0, tzinfo=timezone(timedelta(hours=8)))
    with pytest.raises(HTTPException) as exc_info:
        validate_trip_dates_for_generation(date(2026, 9, 7), date(2026, 9, 10), now=now)
    assert exc_info.value.detail["code"] == "expired_trip_start_date"


def test_same_day_plan_rejects_items_before_the_generation_window():
    # This legacy rule uses host-local time: keep the fixture at 17:00 on both UTC CI and local Windows.
    now = datetime(2026, 9, 8, 17, 0).astimezone()
    request = _request(start_date=now.date(), end_date=now.date(), generated_at=now)
    payload = _payload(
        [{"title": "当天", "summary": "", "total_cost": 500, "items": [_item("小公园", "09:00", "11:00")]}]
    )
    with pytest.raises(ValueError, match="早于可执行时间 17:30"):
        _orchestrator()._validate_execution_constraints(payload, request, TransportGuidance())


def test_cross_day_duplicate_poi_is_rejected():
    request = _request(start_date=date(2026, 9, 9), end_date=date(2026, 9, 10))
    payload = _payload(
        [
            {"title": "第一天", "summary": "", "total_cost": 500, "items": [_item("汕头小公园", "09:00", "11:00")]},
            {"title": "第二天", "summary": "", "total_cost": 500, "items": [_item("汕头小公园", "10:00", "12:00")]},
        ]
    )
    with pytest.raises(ValueError, match="重复"):
        _orchestrator()._validate_execution_constraints(payload, request, TransportGuidance())


def test_cross_day_duplicate_poi_with_presentation_suffix_is_rejected():
    request = _request(start_date=date(2026, 9, 9), end_date=date(2026, 9, 10))
    payload = _payload(
        [
            {"title": "第一天", "summary": "", "total_cost": 500, "items": [_item("南澳岛景区", "09:00", "11:00")]},
            {"title": "第二天", "summary": "", "total_cost": 500, "items": [_item("南澳岛再访", "10:00", "12:00")]},
        ]
    )
    with pytest.raises(ValueError, match="重复"):
        _orchestrator()._validate_execution_constraints(payload, request, TransportGuidance())


def test_departure_day_enforces_transfer_luggage_and_station_buffer():
    request = _request(start_date=date(2026, 9, 9), end_date=date(2026, 9, 9))
    payload = _payload(
        [
            {
                "title": "返程日",
                "summary": "",
                "total_cost": 500,
                "items": [
                    _item("小公园", "10:00", "12:00"),
                    _item("潮汕站到广州南高铁", "13:30", "17:30", item_type="transport"),
                ],
            }
        ]
    )
    transport = TransportGuidance(
        departure_transfer_minutes=50,
        station_buffer_minutes=45,
        luggage_buffer_minutes=30,
        minimum_departure_buffer_minutes=125,
    )
    with pytest.raises(ValueError, match="仅 90 分钟，至少需要 125 分钟"):
        _orchestrator()._validate_execution_constraints(payload, request, transport)


def test_departure_buffer_rejects_an_invalid_time_instead_of_skipping_validation():
    request = _request(start_date=date(2026, 9, 9), end_date=date(2026, 9, 9))
    payload = _payload(
        [
            {
                "title": "返程日",
                "summary": "",
                "total_cost": 500,
                "items": [
                    _item("小公园", "10:00", "12:00"),
                    _item("潮汕站到广州南高铁", "13:30", "17:30", item_type="transport"),
                ],
            }
        ]
    )
    payload.days[0].items[1].start_time = "99:99"
    with pytest.raises(ValueError, match="返程缓冲无法校验"):
        _orchestrator()._validate_execution_constraints(payload, request, TransportGuidance())


def test_unverified_train_time_is_marked_as_a_planning_window():
    request = _request(start_date=date(2026, 9, 9), end_date=date(2026, 9, 9))
    payload = _payload(
        [
            {
                "title": "出发日",
                "summary": "",
                "total_cost": 500,
                "items": [
                    _item(
                        "广州南到潮汕站高铁",
                        "08:00",
                        "12:00",
                        item_type="transport",
                        booking_info={"official_booking_url": "https://www.12306.cn/"},
                    )
                ],
            }
        ]
    )
    normalized = _orchestrator()._mark_unverified_schedules_as_planning_windows(payload, request)
    item = normalized.days[0].items[0]
    assert "班次待确认" in item.name
    assert "建议出行预留窗口" in item.note
    assert item.booking_info is not None
    assert item.booking_info.schedule_verified is False


def test_weather_requires_exact_trip_date_coverage_for_real_generation():
    now = datetime(2026, 9, 8, 17, 0, tzinfo=timezone(timedelta(hours=8)))
    request = _request(start_date=date(2026, 9, 9), end_date=date(2026, 9, 10), generated_at=now)
    weather = WeatherGuidance(
        overall_outlook="天气参考",
        daily_forecasts=[{"date": "2026-09-09", "outlook": "有阵雨"}],
    )
    with pytest.raises(ValueError, match="2026-09-10"):
        _orchestrator()._validate_weather_date_coverage(weather, request)
