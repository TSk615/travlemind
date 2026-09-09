import json
import time
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from pypdf import PdfReader



def _register(client: TestClient):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Planner",
            "email": "planner@example.com",
            "password": "supersecure123",
        },
    )
    assert response.status_code == 200



def _future_trip_dates(*, start_offset_days: int = 1, duration_days: int = 2) -> tuple[str, str]:
    start_date = date.today() + timedelta(days=start_offset_days)
    end_date = start_date + timedelta(days=duration_days)
    return start_date.isoformat(), end_date.isoformat()


def _create_trip(client: TestClient) -> dict:
    start_date, end_date = _future_trip_dates()
    trip_response = client.post(
        "/api/v1/trips",
        json={
            "title": "Kyoto calm days",
            "origin": "Shanghai",
            "destination": "Kyoto",
            "start_date": start_date,
            "end_date": end_date,
            "budget": 4800,
            "travelers": 2,
            "interests": ["temples", "coffee"],
            "accommodation_preference": "Quiet boutique hotel",
            "pace": "balanced",
            "transport_mode": "rail",
        },
    )
    assert trip_response.status_code == 200
    return trip_response.json()["data"]



def _wait_for_job(client: TestClient, job_id: str) -> dict:
    payload = None
    for _ in range(10):
        response = client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200
        payload = response.json()["data"]
        if payload["status"] in {"completed", "failed", "cancelled"}:
            return payload
        time.sleep(0.1)
    assert payload is not None
    return payload



