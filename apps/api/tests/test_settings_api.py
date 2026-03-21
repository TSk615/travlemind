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
    assert response.status_code == 200, response.text
    return response



def _create_trip(client: TestClient):
    response = client.post(
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
    assert response.status_code == 200, response.text
    return response.json()["data"]



def test_llm_settings_can_be_saved_and_read_back_masked(client: TestClient):
    _register(client)

    initial_response = client.get("/api/v1/settings/llm")
    assert initial_response.status_code == 200
    assert initial_response.json()["data"] == {
        "base_url": None,
        "api_key_masked": None,
        "has_api_key": False,
        "model": None,
        "wire_api": None,
        "configured": False,
    }

    raw_api_key = "sk-travelmind-secret-1234"
    update_response = client.put(
        "/api/v1/settings/llm",
        json={
            "base_url": " https://api.example.com/v1/ ",
            "api_key": raw_api_key,
            "model": "gpt-5.4-mini",
            "wire_api": "responses",
        },
    )
    assert update_response.status_code == 200, update_response.text

    updated = update_response.json()["data"]
    assert updated["base_url"] == "https://api.example.com/v1"
    assert updated["model"] == "gpt-5.4-mini"
    assert updated["wire_api"] == "responses"
    assert updated["configured"] is True
    assert updated["has_api_key"] is True
    assert updated["api_key_masked"].startswith(raw_api_key[:4])
    assert updated["api_key_masked"].endswith(raw_api_key[-4:])
    assert updated["api_key_masked"] != raw_api_key
    assert raw_api_key not in update_response.text

    get_response = client.get("/api/v1/settings/llm")
    assert get_response.status_code == 200
    assert get_response.json()["data"] == updated

    from travelmind_api.core.database import SessionLocal
    from travelmind_api.db.models import User

    with SessionLocal() as session:
        user = session.query(User).filter(User.email == "planner@example.com").one()
        assert user.llm_base_url == "https://api.example.com/v1"
        assert user.llm_api_key == raw_api_key
        assert user.llm_model == "gpt-5.4-mini"
        assert user.llm_wire_api == "responses"



def test_trip_jobs_do_not_persist_llm_secret_snapshots(client: TestClient):
    _register(client)

    raw_config = {
        "base_url": "https://api.gateway.example/v1",
        "api_key": "sk-job-snapshot-5678",
        "model": "gpt-5.4",
        "wire_api": "responses",
    }
    settings_response = client.put("/api/v1/settings/llm", json=raw_config)
    assert settings_response.status_code == 200, settings_response.text

    trip = _create_trip(client)

    generate_response = client.post(f"/api/v1/trips/{trip['id']}/generate")
    assert generate_response.status_code == 200, generate_response.text
    generate_job_id = generate_response.json()["data"]["job_id"]

    refine_response = client.post(
        f"/api/v1/trips/{trip['id']}/refine",
        json={
            "instruction": "Focus more on food.",
            "scope": "full_trip",
            "day_index": None,
        },
    )
    assert refine_response.status_code == 200, refine_response.text
    refine_job_id = refine_response.json()["data"]["job_id"]

    from travelmind_api.core.database import SessionLocal
    from travelmind_api.db.models import JobRecord

    with SessionLocal() as session:
        generate_job = session.query(JobRecord).filter(JobRecord.id == generate_job_id).one()
        refine_job = session.query(JobRecord).filter(JobRecord.id == refine_job_id).one()

        assert "llm_config" not in generate_job.payload_json
        assert "llm_config" not in refine_job.payload_json
        assert refine_job.payload_json["instruction"] == "Focus more on food."
        assert refine_job.payload_json["scope"] == "full_trip"