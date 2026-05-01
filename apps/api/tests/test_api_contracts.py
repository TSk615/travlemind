import json
import time
from datetime import date, timedelta

from fastapi.testclient import TestClient


def _register(client: TestClient, *, email: str = "planner@example.com", password: str = "supersecure123", name: str = "Planner"):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": name,
            "email": email,
            "password": password,
        },
    )
    assert response.status_code == 200, response.text
    return response



def _login(client: TestClient, *, email: str = "planner@example.com", password: str = "supersecure123"):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )
    assert response.status_code == 200, response.text
    return response



def _create_trip(client: TestClient, **overrides):
    payload = {
        "title": "Kyoto calm days",
        "origin": "Shanghai",
        "destination": "Kyoto",
        "start_date": "2026-05-14",
        "end_date": "2026-05-16",
        "budget": 4800,
        "travelers": 2,
        "interests": ["temples", "coffee"],
        "accommodation_preference": "Quiet boutique hotel",
        "pace": "balanced",
        "transport_mode": "rail",
    }
    payload.update(overrides)
    response = client.post("/api/v1/trips", json=payload)
    assert response.status_code == 200, response.text
    return response



def _wait_for_terminal_job(client: TestClient, job_id: str) -> dict:
    payload = None
    for _ in range(20):
        response = client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200, response.text
        payload = response.json()["data"]
        if payload["status"] in {"completed", "failed"}:
            return payload
        time.sleep(0.05)
    assert payload is not None
    return payload



def test_auth_register_login_me_and_logout(client: TestClient):
    register_response = _register(client)
    register_payload = register_response.json()
    assert register_payload["error"] is None
    assert register_payload["data"]["email"] == "planner@example.com"

    current_user_response = client.get("/api/v1/me")
    assert current_user_response.status_code == 200
    assert current_user_response.json()["data"]["id"] == register_payload["data"]["id"]

    logout_response = client.post("/api/v1/auth/logout")
    assert logout_response.status_code == 200
    assert logout_response.json()["data"] == {"success": True}

    unauthorized_response = client.get("/api/v1/me")
    assert unauthorized_response.status_code == 401
    assert unauthorized_response.json()["error"]["code"] == "not_authenticated"

    login_response = _login(client)
    assert login_response.json()["data"]["id"] == register_payload["data"]["id"]

    refreshed_user_response = client.get("/api/v1/me")
    assert refreshed_user_response.status_code == 200
    assert refreshed_user_response.json()["data"]["email"] == "planner@example.com"


def test_auth_refresh_issues_new_access_cookie_after_access_token_expires(client: TestClient):
    register_response = _register(client)
    user = register_response.json()["data"]

    from travelmind_api.core.config import get_settings
    from travelmind_api.core.security import create_access_token

    settings = get_settings()
    original_minutes = settings.access_token_minutes
    settings.access_token_minutes = -1
    try:
        expired_access_token = create_access_token({"sub": user["id"], "email": user["email"]}, settings)
    finally:
        settings.access_token_minutes = original_minutes

    client.cookies.set(settings.access_cookie_name, expired_access_token, domain="testserver.local", path="/")

    expired_response = client.get("/api/v1/me")
    assert expired_response.status_code == 401
    assert expired_response.json()["error"]["code"] == "invalid_token"

    refresh_response = client.post("/api/v1/auth/refresh")
    assert refresh_response.status_code == 200, refresh_response.text
    assert refresh_response.json()["data"] == {"success": True}
    assert settings.access_cookie_name in refresh_response.headers.get("set-cookie", "")

    recovered_response = client.get("/api/v1/me")
    assert recovered_response.status_code == 200
    assert recovered_response.json()["data"]["id"] == user["id"]


