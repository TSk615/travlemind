from datetime import date, timedelta

from fastapi.testclient import TestClient


def _register(client: TestClient, *, email: str = "planner@example.com", password: str = "supersecure123", name: str = "Planner"):
    response = client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response


def _future_trip_dates(*, start_offset_days: int = 1, duration_days: int = 2) -> tuple[str, str]:
    start_date = date.today() + timedelta(days=start_offset_days)
    end_date = start_date + timedelta(days=duration_days)
    return start_date.isoformat(), end_date.isoformat()


def _create_trip(client: TestClient, **overrides) -> dict:
    start_date, end_date = _future_trip_dates()
    payload = {
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
    }
    payload.update(overrides)
    response = client.post("/api/v1/trips", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _save_itinerary(client: TestClient, trip_id: str, *, summary: str = "A calm Kyoto route.") -> None:
    response = client.put(
        f"/api/v1/trips/{trip_id}/itinerary",
        json={
            "itinerary": {
                "summary": summary,
                "total_budget_estimate": 1200,
                "days": [
                    {
                        "day_index": 1,
                        "title": "Temple morning",
                        "summary": "Start early and keep the afternoon open.",
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
                                "note": "Arrive before the bus groups.",
                            }
                        ],
                    }
                ],
                "risks": [],
            }
        },
    )
    assert response.status_code == 200, response.text


def test_refine_session_persists_conversation_sources_and_reset(client: TestClient):
    _register(client)
    target_trip = _create_trip(client, title="Target Kyoto route")

    initial_response = client.get(f"/api/v1/trips/{target_trip['id']}/refine-session")
    assert initial_response.status_code == 200, initial_response.text
    initial_session = initial_response.json()["data"]
    assert initial_session["trip_id"] == target_trip["id"]
    assert initial_session["messages"] == []
    assert initial_session["uploaded_guides"] == []
    assert initial_session["community_sources"] == []

    message_response = client.post(
        f"/api/v1/trips/{target_trip['id']}/refine-session/messages",
        json={"role": "user", "text": "Remember that I prefer slower mornings."},
    )
    assert message_response.status_code == 200, message_response.text
    assert message_response.json()["data"]["messages"][0]["text"] == "Remember that I prefer slower mornings."

    upload_response = client.post(
        f"/api/v1/trips/{target_trip['id']}/refine-session/uploaded-guides",
        json={
            "title": "Food guide notes",
            "content": "Prefer Nishiki Market snacks, quiet cafes, and dinner reservations near the hotel.",
        },
    )
    assert upload_response.status_code == 200, upload_response.text
    uploaded_guide = upload_response.json()["data"]["uploaded_guides"][0]
    assert uploaded_guide["title"] == "Food guide notes"
    assert uploaded_guide["source_type"] == "manual_text"

    source_trip = _create_trip(client, title="Community Kyoto inspiration")
    _save_itinerary(client, source_trip["id"], summary="A community route with a market morning.")
    post_response = client.post(
        "/api/v1/community/posts",
        json={"trip_id": source_trip["id"], "share_note": "Good for food-first travelers."},
    )
    assert post_response.status_code == 200, post_response.text
    post = post_response.json()["data"]

    attach_response = client.post(
        f"/api/v1/trips/{target_trip['id']}/refine-session/community-sources",
        json={"post_id": post["id"]},
    )
    assert attach_response.status_code == 200, attach_response.text
    attached_source = attach_response.json()["data"]["community_sources"][0]
    assert attached_source["post_id"] == post["id"]
    assert attached_source["itinerary_summary"] == "A community route with a market morning."
    assert attached_source["snapshot"]["itinerary"]["summary"] == "A community route with a market morning."

    remove_upload_response = client.delete(
        f"/api/v1/trips/{target_trip['id']}/refine-session/uploaded-guides/{uploaded_guide['id']}"
    )
    assert remove_upload_response.status_code == 200, remove_upload_response.text
    assert remove_upload_response.json()["data"]["uploaded_guides"] == []

    reset_response = client.delete(f"/api/v1/trips/{target_trip['id']}/refine-session")
    assert reset_response.status_code == 200, reset_response.text

    empty_response = client.get(f"/api/v1/trips/{target_trip['id']}/refine-session")
    assert empty_response.status_code == 200, empty_response.text
    empty_session = empty_response.json()["data"]
    assert empty_session["messages"] == []
    assert empty_session["uploaded_guides"] == []
    assert empty_session["community_sources"] == []