def _fake_helloagents_module(*, failing_role: str | None = None):
    class FakeSimpleAgent:
        def __init__(self, *, name, llm, system_prompt, **kwargs):
            self.name = name
            self.llm = llm
            self.system_prompt = system_prompt
            self.kwargs = kwargs

        def run(self, prompt):
            if failing_role == self.name:
                raise RuntimeError(f"forced upstream failure for {self.name}")
            if self.name == "brief_parser":
                return json.dumps(
                    {
                        "destination": "Kyoto",
                        "trip_days": 3,
                        "budget_band": "midrange",
                        "pace": "balanced",
                        "must_have": ["temples", "coffee"],
                        "avoid": ["overpacked long-distance transfers"],
                        "transport": "rail",
                        "accommodation": "Quiet boutique hotel",
                        "interests": ["temples", "coffee"],
                        "planning_constraints": ["keep sequencing realistic"],
                    }
                )
            if self.name in {"attraction_specialist", "poi_specialist"}:
                return json.dumps(
                    {
                        "candidate_areas": ["Higashiyama", "Downtown Kyoto", "Arashiyama"],
                        "featured_pois": [
                            {"name": "Ginkaku-ji", "area": "Higashiyama", "reason": "Calm morning.", "suggested_time": "morning"},
                            {"name": "Nishiki Market", "area": "Downtown Kyoto", "reason": "Food focus.", "suggested_time": "midday"},
                        ],
                        "sequencing_hints": ["Group nearby sights in the same half-day block."],
                        "crowd_notes": ["Arrive early at the headline sights."],
                        "attraction_risks": ["Long cross-city transfers will hurt pacing."],
                    }
                )
            if self.name == "weather_specialist":
                trip_request = json.loads(prompt)["trip_request"]
                first_day = date.fromisoformat(trip_request["start_date"])
                trip_days = int(trip_request["trip_days"])
                return json.dumps(
                    {
                        "overall_outlook": "Cool mornings and mild afternoons with occasional light rain.",
                        "daily_outlook": ["Day 1: cool start, mild afternoon.", "Day 2: light rain risk after lunch.", "Day 3: mild and comfortable."],
                        "daily_forecasts": [
                            {
                                "date": (first_day + timedelta(days=offset)).isoformat(),
                                "outlook": "Cool to mild with possible light rain.",
                                "timing_advice": "Keep outdoor walks before late afternoon.",
                                "risk": "Forecast confidence may change.",
                            }
                            for offset in range(trip_days)
                        ],
                        "packing_notes": ["Carry a light layer.", "Bring a compact umbrella."],
                        "timing_guidance": ["Outdoor walks fit best before late afternoon."],
                        "weather_risks": ["Light rain may affect exposed temple walks."],
                    }
                )
            if self.name == "hotel_specialist":
                return json.dumps(
                    {
                        "recommended_areas": ["Downtown Kyoto", "Higashiyama"],
                        "hotel_candidates": [
                            {
                                "name": "Downtown Kyoto Hotel",
                                "area": "Downtown Kyoto",
                                "reason": "Balanced access to food and transit.",
                                "price_hint": "moderate",
                                "source_urls": ["https://hotel.example.test/downtown-kyoto"],
                            }
                        ],
                        "stay_strategy": ["Prefer one transit-friendly base for the whole trip."],
                        "budget_notes": ["Keep the hotel near the nightly target budget band."],
                    }
                )
            if self.name == "transport_specialist":
                return json.dumps(
                    {
                        "intercity_options": [
                            {
                                "mode": "high_speed_rail",
                                "route": "Osaka to Kyoto Station",
                                "duration_hint": "about 15 to 30 minutes",
                                "price_hint": "roughly within the live rail fare range",
                                "booking_window": "Reserve early during peak periods",
                                "reason": "Fastest practical rail transfer into central Kyoto.",
                            }
                        ],
                        "arrival_strategy": ["Keep the arrival transfer aligned with the hotel area and first-day pacing."],
                        "local_mobility_strategy": ["Use rail or subway first, with buses only when they reduce walking burden."],
                        "pass_or_ticket_notes": ["Only recommend rail passes when they beat point-to-point tickets."],
                        "budget_notes": ["Treat the rail transfer as a dedicated transport cost and keep it grounded."],
                        "transport_risks": ["Peak-hour trains may be crowded or require reserved seats."],
                        "sequencing_constraints": ["Keep departure-day activities close to the final station corridor."],
                        "estimated_intercity_cost": 320,
                        "estimated_local_transport_cost": 60,
                    }
                )
            if self.name == "itinerary_planner":
                assert "poi_collection" in prompt
                assert "weather" in prompt
                assert "hotels" in prompt
                assert "transport" in prompt
                return json.dumps(
                    {
                        "summary": "Three Kyoto days coordinated across attractions, weather, and hotel strategy.",
                        "total_budget_estimate": 4700,
                        "risks": ["Popular sites may require early arrival."],
                        "days": [
                            {
                                "title": "2026-04-14 | East Kyoto",
                                "summary": "Temple-heavy first day.",
                                "total_cost": 1500,
                                "items": [
                                    {"type": "sight", "name": "Ginkaku-ji", "start_time": "09:00", "end_time": "11:00", "location": "Kyoto", "score": 0.9, "note": "Start calm and scenic."},
                                    {"type": "meal", "name": "Philosopher's Path coffee stop", "start_time": "12:00", "end_time": "13:30", "location": "Kyoto", "score": 0.82, "note": "Cafe stop near the walking route."},
                                ],
                            },
                            {
                                "title": "2026-04-15 | Central Kyoto",
                                "summary": "Markets and neighborhood food stops.",
                                "total_cost": 1600,
                                "items": [
                                    {"type": "food", "name": "Nishiki Market brunch", "start_time": "10:00", "end_time": "12:00", "location": "Kyoto", "score": 0.84, "note": "Flexible food crawl."},
                                    {"type": "explore", "name": "Kamo River slow walk", "start_time": "14:00", "end_time": "16:30", "location": "Kyoto", "score": 0.81, "note": "Keep the afternoon light."},
                                ],
                            },
                            {
                                "title": "2026-04-16 | Arashiyama",
                                "summary": "Scenic finish with fewer transfers.",
                                "total_cost": 1600,
                                "items": [
                                    {"type": "sight", "name": "Arashiyama Bamboo Grove", "start_time": "08:30", "end_time": "10:30", "location": "Kyoto", "score": 0.88, "note": "Arrive early to avoid crowds."},
                                    {"type": "meal", "name": "Riverfront lunch", "start_time": "12:00", "end_time": "13:30", "location": "Kyoto", "score": 0.8, "note": "Stay near the area before departure."},
                                ],
                            },
                        ],
                    }
                )
            raise AssertionError(f"Unexpected agent role: {self.name}")

    class FakeModule:
        SimpleAgent = FakeSimpleAgent

    return FakeModule



