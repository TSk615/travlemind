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
