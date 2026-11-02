from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from travelmind_api.core.config import get_settings
from travelmind_api.core.database import SessionLocal
from travelmind_api.db.models import GenerationQuota, JobRecord, User
from travelmind_api.provision_demo import provision_demo
from travelmind_api.services.job_service import create_job
from test_api_contracts import _create_trip, _register

EMAIL = "demo@travelmind.example"
PASSWORD = "TravelMind-Demo-2026!"


def _demo(client, monkeypatch):
    # Never spend the real five public credits or invoke upstream models in tests.
    monkeypatch.setattr("travelmind_api.api.routes.trips.dispatch_job", lambda *args: None)
    monkeypatch.setattr("travelmind_api.api.routes.jobs.dispatch_job", lambda *args: None)
    with SessionLocal() as session:
        user = provision_demo(session, email=EMAIL, password=PASSWORD, settings=get_settings())
        user_id = user.id
    response = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200
    assert response.json()["data"]["generation_quota"] == {"limit": 5, "used": 0, "remaining": 5}
    return user_id


def test_five_generations_sixth_denied_and_idempotency_is_free(client, monkeypatch):
    user_id = _demo(client, monkeypatch)
    trip_id = _create_trip(client).json()["data"]["id"]
    url = f"/api/v1/trips/{trip_id}/generate"
    first = None
    for i in range(5):
        response = client.post(url, headers={"Idempotency-Key": f"demo-{i}"})
        assert response.status_code == 200, response.text
        if i == 0:
            first = response.json()["data"]["job_id"]
    assert client.get("/api/v1/me").json()["data"]["generation_quota"]["remaining"] == 0
    duplicate = client.post(url, headers={"Idempotency-Key": "demo-0"})
    assert duplicate.status_code == 200
    assert duplicate.json()["data"]["job_id"] == first
    denied = client.post(url)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "generation_quota_exhausted"
    assert client.get(f"/api/v1/trips/{trip_id}").status_code == 200
    assert client.delete(f"/api/v1/trips/{trip_id}").status_code == 200
    with SessionLocal() as session:
        assert session.get(GenerationQuota, user_id).used == 5
        again = provision_demo(session, email=EMAIL, password=PASSWORD, settings=get_settings())
        assert again.generation_quota.used == 5
    client.post("/api/v1/auth/logout")
    login = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert login.json()["data"]["generation_quota"]["remaining"] == 0


def test_concurrent_requests_cannot_overspend(client, monkeypatch):
    user_id = _demo(client, monkeypatch)
    trip_id = _create_trip(client).json()["data"]["id"]

    def attempt(index):
        with SessionLocal() as session:
            try:
                job = create_job(session, job_type="trip.generate", owner_user_id=user_id,
                                 trip_id=trip_id, payload={}, idempotency_key=f"parallel-{index}")
                return job.id
            except HTTPException as exc:
                assert exc.status_code == 403
                return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(12)))
    assert sum(result is not None for result in results) == 5
    with SessionLocal() as session:
        assert session.get(GenerationQuota, user_id).used == 5
        assert len(session.scalars(select(JobRecord).where(JobRecord.owner_user_id == user_id)).all()) == 5


def test_concurrent_same_key_debits_once(client, monkeypatch):
    user_id = _demo(client, monkeypatch)
    trip_id = _create_trip(client).json()["data"]["id"]

    def attempt(_):
        with SessionLocal() as session:
            return create_job(session, job_type="trip.generate", owner_user_id=user_id, trip_id=trip_id,
                              payload={}, idempotency_key="same-key").id

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(attempt, range(5)))
    assert len(set(results)) == 1
    with SessionLocal() as session:
        assert session.get(GenerationQuota, user_id).used == 1


def test_refinement_retry_and_rollback_share_allowance(client, monkeypatch):
    user_id = _demo(client, monkeypatch)
    trip_id = _create_trip(client).json()["data"]["id"]
    with SessionLocal() as session:
        create_job(session, job_type="trip.refine", owner_user_id=user_id, trip_id=trip_id, payload={}, commit=False)
        session.rollback()
        assert session.get(GenerationQuota, user_id).used == 0
        create_job(session, job_type="trip.refine", owner_user_id=user_id, trip_id=trip_id, payload={})
    with SessionLocal() as session:
        job = create_job(session, job_type="trip.generate", owner_user_id=user_id, trip_id=trip_id, payload={})
        job.status = "failed"
        job.payload_json = {"resume_checkpoint": {"failed_role": "planner"}}
        session.commit()
        job_id = job.id
    assert client.post(f"/api/v1/jobs/{job_id}/retry").status_code == 200
    assert client.get("/api/v1/me").json()["data"]["generation_quota"]["used"] == 3


