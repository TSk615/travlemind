from datetime import date, timedelta

from fastapi.testclient import TestClient


def _register(
    client: TestClient,
    *,
    email: str,
    password: str = "supersecure123",
    name: str = "Planner",
):
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


def _login(client: TestClient, *, email: str, password: str = "supersecure123"):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )
    assert response.status_code == 200, response.text
    return response


def _create_trip(client: TestClient, *, title: str = "Kyoto calm days") -> dict:
    start_date = (date.today() + timedelta(days=7)).isoformat()
    end_date = (date.today() + timedelta(days=9)).isoformat()
    response = client.post(
        "/api/v1/trips",
        json={
            "title": title,
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
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _save_itinerary(client: TestClient, trip_id: str, *, title: str = "Kyoto calm days", budget: float = 4800) -> dict:
    response = client.put(
        f"/api/v1/trips/{trip_id}/itinerary",
        json={
            "itinerary": {
                "summary": "A calm Kyoto route with temple mornings and coffee afternoons.",
                "total_budget_estimate": budget,
                "days": [
                    {
                        "day_index": 1,
                        "title": "East Kyoto slow day",
                        "summary": "Early temple visits followed by a quiet cafe stop.",
                        "total_cost": budget / 2,
                        "items": [
                            {
                                "id": "item_1",
                                "type": "sight",
                                "name": title,
                                "start_time": "09:00",
                                "end_time": "11:00",
                                "location": "Kyoto",
                                "score": 0.92,
                                "note": "Go early for a quieter entry window.",
                                "image_urls": ["https://example.com/community-cover.png"],
                            }
                        ],
                    }
                ],
                "risks": ["Reserve peak attractions in advance."],
            },
            "latest_agent_trace": {
                "provider": "stub",
                "workflow_id": "wf_test_community",
                "notes": [],
                "agent_runs": [],
                "grounding_documents": [],
                "transport_guidance": None,
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_community_requires_authentication(client: TestClient):
    response = client.get("/api/v1/community/posts")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_community_publish_snapshot_and_refresh_flow(client: TestClient):
    _register(client, email="community@example.com")
    trip = _create_trip(client)

    missing_itinerary = client.post(
        "/api/v1/community/posts",
        json={"trip_id": trip["id"], "share_note": "Helpful starter guide"},
    )
    assert missing_itinerary.status_code == 400
    assert missing_itinerary.json()["error"]["code"] == "trip_itinerary_required"

    _save_itinerary(client, trip["id"], title=trip["title"], budget=trip["budget"])

    create_response = client.post(
        "/api/v1/community/posts",
        json={"trip_id": trip["id"], "share_note": "Best for a relaxed first Kyoto visit."},
    )
    assert create_response.status_code == 200, create_response.text
    created = create_response.json()["data"]
    assert created["share_note"] == "Best for a relaxed first Kyoto visit."
    assert created["snapshot"]["title"] == trip["title"]
    assert created["snapshot"]["itinerary"]["summary"]
    assert created["snapshot"]["latest_agent_trace"]["provider"] == "stub"

    duplicate_response = client.post(
        "/api/v1/community/posts",
        json={"trip_id": trip["id"], "share_note": "Duplicate publish"},
    )
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["error"]["code"] == "community_post_exists"

    trip_detail = client.get(f"/api/v1/trips/{trip['id']}")
    assert trip_detail.status_code == 200
    assert trip_detail.json()["data"]["community_post"]["is_stale"] is False

    feed_response = client.get("/api/v1/community/posts")
    assert feed_response.status_code == 200
    feed = feed_response.json()["data"]
    assert len(feed) == 1
    assert feed[0]["id"] == created["id"]
    assert feed[0]["itinerary_summary"] == created["snapshot"]["itinerary"]["summary"]

    update_trip = client.patch(
        f"/api/v1/trips/{trip['id']}",
        json={
            "title": "Kyoto calm days refreshed",
            "budget": 5300,
        },
    )
    assert update_trip.status_code == 200, update_trip.text

    stale_trip_detail = client.get(f"/api/v1/trips/{trip['id']}")
    assert stale_trip_detail.status_code == 200
    assert stale_trip_detail.json()["data"]["community_post"]["is_stale"] is True

    detail_before_refresh = client.get(f"/api/v1/community/posts/{created['id']}")
    assert detail_before_refresh.status_code == 200
    assert detail_before_refresh.json()["data"]["snapshot"]["title"] == trip["title"]
    assert detail_before_refresh.json()["data"]["snapshot"]["budget"] == trip["budget"]

    refresh_response = client.post(f"/api/v1/community/posts/{created['id']}/refresh-from-trip", json={})
    assert refresh_response.status_code == 200, refresh_response.text
    refreshed = refresh_response.json()["data"]
    assert refreshed["snapshot"]["title"] == "Kyoto calm days refreshed"
    assert refreshed["snapshot"]["budget"] == 5300
    assert refreshed["share_note"] == "Best for a relaxed first Kyoto visit."
    assert refreshed["snapshot"]["latest_agent_trace"]["provider"] == "stub"

    patch_response = client.patch(
        f"/api/v1/community/posts/{created['id']}",
        json={"share_note": "Updated note after the route refresh."},
    )
    assert patch_response.status_code == 200, patch_response.text
    assert patch_response.json()["data"]["share_note"] == "Updated note after the route refresh."

    fresh_trip_detail = client.get(f"/api/v1/trips/{trip['id']}")
    assert fresh_trip_detail.status_code == 200
    assert fresh_trip_detail.json()["data"]["community_post"]["is_stale"] is False


def test_community_post_ownership_and_delete_flow(client: TestClient):
    _register(client, email="author@example.com", name="Author")
    trip = _create_trip(client, title="Kyoto author guide")
    _save_itinerary(client, trip["id"], title=trip["title"], budget=trip["budget"])

    create_response = client.post(
        "/api/v1/community/posts",
        json={"trip_id": trip["id"], "share_note": "Author note"},
    )
    assert create_response.status_code == 200, create_response.text
    post_id = create_response.json()["data"]["id"]

    logout_response = client.post("/api/v1/auth/logout")
    assert logout_response.status_code == 200, logout_response.text

    _register(client, email="viewer@example.com", name="Viewer")

    unauthorized_patch = client.patch(
        f"/api/v1/community/posts/{post_id}",
        json={"share_note": "Not allowed"},
    )
    assert unauthorized_patch.status_code == 404
    assert unauthorized_patch.json()["error"]["code"] == "community_post_not_found"

    unauthorized_delete = client.delete(f"/api/v1/community/posts/{post_id}")
    assert unauthorized_delete.status_code == 404
    assert unauthorized_delete.json()["error"]["code"] == "community_post_not_found"

    _login(client, email="author@example.com")

    delete_response = client.delete(f"/api/v1/community/posts/{post_id}")
    assert delete_response.status_code == 200, delete_response.text
    assert delete_response.json()["data"] == {"success": True, "post_id": post_id}

    feed_response = client.get("/api/v1/community/posts")
    assert feed_response.status_code == 200
    assert feed_response.json()["data"] == []

    trip_detail = client.get(f"/api/v1/trips/{trip['id']}")
    assert trip_detail.status_code == 200
    assert trip_detail.json()["data"]["community_post"] is None
