import json
import time

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
        "destination": "Kyoto",
        "start_date": "2026-04-14",
        "end_date": "2026-04-16",
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



def test_trip_create_list_get_and_update(client: TestClient):
    _register(client)

    create_response = _create_trip(client)
    trip = create_response.json()["data"]
    assert trip["title"] == "Kyoto calm days"
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



def test_trip_create_rejects_invalid_date_range(client: TestClient):
    _register(client)

    response = client.post(
        "/api/v1/trips",
        json={
            "title": "Broken trip",
            "destination": "Kyoto",
            "start_date": "2026-04-16",
            "end_date": "2026-04-14",
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