def test_account_xhs_bind_status_and_unbind(client: TestClient, monkeypatch):
    _register(client)
    monkeypatch.setenv("TRAVELMIND_XHS_CRAWLER_ENABLED", "true")
    monkeypatch.setenv("TRAVELMIND_XHS_CRAWLER_BASE_URL", "https://crawler.example.test")

    import travelmind_api.services.xhs_crawler as crawler_service

    monkeypatch.setattr(
        crawler_service.XhsCrawlerClient,
        "start_binding",
        lambda self, *, user_id: crawler_service.XhsCrawlerBindingState(
            bind_id="xhb_test",
            status="pending",
            verification_url="https://example.test/xhs/bind",
            verification_code="123456",
            qr_image_data_url="data:image/png;base64,abcd",
            expires_at="2026-04-20T10:00:00Z",
        ),
    )
    monkeypatch.setattr(
        crawler_service.XhsCrawlerClient,
        "get_binding",
        lambda self, *, bind_id: crawler_service.XhsCrawlerBindingState(
            bind_id=bind_id,
            status="authorized",
            completed_at="2026-04-20T09:05:00Z",
            display_name="Traveler A",
            xhs_user_id="xhs_user_1",
            session_payload={"cookies": [{"name": "a", "value": "b"}]},
            session_expires_at="2099-04-30T10:00:00Z",
        ),
    )
    monkeypatch.setattr(crawler_service.XhsCrawlerClient, "delete_session", lambda self, *, user_id: None)

    start_response = client.post("/api/v1/account/xhs/bind")
    assert start_response.status_code == 200, start_response.text
    assert start_response.json()["data"]["status"] == "pending"
    assert start_response.json()["data"]["bind_id"] == "xhb_test"

    status_response = client.get("/api/v1/account/xhs/status")
    assert status_response.status_code == 200, status_response.text
    assert status_response.json()["data"]["xhs_bound"] is False
    assert status_response.json()["data"]["active_binding"]["bind_id"] == "xhb_test"

    poll_response = client.get("/api/v1/account/xhs/bind/xhb_test")
    assert poll_response.status_code == 200, poll_response.text
    assert poll_response.json()["data"]["status"] == "authorized"

    bound_status_response = client.get("/api/v1/account/xhs/status")
    assert bound_status_response.status_code == 200, bound_status_response.text
    assert bound_status_response.json()["data"]["xhs_bound"] is True
    assert bound_status_response.json()["data"]["xhs_display_name"] == "Traveler A"

    delete_response = client.delete("/api/v1/account/xhs/bind")
    assert delete_response.status_code == 200, delete_response.text
    assert delete_response.json()["data"]["xhs_bound"] is False
    assert delete_response.json()["data"]["xhs_binding_required"] is True



