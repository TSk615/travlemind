from fastapi.testclient import TestClient



from datetime import date, timedelta


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



def _future_trip_dates(*, start_offset_days: int = 1, duration_days: int = 2) -> tuple[str, str]:
    start_date = date.today() + timedelta(days=start_offset_days)
    end_date = start_date + timedelta(days=duration_days)
    return start_date.isoformat(), end_date.isoformat()


def _create_trip(client: TestClient):
    start_date, end_date = _future_trip_dates()
    response = client.post(
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
    assert response.status_code == 200, response.text
    return response.json()["data"]



def test_llm_settings_can_be_saved_and_read_back_masked(client: TestClient):
    _register(client)

    initial_response = client.get("/api/v1/settings/llm")
    assert initial_response.status_code == 200
    assert initial_response.json()["data"] == {
        "agent": {
            "provider_protocol": "openai",
            "base_url": None,
            "api_key_masked": None,
            "has_api_key": False,
            "model": None,
            "wire_api": None,
            "agent_provider": "standard",
            "configured": False,
            "poi_provider_protocol": "openai",
            "poi_base_url": None,
            "poi_api_key_masked": None,
            "poi_has_api_key": False,
            "poi_model": None,
            "weather_model": None,
            "hotel_model": None,
            "transport_model": None,
            "poi_wire_api": None,
            "poi_configured": False,
        },
        "search": {
            "provider": "groksearch",
            "transport": "mcp",
            "base_url": None,
            "api_key_masked": None,
            "has_api_key": False,
            "timeout_seconds": 30.0,
            "xhs_source_enabled": False,
            "configured": False,
        },
        "image": {
            "base_url": None,
            "api_key_masked": None,
            "has_api_key": False,
            "model": None,
            "provider": "openai_compatible",
            "configured": False,
        },
    }

    raw_api_key = "sk-travelmind-secret-1234"
    raw_search_key = "search-secret-5678"
    update_response = client.put(
        "/api/v1/settings/llm",
        json={
            "agent": {
                "provider_protocol": "newapi",
                "base_url": " https://api.example.com/v1/ ",
                "api_key": raw_api_key,
                "model": "gpt-5.4-mini",
                "wire_api": "chat_completions",
                "agent_provider": "helloagents",
                "poi_provider_protocol": "newapi",
                "poi_base_url": " https://poi.example.com/v1/ ",
                "poi_api_key": "poi-secret-4321",
                "poi_model": "Console/grok-4.20-multi-agent-0309",
                "weather_model": "Console/grok-4.20-0309-non-reasoning",
                "hotel_model": "Console/grok-4.20-0309-reasoning",
                "transport_model": "Console/grok-4.20-0309-reasoning",
                "poi_wire_api": "responses",
            },
            "search": {
                "provider": "groksearch",
                "transport": "mcp",
                "base_url": " https://search.example.com/mcp ",
                "api_key": raw_search_key,
                "timeout_seconds": 45,
                "xhs_source_enabled": True,
            },
            "image": {
                "base_url": " https://images.example.com/v1 ",
                "api_key": "img-secret-9012",
                "model": "gpt-image-1",
                "provider": "openai_compatible",
            },
        },
    )
    assert update_response.status_code == 200, update_response.text

    updated = update_response.json()["data"]
    assert updated["agent"]["base_url"] == "https://api.example.com/v1"
    assert updated["agent"]["provider_protocol"] == "newapi"
    assert updated["agent"]["model"] == "gpt-5.4-mini"
    assert updated["agent"]["wire_api"] == "chat_completions"
    assert updated["agent"]["agent_provider"] == "helloagents"
    assert updated["agent"]["configured"] is True
    assert updated["agent"]["has_api_key"] is True
    assert updated["agent"]["api_key_masked"].startswith(raw_api_key[:4])
    assert updated["agent"]["api_key_masked"].endswith(raw_api_key[-4:])
    assert updated["agent"]["api_key_masked"] != raw_api_key
    assert updated["agent"]["poi_provider_protocol"] == "newapi"
    assert updated["agent"]["poi_base_url"] == "https://poi.example.com/v1"
    assert updated["agent"]["poi_model"] == "Console/grok-4.20-multi-agent-0309"
    assert updated["agent"]["weather_model"] == "Console/grok-4.20-0309-non-reasoning"
    assert updated["agent"]["hotel_model"] == "Console/grok-4.20-0309-reasoning"
    assert updated["agent"]["transport_model"] == "Console/grok-4.20-0309-reasoning"
    assert updated["agent"]["poi_wire_api"] == "responses"
    assert updated["agent"]["poi_has_api_key"] is True
    assert updated["agent"]["poi_configured"] is True
    assert updated["agent"]["poi_api_key_masked"].startswith("poi-")
    assert updated["search"]["provider"] == "groksearch"
    assert updated["search"]["transport"] == "mcp"
    assert updated["search"]["base_url"] == "https://search.example.com/mcp"
    assert updated["search"]["timeout_seconds"] == 45.0
    assert updated["search"]["xhs_source_enabled"] is True
    assert updated["search"]["configured"] is True
    assert updated["search"]["has_api_key"] is True
    assert updated["search"]["api_key_masked"].startswith(raw_search_key[:4])
    assert updated["search"]["api_key_masked"].endswith(raw_search_key[-4:])
    assert updated["image"]["base_url"] == "https://images.example.com/v1"
    assert updated["image"]["model"] == "gpt-image-1"
    assert updated["image"]["provider"] == "openai_compatible"
    assert updated["image"]["configured"] is True
    assert updated["image"]["has_api_key"] is True
    assert raw_api_key not in update_response.text
    assert raw_search_key not in update_response.text

    get_response = client.get("/api/v1/settings/llm")
    assert get_response.status_code == 200
    assert get_response.json()["data"] == updated

    from travelmind_api.core.database import SessionLocal
    from travelmind_api.core.database import engine
    from travelmind_api.core.credentials import ENCRYPTED_CREDENTIAL_PREFIX
    from travelmind_api.db.models import User

    with engine.connect() as connection:
        stored = connection.exec_driver_sql(
            "SELECT llm_api_key, poi_llm_api_key, search_service_api_key, image_api_key FROM users WHERE email = ?",
            ("planner@example.com",),
        ).mappings().one()
    assert all(value.startswith(ENCRYPTED_CREDENTIAL_PREFIX) for value in stored.values())
    assert raw_api_key not in stored["llm_api_key"]
    assert raw_search_key not in stored["search_service_api_key"]

    with SessionLocal() as session:
        user = session.query(User).filter(User.email == "planner@example.com").one()
        assert user.llm_base_url == "https://api.example.com/v1"
        assert user.llm_api_key == raw_api_key
        assert user.llm_model == "gpt-5.4-mini"
        assert user.llm_wire_api == "chat_completions"
        assert user.llm_provider_protocol == "newapi"
        assert user.llm_agent_provider == "helloagents"
        assert user.poi_llm_base_url == "https://poi.example.com/v1"
        assert user.poi_llm_api_key == "poi-secret-4321"
        assert user.poi_llm_model == "Console/grok-4.20-multi-agent-0309"
        assert user.weather_llm_model == "Console/grok-4.20-0309-non-reasoning"
        assert user.hotel_llm_model == "Console/grok-4.20-0309-reasoning"
        assert user.transport_llm_model == "Console/grok-4.20-0309-reasoning"
        assert user.poi_llm_wire_api == "responses"
        assert user.poi_llm_provider_protocol == "newapi"
        assert user.search_service_provider == "groksearch"
        assert user.search_service_transport == "mcp"
        assert user.search_service_base_url == "https://search.example.com/mcp"
        assert user.search_service_api_key == raw_search_key
        assert user.search_service_timeout_seconds == 45.0
        assert user.xhs_source_enabled is True
        assert user.image_base_url == "https://images.example.com/v1"
        assert user.image_model == "gpt-image-1"
        assert user.image_api_key == "img-secret-9012"
        assert user.image_provider == "openai_compatible"


def test_legacy_plaintext_credentials_are_migrated_in_place(client: TestClient):
    _register(client)

    from travelmind_api.core.credentials import ENCRYPTED_CREDENTIAL_PREFIX, migrate_legacy_plaintext_credentials
    from travelmind_api.core.database import SessionLocal, engine
    from travelmind_api.db.models import User

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE users SET llm_api_key = ? WHERE email = ?",
            ("legacy-plaintext-key", "planner@example.com"),
        )

    assert migrate_legacy_plaintext_credentials(engine) == 1

    with engine.connect() as connection:
        stored = connection.exec_driver_sql(
            "SELECT llm_api_key FROM users WHERE email = ?",
            ("planner@example.com",),
        ).scalar_one()
    assert stored.startswith(ENCRYPTED_CREDENTIAL_PREFIX)
    assert "legacy-plaintext-key" not in stored

    with SessionLocal() as session:
        user = session.query(User).filter(User.email == "planner@example.com").one()
        assert user.llm_api_key == "legacy-plaintext-key"