@pytest.mark.parametrize("method,path", [
    ("put", "/settings/llm"), ("post", "/llm/proxy"), ("post", "/llm/test"),
    ("post", "/llm/models"), ("post", "/llm/search-proxy"), ("post", "/llm/search-images-proxy"),
    ("post", "/search"), ("post", "/images/generate"), ("post", "/images/prompts/compose"),
    ("post", "/trips/intake/chat"), ("post", "/account/xhs/bind"),
    ("post", "/trips/unused/images/enrich"),
])
def test_demo_cannot_bypass_meter_or_edit_providers(client, monkeypatch, method, path):
    _demo(client, monkeypatch)
    response = getattr(client, method)("/api/v1" + path, json={})
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "demo_action_forbidden"


def test_normal_accounts_remain_unlimited(client, monkeypatch):
    monkeypatch.setattr("travelmind_api.api.routes.trips.dispatch_job", lambda *args: None)
    _register(client)
    trip_id = _create_trip(client).json()["data"]["id"]
    for _ in range(7):
        assert client.post(f"/api/v1/trips/{trip_id}/generate").status_code == 200
    assert client.get("/api/v1/me").json()["data"]["generation_quota"] is None


def test_provision_refuses_admin_existing_accounts_and_missing_source(client):
    with SessionLocal() as session:
        with pytest.raises(ValueError, match="administrators"):
            provision_demo(session, email="admin@example.com", password=PASSWORD,
                           settings=get_settings().model_copy(update={"admin_emails": "admin@example.com"}))
        with pytest.raises(ValueError, match="does not exist"):
            provision_demo(session, email=EMAIL, password=PASSWORD, settings=get_settings(),
                           copy_settings_from_email="missing@example.com")
    _register(client, email=EMAIL)
    with SessionLocal() as session:
        with pytest.raises(ValueError, match="Refusing"):
            provision_demo(session, email=EMAIL, password=PASSWORD, settings=get_settings())


def test_demo_settings_hide_key_fragments(client, monkeypatch):
    user_id = _demo(client, monkeypatch)
    with SessionLocal() as session:
        user = session.get(User, user_id)
        user.llm_api_key = "secret-prefix-never-show-secret-suffix"
        session.commit()
    response = client.get("/api/v1/settings/llm")
    assert response.status_code == 200
    assert response.json()["data"]["agent"]["api_key_masked"] == "configured"
    assert "secret-prefix" not in response.text


def test_public_account_never_becomes_admin_via_allowlist(client, monkeypatch):
    from travelmind_api.services.auth_service import is_admin_user
    user_id = _demo(client, monkeypatch)
    with SessionLocal() as session:
        user = session.get(User, user_id)
        settings = get_settings().model_copy(update={"admin_emails": EMAIL})
        assert not is_admin_user(user, settings)


def test_stdin_provisioning_is_allowlisted_and_preserves_credentials(client):
    config = {"llm_base_url": "https://models.example.com/v1", "llm_api_key": "fixture-key",
              "llm_model": "fixture-model", "llm_agent_provider": "langgraph"}
    with SessionLocal() as session:
        with pytest.raises(ValueError, match="unsupported"):
            provision_demo(session, email=EMAIL, password=PASSWORD, settings=get_settings(),
                           planning_settings={**config, "image_api_key": "not-allowed"})
        user = provision_demo(session, email=EMAIL, password=PASSWORD, settings=get_settings(),
                              planning_settings=config)
        assert user.llm_api_key == "fixture-key"
        assert user.image_api_key is None and not user.xhs_source_enabled
        user.generation_quota.used = 2
        session.commit()
        again = provision_demo(session, email=EMAIL, password=PASSWORD, settings=get_settings(),
                               planning_settings={**config, "llm_api_key": "should-not-replace"})
        assert again.llm_api_key == "fixture-key"
        assert again.generation_quota.used == 2
