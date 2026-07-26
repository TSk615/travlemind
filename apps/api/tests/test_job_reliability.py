from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx


def test_create_job_reuses_idempotency_key(client):
    del client
    from travelmind_api.core.database import SessionLocal
    from travelmind_api.db.models import JobRecord
    from travelmind_api.services.job_service import create_job

    with SessionLocal() as session:
        first = create_job(
            session,
            job_type="export.pdf",
            owner_user_id="usr-idempotent",
            trip_id=None,
            payload={"trip_id": "trip-1"},
            idempotency_key="same-request",
        )
        second = create_job(
            session,
            job_type="export.pdf",
            owner_user_id="usr-idempotent",
            trip_id=None,
            payload={"trip_id": "trip-1"},
            idempotency_key="same-request",
        )
        assert first.id == second.id
        assert session.query(JobRecord).filter(JobRecord.owner_user_id == "usr-idempotent").count() == 1


def test_claim_and_transient_retry_increment_attempts(client):
    del client
    from travelmind_api.core.database import SessionLocal
    from travelmind_api.db.models import JobRecord
    from travelmind_api.jobs.handlers import _claim_job, _schedule_retry
    from travelmind_api.services.job_service import create_job

    with SessionLocal() as session:
        job = create_job(
            session,
            job_type="export.pdf",
            owner_user_id="usr-retry",
            trip_id=None,
            payload={},
            max_attempts=3,
        )
        job_id = job.id

    first_claim = _claim_job(job_id)
    assert first_claim is not None
    assert first_claim.attempt_count == 1
    assert _schedule_retry(job_id, httpx.TimeoutException("upstream timed out")) == 5

    second_claim = _claim_job(job_id)
    assert second_claim is not None
    assert second_claim.attempt_count == 2

    with SessionLocal() as session:
        stored = session.query(JobRecord).filter(JobRecord.id == job_id).one()
        assert stored.status == "running"
        assert stored.locked_at is not None
        assert stored.heartbeat_at is not None


def test_stale_jobs_are_recovered_or_failed_at_attempt_limit(client):
    del client
    from travelmind_api.core.database import SessionLocal
    from travelmind_api.db.models import JobRecord
    from travelmind_api.services.job_service import create_job, recover_stale_jobs

    stale_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    with SessionLocal() as session:
        recoverable = create_job(
            session,
            job_type="trip.generate",
            owner_user_id="usr-stale",
            trip_id=None,
            payload={},
            max_attempts=3,
        )
        exhausted = create_job(
            session,
            job_type="trip.refine",
            owner_user_id="usr-stale",
            trip_id=None,
            payload={},
            max_attempts=1,
        )
        for job, attempts in ((recoverable, 1), (exhausted, 1)):
            job.status = "running"
            job.attempt_count = attempts
            job.started_at = stale_time
            job.locked_at = stale_time
            job.heartbeat_at = stale_time
            session.add(job)
        session.commit()
        recoverable_id = recoverable.id
        exhausted_id = exhausted.id

    recovered = recover_stale_jobs(stale_after_seconds=60)
    assert recovered == [recoverable_id]

    with SessionLocal() as session:
        recoverable = session.query(JobRecord).filter(JobRecord.id == recoverable_id).one()
        exhausted = session.query(JobRecord).filter(JobRecord.id == exhausted_id).one()
        assert recoverable.status == "retrying"
        assert recoverable.locked_at is None
        assert exhausted.status == "failed"
        assert exhausted.finished_at is not None