def test_trip_generation_and_export_flow(client: TestClient):
    _register(client)
    trip = _create_trip(client)

    generate_response = client.post(f"/api/v1/trips/{trip['id']}/generate")
    assert generate_response.status_code == 200
    job = _wait_for_job(client, generate_response.json()["data"]["job_id"])
    assert job["status"] == "completed"
    assert job["stage"] == "export_ready"
    assert job["progress_percent"] == 100
    assert len(job["timeline_json"]) >= 6

    trip_detail = client.get(f"/api/v1/trips/{trip['id']}")
    assert trip_detail.status_code == 200
    assert trip_detail.json()["data"]["itinerary"]["days"]

    export_response = client.post("/api/v1/exports", json={"trip_id": trip["id"], "formats": ["md", "pdf", "json"]})
    assert export_response.status_code == 200
    export_job = _wait_for_job(client, export_response.json()["data"]["job_id"])
    assert export_job["status"] == "completed"
    assert export_job["stage"] == "export_ready"
    assert export_job["progress_percent"] == 100
    assert export_job["result"]["primary_artifact"] == "pdf"
    assert [artifact["type"] for artifact in export_job["result"]["artifacts"]] == ["md", "pdf", "json"]
    assert Path(export_job["result"]["file_path"]).exists()
    assert export_job["result"]["file_url"].endswith(f"/api/v1/exports/files/{export_job['result']['file_name']}")

    artifact_map = {artifact["type"]: artifact for artifact in export_job["result"]["artifacts"]}

    pdf_response = client.get(urlparse(artifact_map["pdf"]["file_url"]).path)
    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"].startswith("application/pdf")
    assert pdf_response.content.startswith(b"%PDF-")
    assert len(PdfReader(BytesIO(pdf_response.content)).pages) >= 2
    legacy_pdf_path = f"/exports/files/{artifact_map['pdf']['file_name']}"
    assert client.get(legacy_pdf_path).status_code == 200

    markdown_response = client.get(urlparse(artifact_map["md"]["file_url"]).path)
    assert markdown_response.status_code == 200
    assert markdown_response.headers["content-type"].startswith("text/")
    assert "# " in markdown_response.text
    # stay_recommendation rendering is covered by test_export_service.py: the
    # stub generation chain used here does not produce stay data.

    json_response = client.get(urlparse(artifact_map["json"]["file_url"]).path)
    assert json_response.status_code == 200
    assert json_response.headers["content-type"].startswith("application/json")
    assert json_response.json()["job_id"] == export_job["job_id"]

    client.post("/api/v1/auth/logout")
    anonymous_pdf_response = client.get(urlparse(artifact_map["pdf"]["file_url"]).path)
    assert anonymous_pdf_response.status_code == 401
    assert client.get(legacy_pdf_path).status_code == 401