def test_trip_jobs_do_not_persist_llm_secret_snapshots(client: TestClient, monkeypatch):
    from travelmind_api.agents.stub import StubOrchestrator
    import travelmind_api.jobs.handlers as job_handlers

    monkeypatch.setattr(job_handlers, "build_orchestrator", lambda *args, **kwargs: StubOrchestrator())
    _register(client)

    raw_config = {
        "base_url": "https://api.gateway.example/v1",
        "api_key": "sk-job-snapshot-5678",
        "model": "gpt-5.4",
        "wire_api": "responses",
        "agent_provider": "helloagents",
        "xhs_source_enabled": True,
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


def test_search_settings_accept_groksearch_mcp_and_reject_api_transport(client: TestClient):
    _register(client)

    valid_response = client.put(
        "/api/v1/settings/llm",
        json={
            "search": {
                "provider": "groksearch",
                "transport": "mcp",
                "base_url": "https://groksearch.example.com/mcp",
                "api_key": "grok-bridge-key",
                "timeout_seconds": 20,
            }
        },
    )
    assert valid_response.status_code == 200, valid_response.text
    updated = valid_response.json()["data"]
    assert updated["search"]["provider"] == "groksearch"
    assert updated["search"]["transport"] == "mcp"
    assert updated["search"]["base_url"] == "https://groksearch.example.com/mcp"
    assert updated["search"]["configured"] is True

    invalid_response = client.put(
        "/api/v1/settings/llm",
        json={
            "search": {
                "transport": "api",
            }
        },
    )
    assert invalid_response.status_code == 422, invalid_response.text
    assert invalid_response.json()["error"]["code"] == "invalid_search_transport"


def test_poi_model_override_requires_complete_settings(client: TestClient):
    _register(client)

    response = client.put(
        "/api/v1/settings/llm",
        json={
            "agent": {
                "provider_protocol": "newapi",
                "base_url": "https://api.example.com/v1",
                "api_key": "main-key",
                "model": "gpt-5.4",
                "wire_api": "chat_completions",
                "poi_provider_protocol": "newapi",
                "poi_base_url": "https://poi.example.com/v1",
                "poi_api_key": "poi-key",
                "poi_wire_api": "chat_completions",
            }
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "poi_llm_override_incomplete"

    valid_response = client.put(
        "/api/v1/settings/llm",
        json={
            "agent": {
                "provider_protocol": "newapi",
                "base_url": "https://api.example.com/v1",
                "api_key": "main-key",
                "model": "gpt-5.4",
                "wire_api": "chat_completions",
                "poi_provider_protocol": "newapi",
                "poi_base_url": "https://poi.example.com/v1",
                "poi_api_key": "poi-key",
                "poi_model": "grok-poi",
                "poi_wire_api": "chat_completions",
            }
        },
    )

    assert valid_response.status_code == 200, valid_response.text
    assert valid_response.json()["data"]["agent"]["poi_configured"] is True


def test_runtime_settings_reject_restricted_upstream_base_urls(client: TestClient):
    _register(client)

    localhost_response = client.put(
        "/api/v1/settings/llm",
        json={
            "agent": {
                "provider_protocol": "newapi",
                "base_url": "http://localhost:3000/v1",
                "api_key": "local-key",
                "model": "local-model",
            }
        },
    )
    assert localhost_response.status_code == 200, localhost_response.text

    private_response = client.put(
        "/api/v1/settings/llm",
        json={
            "search": {
                "provider": "tavily",
                "transport": "api",
                "base_url": "http://169.254.169.254/latest",
                "api_key": "tvly-test-key",
            }
        },
    )
    assert private_response.status_code == 422, private_response.text
    assert private_response.json()["error"]["code"] == "invalid_upstream_base_url"


def test_search_settings_accept_tavily_api_and_reject_mcp_transport(client: TestClient):
    _register(client)

    valid_response = client.put(
        "/api/v1/settings/llm",
        json={
            "search": {
                "provider": "tavily",
                "transport": "api",
                "base_url": "https://api.tavily.com/search",
                "api_key": "tvly-test-key",
                "timeout_seconds": 20,
            }
        },
    )
    assert valid_response.status_code == 200, valid_response.text
    updated = valid_response.json()["data"]
    assert updated["search"]["provider"] == "tavily"
    assert updated["search"]["transport"] == "api"
    assert updated["search"]["base_url"] == "https://api.tavily.com/search"
    assert updated["search"]["configured"] is True

    invalid_response = client.put(
        "/api/v1/settings/llm",
        json={
            "search": {
                "transport": "mcp",
            }
        },
    )
    assert invalid_response.status_code == 422, invalid_response.text
    assert invalid_response.json()["error"]["code"] == "invalid_search_transport"


def test_image_settings_accept_multiple_provider_types(client: TestClient):
    _register(client)

    for provider in ("openai_compatible", "huggingface", "gitee_ai", "modelscope", "a4f"):
        response = client.put(
            "/api/v1/settings/llm",
            json={
                "image": {
                    "base_url": "https://images.example.com/v1",
                    "api_key": "img-secret-1234",
                    "model": "demo-model",
                    "provider": provider,
                }
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["image"]["provider"] == provider
