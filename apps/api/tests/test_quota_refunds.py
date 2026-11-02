from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from travelmind_api.core.database import SessionLocal
from travelmind_api.db.models import GenerationQuota, GenerationQuotaCharge, JobRecord, Trip
from travelmind_api.services.generation_quota import refund_failed_generation
from travelmind_api.services.job_service import create_job, serialize_job, update_job_state, recover_stale_jobs
from test_api_contracts import _create_trip
from test_demo_quota import _demo


def _job(user_id, trip_id, job_type="trip.generate"):
    with SessionLocal() as s:
        return create_job(s, job_type=job_type, owner_user_id=user_id, trip_id=trip_id, payload={}).id


def _used(user_id):
    with SessionLocal() as s:
        return s.get(GenerationQuota, user_id).used


@pytest.mark.parametrize("job_type", ["trip.generate", "trip.refine"])
def test_failure_refunds_once_and_receipt_survives_result_replacement(client, monkeypatch, job_type):
    user = _demo(client, monkeypatch)
    trip = _create_trip(client).json()["data"]["id"]
    job_id = _job(user, trip, job_type)
    assert _used(user) == 1
    with SessionLocal() as s:
        job = update_job_state(s, job_id, status="failed", error_message="schema_validation_failed", set_finished=True)
        assert refund_failed_generation(s, job) is False  # Same transaction must not refund twice.
        s.commit()
    with SessionLocal() as s:
        job = update_job_state(s, job_id, status="failed", result={"resume_available": True})
        s.commit()
        assert serialize_job(job).quota_refunded is True
        assert serialize_job(job).public_error_code == "planning_validation_failed"
    assert _used(user) == 0
    assert client.get(f"/api/v1/jobs/{job_id}").json()["data"]["quota_refunded"] is True


def test_refund_and_failed_status_rollback_together(client, monkeypatch):
    user = _demo(client, monkeypatch)
    trip = _create_trip(client).json()["data"]["id"]
    job_id = _job(user, trip)
    with SessionLocal() as s:
        update_job_state(s, job_id, status="failed")
        s.rollback()
    assert _used(user) == 1
    with SessionLocal() as s:
        assert s.get(JobRecord, job_id).status == "queued"
        assert s.get(GenerationQuotaCharge, job_id).refunded_at is None


def test_duplicate_workers_and_new_debits_are_serialized(client, monkeypatch):
    user = _demo(client, monkeypatch)
    trip = _create_trip(client).json()["data"]["id"]
    job_id = _job(user, trip)

    def notification(index):
        with SessionLocal() as s:
            if index % 2:
                create_job(s, job_type="trip.refine", owner_user_id=user, trip_id=trip, payload={})
            else:
                # Simulate a stale ORM identity loaded before another notification.
                s.get(JobRecord, job_id)
                update_job_state(s, job_id, status="failed", skip_if_terminal=True)
                s.commit()

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(notification, range(8)))
    assert _used(user) == 4


@pytest.mark.parametrize("state", ["running", "retrying", "completed", "cancelled"])
def test_nonfailure_never_refunds(client, monkeypatch, state):
    user = _demo(client, monkeypatch)
    trip = _create_trip(client).json()["data"]["id"]
    job_id = _job(user, trip)
    with SessionLocal() as s:
        update_job_state(s, job_id, status=state)
        s.commit()
    assert _used(user) == 1


def test_unmetered_failure_never_refunds_another_job(client, monkeypatch):
    user = _demo(client, monkeypatch)
    trip = _create_trip(client).json()["data"]["id"]
    _job(user, trip)
    image_id = _job(user, trip, "trip.image_enrich")
    with SessionLocal() as s:
        job = update_job_state(s, image_id, status="failed")
        s.commit()
        assert not serialize_job(job).quota_refunded
    assert _used(user) == 1


def test_stale_exhausted_job_refunds_but_recoverable_does_not(client, monkeypatch):
    user = _demo(client, monkeypatch)
    trip = _create_trip(client).json()["data"]["id"]
    ids = [_job(user, trip), _job(user, trip)]
    with SessionLocal() as s:
        for i, job_id in enumerate(ids):
            j = s.get(JobRecord, job_id)
            j.status = "running"
            j.attempt_count = j.max_attempts if i == 0 else 0
            j.heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=2)
        s.commit()
    recovered = recover_stale_jobs(stale_after_seconds=60)
    assert ids[1] in recovered and ids[0] not in recovered
    assert _used(user) == 1


def test_dispatch_failure_refunds(client, monkeypatch):
    from travelmind_api.services.job_service import _mark_dispatch_failed
    user = _demo(client, monkeypatch)
    trip = _create_trip(client).json()["data"]["id"]
    job_id = _job(user, trip)
    _mark_dispatch_failed(job_id, "Queue unavailable")
    _mark_dispatch_failed(job_id, "Duplicate notification")
    assert _used(user) == 0


def test_expired_trip_and_late_same_day_rejected_before_charge_or_queue(client, monkeypatch):
    user = _demo(client, monkeypatch)
    trip = _create_trip(client).json()["data"]["id"]
    fixed = datetime(2030, 5, 1, 23, 45, tzinfo=timezone(timedelta(hours=8)))
    from travelmind_api.services.trip_service import validate_trip_dates_for_generation
    # Freeze the business instant, not the host-local astimezone conversion.
    # This exercises the real validator identically on UTC CI and UTC+08 hosts.
    monkeypatch.setattr("travelmind_api.services.trip_service.validate_trip_dates_for_generation",
                        lambda start, end: validate_trip_dates_for_generation(start, end, now=fixed))
    for start, code in [(fixed.date(), "same_day_planning_window_closed"), (fixed.date()-timedelta(days=1), "expired_trip_start_date")]:
        with SessionLocal() as s:
            j = s.get(Trip, trip)
            j.start_date = start
            j.end_date = fixed.date() + timedelta(days=3)
            s.commit()
        response = client.post(f"/api/v1/trips/{trip}/generate")
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == code
    assert _used(user) == 0
    with SessionLocal() as s:
        assert s.query(GenerationQuotaCharge).count() == 0
        assert s.query(JobRecord).filter(JobRecord.owner_user_id == user).count() == 0


def test_failed_idempotent_request_does_not_debit_again(client, monkeypatch):
    user = _demo(client, monkeypatch)
    trip = _create_trip(client).json()["data"]["id"]
    with SessionLocal() as s:
        job = create_job(s, job_type="trip.generate", owner_user_id=user, trip_id=trip, payload={}, idempotency_key="refunded")
        update_job_state(s, job.id, status="failed")
        s.commit()
        repeated = create_job(s, job_type="trip.generate", owner_user_id=user, trip_id=trip, payload={}, idempotency_key="refunded")
        assert repeated.id == job.id
    assert _used(user) == 0


def test_public_failure_codes_only_return_safe_contract():
    from travelmind_api.services.job_public_error import public_job_error_code
    assert public_job_error_code("failed", "今天已经没有足够的行程生成与准备时间 (log: /secret)") == "same_day_planning_window_closed"
    assert public_job_error_code("failed", "行程开始日期 2026-11-02 已经过期 /secret") == "expired_trip_start_date"
    assert public_job_error_code("failed", "api_key=secret /app/storage/internal") == "job_failed"
    assert public_job_error_code("running", "schema_validation_failed") is None