def test_trip_generation_uses_helloagents_provider_when_selected(client: TestClient, monkeypatch):
    import travelmind_api.agents.helloagents as current_helloagents_module

    monkeypatch.setattr(current_helloagents_module, "import_module", lambda _: _fake_helloagents_module())
    monkeypatch.setattr(
        current_helloagents_module.OpenAICompatibleClient,
        "create_chat_completion",
        lambda self, *, messages, temperature=0.2, max_tokens=None: json.dumps(
            {
                "summary": "三天京都行程，已综合景点、天气和住宿策略。",
                "total_budget_estimate": 4700,
                "risks": ["热门景点建议提早出发。"],
                "days": [
                    {
                        "title": "2026-04-14 | 京都东部",
                        "summary": "第一天以寺庙和步行为主。",
                        "total_cost": 1500,
                        "items": [
                            {"type": "sight", "name": "Ginkaku-ji", "start_time": "09:00", "end_time": "11:00", "location": "Kyoto", "score": 0.9, "note": "先从清静景点开始。"},
                            {"type": "meal", "name": "Philosopher's Path coffee stop", "start_time": "12:00", "end_time": "13:30", "location": "Kyoto", "score": 0.82, "note": "中午安排咖啡与简餐。"},
                        ],
                    },
                    {
                        "title": "2026-04-15 | 京都中心",
                        "summary": "第二天安排市场与小吃。",
                        "total_cost": 1600,
                        "items": [
                            {"type": "food", "name": "Nishiki Market brunch", "start_time": "10:00", "end_time": "12:00", "location": "Kyoto", "score": 0.84, "note": "把午前留给市场和小吃。"},
                            {"type": "explore", "name": "Kamo River slow walk", "start_time": "14:00", "end_time": "16:30", "location": "Kyoto", "score": 0.81, "note": "下午轻松散步收尾。"},
                        ],
                    },
                    {
                        "title": "2026-04-16 | 岚山",
                        "summary": "第三天以景观和低转场为主。",
                        "total_cost": 1600,
                        "items": [
                            {"type": "sight", "name": "Arashiyama Bamboo Grove", "start_time": "08:30", "end_time": "10:30", "location": "Kyoto", "score": 0.88, "note": "尽量早到以避开人流。"},
                            {"type": "meal", "name": "Riverfront lunch", "start_time": "12:00", "end_time": "13:30", "location": "Kyoto", "score": 0.8, "note": "午餐后准备返程。"},
                        ],
                    },
                ],
            }
        ),
    )
    _register(client)
    settings_response = client.put(
        "/api/v1/settings/llm",
        json={
            "base_url": "https://api.example.test/v1",
            "api_key": "test-key",
            "model": "gpt-5.4",
            "wire_api": "responses",
            "agent_provider": "helloagents",
        },
    )
    assert settings_response.status_code == 200, settings_response.text

    trip = _create_trip(client)
    generate_response = client.post(f"/api/v1/trips/{trip['id']}/generate")
    assert generate_response.status_code == 200, generate_response.text
    job = _wait_for_job(client, generate_response.json()["data"]["job_id"])
    assert job["status"] == "completed"

    trip_detail = client.get(f"/api/v1/trips/{trip['id']}")
    assert trip_detail.status_code == 200
    detail_payload = trip_detail.json()["data"]
    assert detail_payload["itinerary"]["days"]
    assert detail_payload["itinerary"]["stay_recommendation"]["final_recommended_hotel"]["name"] == "Downtown Kyoto Hotel"
    assert "Downtown Kyoto" in detail_payload["itinerary"]["stay_recommendation"]["recommended_areas"]
    assert detail_payload["latest_agent_trace"]["provider"] == "helloagents-poc"
    assert detail_payload["latest_agent_trace"]["license_notice"]
    agent_run_keys = {run["key"] for run in detail_payload["latest_agent_trace"]["agent_runs"]}
    assert len(detail_payload["latest_agent_trace"]["agent_runs"]) >= 7
    assert detail_payload["latest_agent_trace"]["agent_runs"][1]["key"] in {"attraction_specialist", "poi_specialist", "weather_specialist", "hotel_specialist", "transport_specialist"}
    assert "attraction_image_specialist" in agent_run_keys
    assert "image_curator" not in agent_run_keys
    assert "image_reviewer" not in agent_run_keys
    assert detail_payload["itinerary"]["days"][0]["items"][0]["image_status"] in {"completed", "failed", "pending", "skipped"}
    assert any("business-specialist" in note.lower() for note in detail_payload["latest_agent_trace"]["notes"])



def test_trip_generation_job_fails_when_helloagents_role_fails(client: TestClient, monkeypatch):
    import travelmind_api.agents.helloagents as current_helloagents_module

    monkeypatch.setattr(
        current_helloagents_module,
        "import_module",
        lambda _: _fake_helloagents_module(failing_role="weather_specialist"),
    )
    _register(client)
    settings_response = client.put(
        "/api/v1/settings/llm",
        json={
            "base_url": "https://api.example.test/v1",
            "api_key": "test-key",
            "model": "gpt-5.4",
            "wire_api": "responses",
            "agent_provider": "helloagents",
        },
    )
    assert settings_response.status_code == 200, settings_response.text

    trip = _create_trip(client)
    generate_response = client.post(f"/api/v1/trips/{trip['id']}/generate")
    assert generate_response.status_code == 200, generate_response.text
    job = _wait_for_job(client, generate_response.json()["data"]["job_id"])
    assert job["status"] == "failed"
    assert "weather_specialist" in (job["error_message"] or "")

    trip_detail = client.get(f"/api/v1/trips/{trip['id']}")
    assert trip_detail.status_code == 200
    assert trip_detail.json()["data"]["itinerary"] is None