def test_trip_create_list_get_and_update(client: TestClient):
    _register(client)

    create_response = _create_trip(client)
    trip = create_response.json()["data"]
    assert trip["title"] == "Kyoto calm days"
    assert trip["origin"] == "Shanghai"
    assert trip["destination"] == "Kyoto"

    list_response = client.get("/api/v1/trips")
    assert list_response.status_code == 200
    trips = list_response.json()["data"]
    assert len(trips) == 1
    assert trips[0]["id"] == trip["id"]

    detail_response = client.get(f"/api/v1/trips/{trip['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["id"] == trip["id"]

    update_response = client.patch(
        f"/api/v1/trips/{trip['id']}",
        json={
            "title": "Kyoto temple sprint",
            "budget": 5200,
            "interests": ["temples", "coffee", "coffee", "  "],
        },
    )
    assert update_response.status_code == 200
    updated_trip = update_response.json()["data"]
    assert updated_trip["title"] == "Kyoto temple sprint"
    assert updated_trip["budget"] == 5200
    assert updated_trip["interests"] == ["temples", "coffee"]



def test_trip_create_auto_generates_title_when_missing(client: TestClient):
    _register(client)

    response = client.post(
        "/api/v1/trips",
        json={
            "title": "",
            "origin": "Shanghai",
            "destination": "Kyoto",
            "start_date": (date.today() + timedelta(days=1)).isoformat(),
            "end_date": (date.today() + timedelta(days=3)).isoformat(),
            "budget": 4800,
            "travelers": 2,
            "interests": ["temples", "coffee"],
            "accommodation_preference": "Quiet boutique hotel",
            "pace": "balanced",
            "transport_mode": "rail",
        },
    )

    assert response.status_code == 200, response.text
    trip = response.json()["data"]
    assert trip["title"]
    assert "Kyoto" in trip["title"] or "??" in trip["title"]




def test_trip_create_requires_explicit_generate_step(client: TestClient):
    _register(client)

    create_response = _create_trip(client)
    trip = create_response.json()["data"]
    assert trip["itinerary"] is None
    assert trip["latest_agent_trace"] is None

    detail_response = client.get(f"/api/v1/trips/{trip['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["itinerary"] is None
    assert detail_response.json()["data"]["latest_agent_trace"] is None

    generate_response = client.post(f"/api/v1/trips/{trip['id']}/generate")
    assert generate_response.status_code == 200
    job = generate_response.json()["data"]
    assert job["type"] == "trip.generate"
    assert job["status"] == "queued"
    assert job["stage"] == "queued"
    assert job["progress_percent"] == 0


def test_trip_create_rejects_invalid_date_range(client: TestClient):
    _register(client)
    future_start = (date.today() + timedelta(days=5)).isoformat()
    future_end = (date.today() + timedelta(days=3)).isoformat()

    response = client.post(
        "/api/v1/trips",
        json={
            "title": "Broken trip",
            "origin": "Shanghai",
            "destination": "Kyoto",
            "start_date": future_start,
            "end_date": future_end,
            "budget": 3000,
            "travelers": 1,
            "interests": [],
            "accommodation_preference": "",
            "pace": "balanced",
            "transport_mode": "rail",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_trip_dates"


def test_trip_create_rejects_start_date_before_today(client: TestClient):
    _register(client)

    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()

    response = client.post(
        "/api/v1/trips",
        json={
            "title": "Past start date",
            "origin": "Shanghai",
            "destination": "Kyoto",
            "start_date": yesterday,
            "end_date": tomorrow,
            "budget": 3000,
            "travelers": 1,
            "interests": [],
            "accommodation_preference": "",
            "pace": "balanced",
            "transport_mode": "rail",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_trip_start_date"



def test_search_endpoint_returns_expected_structure(client: TestClient):
    _register(client)

    response = client.post(
        "/api/v1/search",
        json={
            "query": "quiet coffee",
            "destination": "Kyoto",
            "manual_links": [
                "https://example.com/custom-guide",
                "https://example.com/custom-guide",
                "not-a-url",
                "   ",
            ],
        },
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["error"] is None
    documents = payload["data"]
    assert len(documents) >= 2

    first_document = documents[0]
    assert set(first_document) >= {"id", "platform", "title", "url", "summary", "destination", "scores"}
    assert set(first_document["scores"]) >= {
        "trust_score",
        "quality_score",
        "freshness_score",
        "ad_score",
        "final_score",
        "reasons",
    }

    manual_documents = [document for document in documents if document["platform"] == "manual-link"]
    assert len(manual_documents) == 1
    assert manual_documents[0]["url"] == "https://example.com/custom-guide"



def test_search_endpoint_passes_user_xhs_toggle_to_search_service(client: TestClient, monkeypatch):
    _register(client)
    settings_response = client.put(
        "/api/v1/settings/llm",
        json={
            "base_url": "https://api.example.com/v1",
            "model": "gpt-5.4",
            "wire_api": "responses",
            "agent_provider": "standard",
            "xhs_source_enabled": True,
        },
    )
    assert settings_response.status_code == 200, settings_response.text

    import travelmind_api.api.routes.search as search_route

    captured: dict[str, object] = {}

    def fake_search_documents(
        query,
        destination,
        manual_links,
        *,
        interests=None,
        social_context="general",
        search_service_config=None,
        xhs_source_enabled=True,
        xhs_user_id=None,
    ):
        captured["query"] = query
        captured["destination"] = destination
        captured["manual_links"] = manual_links
        captured["interests"] = interests
        captured["social_context"] = social_context
        captured["search_service_config"] = search_service_config
        captured["xhs_source_enabled"] = xhs_source_enabled
        captured["xhs_user_id"] = xhs_user_id
        return []

    monkeypatch.setattr(search_route, "search_documents", fake_search_documents)

    response = client.post(
        "/api/v1/search",
        json={
            "query": "quiet coffee",
            "destination": "Kyoto",
            "manual_links": [],
            "interests": ["coffee"],
        },
    )
    assert response.status_code == 200, response.text
    assert captured["xhs_source_enabled"] is True
    assert captured["xhs_user_id"]




def test_job_detail_and_stream_return_consistent_structure(client: TestClient):
    _register(client)
    trip = _create_trip(client).json()["data"]

    generate_response = client.post(f"/api/v1/trips/{trip['id']}/generate")
    assert generate_response.status_code == 200
    job_id = generate_response.json()["data"]["job_id"]

    detail_response = client.get(f"/api/v1/jobs/{job_id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["error"] is None
    assert detail_payload["data"]["job_id"] == job_id
    assert detail_payload["data"]["type"] == "trip.generate"
    assert set(detail_payload["data"]) >= {
        "job_id",
        "status",
        "type",
        "trip_id",
        "created_at",
        "updated_at",
        "stage",
        "stage_message",
        "progress_percent",
        "timeline_json",
        "result",
        "error_message",
    }
    assert isinstance(detail_payload["data"]["timeline_json"], list)
    assert detail_payload["data"]["timeline_json"]

    with client.stream("GET", f"/api/v1/jobs/{job_id}/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    data_lines = [line for line in body.splitlines() if line.startswith("data: ")]
    assert data_lines
    stream_payload = json.loads(data_lines[-1][6:])
    assert stream_payload["meta"] == {"stream": True}
    assert set(stream_payload["data"]) == set(detail_payload["data"])
    assert stream_payload["data"]["job_id"] == job_id
    assert stream_payload["data"]["status"] in {"queued", "running", "completed", "failed"}
    assert isinstance(stream_payload["data"]["timeline_json"], list)
    assert stream_payload["data"]["timeline_json"][-1]["status"] == stream_payload["data"]["status"]



def test_refine_endpoint_updates_trip_and_trace(client: TestClient):
    _register(client)
    trip = _create_trip(client).json()["data"]

    refine_response = client.post(
        f"/api/v1/trips/{trip['id']}/refine",
        json={
            "instruction": "Make day 2 quieter and slower.",
            "scope": "day_plan",
            "day_index": 2,
        },
    )
    assert refine_response.status_code == 200
    refine_job = refine_response.json()["data"]
    assert refine_job["type"] == "trip.refine"
    assert refine_job["stage"] == "queued"
    assert refine_job["progress_percent"] == 0
    assert refine_job["timeline_json"][0]["status"] == "queued"

    final_job = _wait_for_terminal_job(client, refine_job["job_id"])
    assert final_job["status"] == "completed"
    assert final_job["stage"] == "export_ready"
    assert final_job["result"]["instruction"] == "Make day 2 quieter and slower."
    assert final_job["result"]["scope"] == "day_plan"
    assert final_job["result"]["day_index"] == 2

    trip_detail = client.get(f"/api/v1/trips/{trip['id']}")
    assert trip_detail.status_code == 200
    detail_payload = trip_detail.json()["data"]
    assert detail_payload["itinerary"] is not None
    assert "Refined day 2" in detail_payload["itinerary"]["summary"]
    assert any(note == "Refine scope: day_plan." for note in detail_payload["latest_agent_trace"]["notes"])


def test_image_enrich_endpoint_queues_followup_job(client: TestClient):
    _register(client)
    trip = _create_trip(client).json()["data"]

    generate_response = client.post(f"/api/v1/trips/{trip['id']}/generate")
    assert generate_response.status_code == 200
    _wait_for_terminal_job(client, generate_response.json()["data"]["job_id"])

    enrich_response = client.post(f"/api/v1/trips/{trip['id']}/images/enrich")
    assert enrich_response.status_code == 200, enrich_response.text
    enrich_job = enrich_response.json()["data"]
    assert enrich_job["type"] == "trip.image_enrich"
    assert enrich_job["stage"] == "queued"
    assert enrich_job["progress_percent"] == 0
    assert enrich_job["timeline_json"][0]["status"] == "queued"






def test_trip_intake_chat_returns_backend_guidance(client: TestClient, monkeypatch):
    _register(client)

    import travelmind_api.api.routes.trips as trips_route

    monkeypatch.setattr(
        trips_route,
        "run_trip_intake_chat",
        lambda **kwargs: {
            "assistant_message": "What is the destination?",
            "draft": {
                "title": "",
                "origin": "Shanghai",
                "destination": "",
                "start_date": "",
                "end_date": "",
                "budget": 0,
                "travelers": 0,
                "interests": [],
                "accommodation_preference": "",
                "pace": "",
                "transport_mode": "",
            },
            "missing_required_fields": ["destination", "start_date"],
            "ready_to_create": False,
        },
    )

    response = client.post(
        "/api/v1/trips/intake/chat",
        json={
            "draft": {
                "title": "",
                "origin": "Shanghai",
                "destination": "",
                "start_date": "",
                "end_date": "",
                "budget": 0,
                "travelers": 0,
                "interests": [],
                "accommodation_preference": "",
                "pace": "",
                "transport_mode": "",
            },
            "messages": [{"role": "assistant", "text": "Where are you departing from?"}],
            "user_message": "I will depart from Shanghai.",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["assistant_message"] == "What is the destination?"
    assert payload["draft"]["origin"] == "Shanghai"
    assert payload["missing_required_fields"] == ["destination", "start_date"]
    assert payload["ready_to_create"] is False

def test_trip_delete_removes_trip_and_related_jobs(client: TestClient):
    _register(client)
    trip = _create_trip(client).json()["data"]

    generate_response = client.post(f"/api/v1/trips/{trip['id']}/generate")
    assert generate_response.status_code == 200, generate_response.text
    job_id = generate_response.json()["data"]["job_id"]

    delete_response = client.delete(f"/api/v1/trips/{trip['id']}")
    assert delete_response.status_code == 200, delete_response.text
    assert delete_response.json()["data"] == {"success": True, "trip_id": trip["id"]}

    detail_response = client.get(f"/api/v1/trips/{trip['id']}")
    assert detail_response.status_code == 404
    assert detail_response.json()["error"]["code"] == "trip_not_found"

    list_response = client.get("/api/v1/trips")
    assert list_response.status_code == 200
    assert list_response.json()["data"] == []

    job_response = client.get(f"/api/v1/jobs/{job_id}")
    assert job_response.status_code == 404
    assert job_response.json()["error"]["code"] == "job_not_found"
