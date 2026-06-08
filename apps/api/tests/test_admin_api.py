from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient


def _register(client: TestClient, *, email: str, password: str = "supersecure123", name: str = "User") -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _login(client: TestClient, *, email: str, password: str = "supersecure123") -> dict:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _logout(client: TestClient) -> None:
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 200, response.text


def _set_admin_emails(value: str) -> None:
    from travelmind_api.core.config import get_settings

    get_settings().admin_emails = value


def _create_trip(client: TestClient, **overrides) -> dict:
    start_date = date.today() + timedelta(days=1)
    payload = {
        "title": "Kyoto calm days",
        "origin": "Shanghai",
        "destination": "Kyoto",
        "start_date": start_date.isoformat(),
        "end_date": (start_date + timedelta(days=2)).isoformat(),
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
    return response.json()["data"]


def _save_itinerary(client: TestClient, trip_id: str) -> None:
    response = client.put(
        f"/api/v1/trips/{trip_id}/itinerary",
        json={
            "itinerary": {
                "summary": "A calm Kyoto route.",
                "total_budget_estimate": 1200,
                "days": [
                    {
                        "day_index": 1,
                        "title": "Temple morning",
                        "summary": "Start early.",
                        "total_cost": 1200,
                        "items": [
                            {
                                "id": "item_1",
                                "type": "sight",
                                "name": "Kiyomizu-dera",
                                "start_time": "09:00",
                                "end_time": "11:00",
                                "location": "Kyoto",
                                "score": 0.91,
                                "note": "Arrive before the crowds.",
                            }
                        ],
                    }
                ],
                "risks": [],
            }
        },
    )
    assert response.status_code == 200, response.text


def test_admin_me_and_access_control(client: TestClient):
    _set_admin_emails("admin@example.com")

    admin = _register(client, email="admin@example.com", name="Admin")
    assert admin["is_admin"] is True
    me_response = client.get("/api/v1/me")
    assert me_response.status_code == 200
    assert me_response.json()["data"]["is_admin"] is True

    users_response = client.get("/api/v1/admin/users")
    assert users_response.status_code == 200
    assert users_response.json()["data"]["total"] == 1

    _logout(client)
    _register(client, email="regular@example.com", name="Regular")
    forbidden_response = client.get("/api/v1/admin/users")
    assert forbidden_response.status_code == 403
    assert forbidden_response.json()["error"]["code"] == "admin_forbidden"


def test_admin_disable_enable_user_revokes_sessions_and_audits(client: TestClient):
    _set_admin_emails("admin@example.com")
    admin = _register(client, email="admin@example.com", name="Admin")
    _logout(client)
    user = _register(client, email="traveler@example.com", name="Traveler")

    protected_response = client.get("/api/v1/trips")
    assert protected_response.status_code == 200
    _logout(client)
    _login(client, email=admin["email"])

    self_disable_response = client.post(f"/api/v1/admin/users/{admin['id']}/disable", json={"reason": "testing self lock"})
    assert self_disable_response.status_code == 409
    assert self_disable_response.json()["error"]["code"] == "cannot_disable_self"

    disable_response = client.post(f"/api/v1/admin/users/{user['id']}/disable", json={"reason": "abuse report"})
    assert disable_response.status_code == 200, disable_response.text
    assert disable_response.json()["data"]["disabled_at"]
    assert disable_response.json()["data"]["disabled_reason"] == "abuse report"

    _logout(client)
    login_response = client.post("/api/v1/auth/login", json={"email": user["email"], "password": "supersecure123"})
    assert login_response.status_code == 403
    assert login_response.json()["error"]["code"] == "user_disabled"

    _login(client, email=admin["email"])
    enable_response = client.post(f"/api/v1/admin/users/{user['id']}/enable", json={"reason": "appeal accepted"})
    assert enable_response.status_code == 200, enable_response.text
    assert enable_response.json()["data"]["disabled_at"] is None

    from travelmind_api.core.database import SessionLocal
    from travelmind_api.db.models import AdminAuditLog

    with SessionLocal() as session:
        actions = [row.action for row in session.query(AdminAuditLog).order_by(AdminAuditLog.created_at).all()]
    assert actions == ["user.disable", "user.enable"]


def test_admin_lists_details_and_delete_trip_with_related_records(client: TestClient):
    _set_admin_emails("admin@example.com")
    admin = _register(client, email="admin@example.com", name="Admin")
    _logout(client)
    _register(client, email="traveler@example.com", name="Traveler")
    trip = _create_trip(client, destination="Kyoto")
    _save_itinerary(client, trip["id"])
    post_response = client.post("/api/v1/community/posts", json={"trip_id": trip["id"], "share_note": "Quiet route"})
    assert post_response.status_code == 200, post_response.text
    post_id = post_response.json()["data"]["id"]
    job_response = client.post(f"/api/v1/trips/{trip['id']}/generate")
    assert job_response.status_code == 200, job_response.text
    job_id = job_response.json()["data"]["job_id"]

    _logout(client)
    _login(client, email=admin["email"])

    trips_response = client.get("/api/v1/admin/trips?query=Kyoto&has_itinerary=true&has_community_post=true")
    assert trips_response.status_code == 200, trips_response.text
    assert trips_response.json()["data"]["total"] == 1
    assert trips_response.json()["data"]["items"][0]["owner"]["email"] == "traveler@example.com"

    detail_response = client.get(f"/api/v1/admin/trips/{trip['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["itinerary"]["summary"]

    jobs_response = client.get(f"/api/v1/admin/jobs?trip_id={trip['id']}")
    assert jobs_response.status_code == 200
    assert job_id in {item["job_id"] for item in jobs_response.json()["data"]["items"]}

    delete_response = client.post(f"/api/v1/admin/trips/{trip['id']}/delete", json={"reason": "duplicate content"})
    assert delete_response.status_code == 200, delete_response.text

    missing_trip_response = client.get(f"/api/v1/admin/trips/{trip['id']}")
    assert missing_trip_response.status_code == 404
    missing_post_response = client.get(f"/api/v1/admin/community/posts/{post_id}")
    assert missing_post_response.status_code == 404

    from travelmind_api.core.database import SessionLocal
    from travelmind_api.db.models import AdminAuditLog, JobRecord

    with SessionLocal() as session:
        assert session.query(JobRecord).filter(JobRecord.id == job_id).one_or_none() is None
        actions = [row.action for row in session.query(AdminAuditLog).all()]
    assert actions == ["trip.delete"]


def test_admin_community_delete_and_job_detail_are_available(client: TestClient):
    _set_admin_emails("admin@example.com")
    admin = _register(client, email="admin@example.com", name="Admin")
    _logout(client)
    _register(client, email="author@example.com", name="Author")
    trip = _create_trip(client, destination="Osaka")
    _save_itinerary(client, trip["id"])
    post_response = client.post("/api/v1/community/posts", json={"trip_id": trip["id"], "share_note": "Food route"})
    assert post_response.status_code == 200, post_response.text
    post_id = post_response.json()["data"]["id"]
    job_response = client.post(f"/api/v1/trips/{trip['id']}/generate")
    assert job_response.status_code == 200, job_response.text
    job_id = job_response.json()["data"]["job_id"]

    _logout(client)
    _login(client, email=admin["email"])

    posts_response = client.get("/api/v1/admin/community/posts?query=Osaka")
    assert posts_response.status_code == 200
    assert posts_response.json()["data"]["total"] == 1

    job_detail_response = client.get(f"/api/v1/admin/jobs/{job_id}")
    assert job_detail_response.status_code == 200
    assert job_detail_response.json()["data"]["payload"]
    assert "timeline_json" in job_detail_response.json()["data"]

    delete_response = client.post(f"/api/v1/admin/community/posts/{post_id}/delete", json={"reason": "moderation"})
    assert delete_response.status_code == 200, delete_response.text

    from travelmind_api.core.database import SessionLocal
    from travelmind_api.db.models import AdminAuditLog

    with SessionLocal() as session:
        actions = [row.action for row in session.query(AdminAuditLog).all()]
    assert actions == ["community_post.delete"]