def test_failed_trip_generation_can_retry_from_failed_helloagents_node(client: TestClient, monkeypatch):
    import travelmind_api.agents.helloagents as current_helloagents_module
    from travelmind_api.agents.helloagents import HelloAgentsOrchestrator

    calls: list[str] = []
    weather_failed_once = {"done": False}

    role_payloads = {
        "brief_parser": {
            "destination": "Kyoto",
            "trip_days": 3,
            "budget_band": "midrange",
            "pace": "balanced",
            "must_have": ["temples", "coffee"],
            "avoid": ["overpacked transfers"],
            "transport": "rail",
            "accommodation": "Quiet boutique hotel",
            "interests": ["temples", "coffee"],
            "planning_constraints": ["keep sequencing realistic"],
        },
        "poi_specialist": {
            "candidate_areas": ["Higashiyama", "Downtown Kyoto"],
            "featured_pois": [
                {"name": "Ginkaku-ji", "area": "Higashiyama", "reason": "Calm morning temple.", "suggested_time": "morning"},
                {"name": "Nishiki Market", "area": "Downtown Kyoto", "reason": "Food focus.", "suggested_time": "midday"},
            ],
            "sequencing_hints": ["Group nearby sights in half-day blocks."],
        },
        "weather_specialist": {
            "overall_outlook": "Cool mornings and mild afternoons.",
            "daily_outlook": ["Day 1: cool.", "Day 2: mild.", "Day 3: comfortable."],
            "packing_notes": ["Carry a light layer."],
            "timing_guidance": ["Outdoor walks fit before late afternoon."],
            "weather_risks": ["Light rain may affect walks."],
        },
        "hotel_specialist": {
            "recommended_areas": ["Downtown Kyoto"],
            "hotel_candidates": [
                {
                    "name": "Downtown Kyoto Hotel",
                    "area": "Downtown Kyoto",
                    "reason": "Balanced access.",
                    "price_hint": "moderate",
                    "source_urls": ["https://hotel.example.test/downtown-kyoto"],
                }
            ],
            "stay_strategy": ["Use one transit-friendly base."],
            "budget_notes": ["Keep hotel spend near target."],
        },
        "transport_specialist": {
            "intercity_options": [
                {
                    "mode": "rail",
                    "route": "Osaka to Kyoto Station",
                    "duration_hint": "about 30 minutes",
                    "price_hint": "moderate",
                    "booking_window": "Reserve during peak periods",
                    "reason": "Fast practical transfer.",
                }
            ],
            "arrival_strategy": ["Align arrival with hotel area."],
            "local_mobility_strategy": ["Use rail or subway first."],
            "pass_or_ticket_notes": ["Use point-to-point tickets."],
            "budget_notes": ["Keep local transport modest."],
            "transport_risks": ["Peak-hour trains may be crowded."],
            "sequencing_constraints": ["Keep departure-day stops near rail."],
            "estimated_intercity_cost": 320,
            "estimated_local_transport_cost": 60,
        },
        "itinerary_planner": {
            "summary": "Three Kyoto days resumed from a failed weather node.",
            "total_budget_estimate": 4700,
            "risks": ["Popular sites may require early arrival."],
            "days": [
                {
                    "title": "Day 1 | East Kyoto",
                    "summary": "Temple-heavy first day.",
                    "total_cost": 1500,
                    "items": [
                        {"type": "sight", "name": "Ginkaku-ji", "start_time": "09:00", "end_time": "11:00", "location": "Kyoto", "score": 0.9, "note": "Start calm."}
                    ],
                },
                {
                    "title": "Day 2 | Central Kyoto",
                    "summary": "Market and river.",
                    "total_cost": 1600,
                    "items": [
                        {"type": "meal", "name": "Nishiki Market", "start_time": "10:00", "end_time": "12:00", "location": "Kyoto", "score": 0.84, "note": "Food crawl."}
                    ],
                },
                {
                    "title": "Day 3 | Arashiyama",
                    "summary": "Scenic finish.",
                    "total_cost": 1600,
                    "items": [
                        {"type": "sight", "name": "Arashiyama Bamboo Grove", "start_time": "08:30", "end_time": "10:30", "location": "Kyoto", "score": 0.88, "note": "Arrive early."}
                    ],
                },
            ],
        },
    }

    def fake_run_role(self, *, module, role_config, llm_config, input_payload):
        role_name = role_config.role_name
        calls.append(role_name)
        if role_name == "weather_specialist" and not weather_failed_once["done"]:
            weather_failed_once["done"] = True
            raise RuntimeError("forced upstream failure for weather_specialist")
        response_payload = dict(role_payloads[role_name])
        if role_name == "weather_specialist":
            trip_request = input_payload["trip_request"]
            first_day = date.fromisoformat(trip_request["start_date"])
            response_payload["daily_forecasts"] = [
                {
                    "date": (first_day + timedelta(days=offset)).isoformat(),
                    "outlook": "Cool to mild with possible light rain.",
                    "timing_advice": "Keep outdoor walks before late afternoon.",
                    "risk": "Forecast confidence may change.",
                }
                for offset in range(int(trip_request["trip_days"]))
            ]
        return json.dumps(response_payload)

    monkeypatch.setattr(current_helloagents_module, "import_module", lambda _: object())
    monkeypatch.setattr(HelloAgentsOrchestrator, "_run_role", fake_run_role)

    _register(client)
    settings_response = client.put(
        "/api/v1/settings/llm",
        json={
            "base_url": "https://api.example.test/v1",
            "api_key": "test-key",
            "model": "gpt-5.4",
            "wire_api": "responses",
            "agent_provider": "helloagents",
        },
    )
    assert settings_response.status_code == 200, settings_response.text

    trip = _create_trip(client)
    generate_response = client.post(f"/api/v1/trips/{trip['id']}/generate")
    assert generate_response.status_code == 200, generate_response.text
    failed_job = _wait_for_job(client, generate_response.json()["data"]["job_id"])
    assert failed_job["status"] == "failed"
    assert failed_job["can_resume"] is True
    assert failed_job["resume_failed_role"] == "weather_specialist"
    assert failed_job["result"]["resume_completed_roles"] == ["brief_parser", "poi_specialist"]

    retry_response = client.post(f"/api/v1/jobs/{failed_job['job_id']}/retry")
    assert retry_response.status_code == 200, retry_response.text
    retry_job = _wait_for_job(client, retry_response.json()["data"]["job_id"])
    assert retry_job["status"] == "completed"

    assert calls.count("brief_parser") == 1
    assert calls.count("poi_specialist") == 1
    assert calls.count("weather_specialist") == 2
    assert calls.count("hotel_specialist") == 1
    assert calls.count("transport_specialist") == 1
    assert calls.count("itinerary_planner") == 1

    trip_detail = client.get(f"/api/v1/trips/{trip['id']}")
    assert trip_detail.status_code == 200
    assert trip_detail.json()["data"]["itinerary"]["summary"] == "Three Kyoto days resumed from a failed weather node."


def test_failed_trip_generation_without_checkpoint_cannot_retry(client: TestClient):
    from travelmind_api.core.database import SessionLocal
    from travelmind_api.services.job_service import create_job, update_job_state

    _register(client)
    trip = _create_trip(client)

    with SessionLocal() as session:
        job = create_job(
            session,
            job_type="trip.generate",
            owner_user_id=trip["user_id"],
            trip_id=trip["id"],
            payload={"trip_id": trip["id"]},
        )
        update_job_state(
            session,
            job.id,
            status="failed",
            stage="route_planning",
            stage_message="Legacy failure without checkpoint.",
            error_message="Legacy failure without checkpoint.",
            set_finished=True,
        )
        session.commit()
        job_id = job.id

    retry_response = client.post(f"/api/v1/jobs/{job_id}/retry")
    assert retry_response.status_code == 409
    assert retry_response.json()["error"]["code"] == "job_resume_checkpoint_missing"
