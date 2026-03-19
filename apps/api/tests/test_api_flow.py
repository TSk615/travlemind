import time
from pathlib import Path

from fastapi.testclient import TestClient


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


def _wait_for_job(client: TestClient, job_id: str) -> dict:
    payload = None
    for _ in range(10):
        response = client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200
        payload = response.json()["data"]
        if payload["status"] in {"completed", "failed"}:
            return payload
        time.sleep(0.1)
    assert payload is not None
    return payload


def test_trip_generation_and_export_flow(client: TestClient):
    _register(client)

    trip_response = client.post(
        "/api/v1/trips",
        json={
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
        },
    )
    assert trip_response.status_code == 200
    trip = trip_response.json()["data"]

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

    export_response = client.post("/api/v1/exports/pdf", json={"trip_id": trip["id"]})
    assert export_response.status_code == 200
    export_job = _wait_for_job(client, export_response.json()["data"]["job_id"])
    assert export_job["status"] == "completed"
    assert export_job["stage"] == "export_ready"
    assert export_job["progress_percent"] == 100
    assert Path(export_job["result"]["file_path"]).exists()
    assert export_job["result"]["file_url"].endswith(f"/exports/files/{export_job['result']['file_name']}")
