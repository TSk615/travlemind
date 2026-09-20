from __future__ import annotations

from datetime import date, timedelta


def _register_and_create_trip(client):
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "rollout@example.com", "password": "StrongPass123!", "name": "Rollout"},
    )
    assert registration.status_code == 200, registration.text
    start = date.today() + timedelta(days=30)
    trip = client.post(
        "/api/v1/trips",
        json={
            "title": "Rollout trip",
            "origin": "上海",
            "destination": "杭州",
            "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=1)).isoformat(),
            "budget": 3000,
            "travelers": 1,
            "interests": ["博物馆"],
            "accommodation_preference": "安静",
            "pace": "balanced",
            "transport_mode": "rail",
        },
    )
    assert trip.status_code == 200, trip.text
    return registration.json()["data"]["id"], trip.json()["data"]["id"]


def test_drain_audit_blocks_legacy_and_unknown_jobs_until_terminal(client):
    from travelmind_api.core.database import SessionLocal
    from travelmind_api.db.models import JobRecord
    from travelmind_api.services.job_service import create_job
    from travelmind_api.services.workflow_rollout import audit_workflow_drain

    user_id, trip_id = _register_and_create_trip(client)
    with SessionLocal() as session:
        legacy = create_job(
            session,
            job_type="trip.generate",
            owner_user_id=user_id,
            trip_id=trip_id,
            payload={"trip_id": trip_id, "workflow_provider": "helloagents"},
        )
        unknown = create_job(
            session,
            job_type="trip.refine",
            owner_user_id=user_id,
            trip_id=trip_id,
            payload={"trip_id": trip_id},
        )
        session.commit()

        audit = audit_workflow_drain(session)
        assert audit.safe_to_remove_legacy_runtime is False
        assert audit.active_jobs_by_provider == {"helloagents": 1, "unknown": 1}
        assert audit.blocking_job_ids == [legacy.id, unknown.id]
        assert audit.unknown_provider_job_ids == [unknown.id]

        session.get(JobRecord, legacy.id).status = "completed"
        session.get(JobRecord, unknown.id).status = "cancelled"
        session.commit()

        drained = audit_workflow_drain(session)
        assert drained.safe_to_remove_legacy_runtime is True
        assert drained.active_jobs_by_provider == {}


def test_drain_audit_allows_active_langgraph_job(client):
    from travelmind_api.core.database import SessionLocal
    from travelmind_api.services.job_service import create_job
    from travelmind_api.services.workflow_rollout import audit_workflow_drain

    user_id, trip_id = _register_and_create_trip(client)
    with SessionLocal() as session:
        create_job(
            session,
            job_type="trip.generate",
            owner_user_id=user_id,
            trip_id=trip_id,
            payload={"trip_id": trip_id, "workflow_provider": "langgraph"},
        )
        session.commit()

        audit = audit_workflow_drain(session)
        assert audit.safe_to_remove_legacy_runtime is True
        assert audit.active_jobs_by_provider == {"langgraph": 1}
        assert audit.blocking_job_ids == []
