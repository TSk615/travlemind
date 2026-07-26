from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from arq.connections import RedisSettings, create_pool
from fastapi import BackgroundTasks
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.jobs import JobResponse
from travelmind_api.core.config import Settings, get_settings
from travelmind_api.core.database import session_scope
from travelmind_api.core.security import generate_identifier
from travelmind_api.db.models import JobRecord


TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}
UNSET = object()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_progress(progress_percent: int | float | None) -> int | None:
    if progress_percent is None:
        return None
    return max(0, min(100, int(round(progress_percent))))


def _build_timeline_entry(job: JobRecord, recorded_at: datetime) -> dict[str, Any]:
    return {
        "recorded_at": recorded_at.isoformat(),
        "status": job.status,
        "stage": job.stage,
        "stage_message": job.stage_message,
        "progress_percent": job.progress_percent,
    }


def _append_timeline_entry(job: JobRecord, recorded_at: datetime) -> None:
    timeline = list(job.timeline_json or [])
    timeline.append(_build_timeline_entry(job, recorded_at))
    job.timeline_json = timeline


def extract_resume_checkpoint(job: JobRecord) -> dict[str, Any] | None:
    payload = job.payload_json if isinstance(job.payload_json, dict) else {}
    checkpoint = payload.get("resume_checkpoint")
    return checkpoint if isinstance(checkpoint, dict) else None


def _resume_metadata(job: JobRecord) -> dict[str, Any]:
    checkpoint = extract_resume_checkpoint(job)
    payload = job.payload_json if isinstance(job.payload_json, dict) else {}
    return {
        "can_resume": bool(job.status == "failed" and job.type == "trip.generate" and checkpoint),
        "resume_from_job_id": str(payload.get("resume_from_job_id") or "").strip() or None,
        "resume_failed_role": str((checkpoint or {}).get("failed_role") or "").strip() or None,
        "resume_reason": str((checkpoint or {}).get("failure_message") or "").strip() or None,
    }


def ensure_job_record_schema(session: Session) -> None:
    # Kept as a temporary compatibility shim for callers in long-lived worker
    # processes. Schema evolution is now exclusively handled by Alembic.
    del session


def serialize_job(job: JobRecord) -> JobResponse:
    resume_metadata = _resume_metadata(job)
    return JobResponse(
        job_id=job.id,
        status=job.status,
        type=job.type,
        trip_id=job.trip_id,
        **resume_metadata,
        created_at=job.created_at,
        updated_at=job.updated_at,
        stage=job.stage,
        stage_message=job.stage_message,
        progress_percent=job.progress_percent,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        timeline_json=job.timeline_json or [],
        result=job.result_json,
        error_message=job.error_message,
    )


def create_job(
    session: Session,
    *,
    job_type: str,
    owner_user_id: str,
    trip_id: str | None,
    payload: dict,
    idempotency_key: str | None = None,
    max_attempts: int | None = None,
) -> JobRecord:
    normalized_idempotency_key = str(idempotency_key or "").strip()[:128] or None
    if normalized_idempotency_key:
        existing = (
            session.query(JobRecord)
            .filter(
                JobRecord.owner_user_id == owner_user_id,
                JobRecord.type == job_type,
                JobRecord.idempotency_key == normalized_idempotency_key,
            )
            .one_or_none()
        )
        if existing is not None:
            return existing

    now = _utcnow()
    configured_attempts = max_attempts if max_attempts is not None else get_settings().job_max_attempts
    job = JobRecord(
        id=generate_identifier("job"),
        type=job_type,
        status="queued",
        owner_user_id=owner_user_id,
        trip_id=trip_id,
        payload_json=payload,
        stage="queued",
        stage_message="Job queued for execution.",
        progress_percent=0,
        timeline_json=[],
        idempotency_key=normalized_idempotency_key,
        attempt_count=0,
        max_attempts=max(1, int(configured_attempts)),
        created_at=now,
        updated_at=now,
    )
    _append_timeline_entry(job, now)
    session.add(job)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if normalized_idempotency_key:
            existing = (
                session.query(JobRecord)
                .filter(
                    JobRecord.owner_user_id == owner_user_id,
                    JobRecord.type == job_type,
                    JobRecord.idempotency_key == normalized_idempotency_key,
                )
                .one_or_none()
            )
            if existing is not None:
                return existing
        raise
    session.refresh(job)
    return job


def get_job(session: Session, job_id: str, owner_user_id: str) -> JobRecord | None:
    ensure_job_record_schema(session)
    return session.query(JobRecord).filter(JobRecord.id == job_id, JobRecord.owner_user_id == owner_user_id).one_or_none()


def get_job_by_idempotency_key(
    session: Session,
    *,
    owner_user_id: str,
    job_type: str,
    idempotency_key: str | None,
) -> JobRecord | None:
    normalized = str(idempotency_key or "").strip()[:128]
    if not normalized:
        return None
    return (
        session.query(JobRecord)
        .filter(
            JobRecord.owner_user_id == owner_user_id,
            JobRecord.type == job_type,
            JobRecord.idempotency_key == normalized,
        )
        .one_or_none()
    )


def update_job_state(
    session: Session,
    job_id: str,
    *,
    status: str | object = UNSET,
    stage: str | None | object = UNSET,
    stage_message: str | None | object = UNSET,
    progress_percent: int | float | None | object = UNSET,
    result: dict[str, Any] | None | object = UNSET,
    error_message: str | None | object = UNSET,
    set_started: bool = False,
    set_finished: bool = False,
    clear_finished: bool = False,
    skip_if_terminal: bool = False,
) -> JobRecord | None:
    ensure_job_record_schema(session)
    job = session.query(JobRecord).filter(JobRecord.id == job_id).one_or_none()
    if not job:
        return None
    if skip_if_terminal and job.status in TERMINAL_JOB_STATUSES:
        return job

    now = _utcnow()
    if status is not UNSET:
        job.status = str(status)
    if stage is not UNSET:
        job.stage = stage
    if stage_message is not UNSET:
        job.stage_message = stage_message
    if progress_percent is not UNSET:
        job.progress_percent = _normalize_progress(progress_percent)
    if result is not UNSET:
        job.result_json = result
    if error_message is not UNSET:
        job.error_message = error_message
    if set_started and job.started_at is None:
        job.started_at = now
    if clear_finished:
        job.finished_at = None
    if set_finished:
        job.finished_at = now
    if job.status == "running":
        job.heartbeat_at = now
    if job.status in TERMINAL_JOB_STATUSES:
        job.locked_at = None
        job.heartbeat_at = None
        job.available_at = None
    job.updated_at = now
    _append_timeline_entry(job, now)
    session.add(job)
    return job


def cancel_job(session: Session, job_id: str, owner_user_id: str, *, message: str = "Job cancelled by user.") -> JobRecord | None:
    ensure_job_record_schema(session)
    job = get_job(session, job_id, owner_user_id)
    if job is None:
        return None
    if job.status in TERMINAL_JOB_STATUSES:
        return job
    return update_job_state(
        session,
        job_id,
        status="cancelled",
        stage="cancelled",
        stage_message=message,
        progress_percent=job.progress_percent,
        error_message=None,
        set_finished=True,
    )


def touch_job_heartbeat(job_id: str) -> bool:
    with session_scope() as session:
        now = _utcnow()
        updated = (
            session.query(JobRecord)
            .filter(JobRecord.id == job_id, JobRecord.status == "running")
            .update({JobRecord.heartbeat_at: now, JobRecord.updated_at: now}, synchronize_session=False)
        )
        return bool(updated)


def recover_stale_jobs(*, stale_after_seconds: int) -> list[str]:
    cutoff = _utcnow() - timedelta(seconds=max(int(stale_after_seconds), 1))
    with session_scope() as session:
        stale_jobs = (
            session.query(JobRecord)
            .filter(
                JobRecord.status == "running",
                or_(
                    JobRecord.heartbeat_at < cutoff,
                    (JobRecord.heartbeat_at.is_(None) & (JobRecord.locked_at < cutoff)),
                    (JobRecord.heartbeat_at.is_(None) & JobRecord.locked_at.is_(None) & (JobRecord.started_at < cutoff)),
                ),
            )
            .all()
        )
        recovered: list[str] = []
        now = _utcnow()
        for job in stale_jobs:
            if job.attempt_count >= job.max_attempts:
                job.status = "failed"
                job.stage = "failed"
                job.stage_message = "Job exceeded its maximum attempts after a stale worker lock."
                job.error_message = job.stage_message
                job.finished_at = now
            else:
                job.status = "retrying"
                job.stage = "retry_wait"
                job.stage_message = "Recovered after a stale worker lock."
                job.available_at = now
                recovered.append(job.id)
            job.locked_at = None
            job.heartbeat_at = None
            job.updated_at = now
            _append_timeline_entry(job, now)
            session.add(job)
        return recovered


def _redis_settings(redis_url: str) -> RedisSettings:
    parsed = urlparse(redis_url)
    return RedisSettings(
        host=parsed.hostname or "127.0.0.1",
        port=parsed.port or 6379,
        database=int((parsed.path or "/0").lstrip("/") or 0),
        password=parsed.password,
    )


async def _enqueue_via_arq(redis_url: str, job_id: str) -> None:
    pool = await create_pool(_redis_settings(redis_url))
    try:
        await pool.enqueue_job("process_job", job_id=job_id, _job_id=f"travelmind:{job_id}")
    finally:
        await pool.close()


def _mark_dispatch_failed(job_id: str, message: str) -> None:
    with session_scope() as session:
        ensure_job_record_schema(session)
        job = session.query(JobRecord).filter(JobRecord.id == job_id).one_or_none()
        if not job or job.status in TERMINAL_JOB_STATUSES:
            return
        update_job_state(
            session,
            job_id,
            status="failed",
            stage_message=message,
            error_message=message,
            set_finished=True,
        )


def dispatch_job(job_id: str, settings: Settings, background_tasks: BackgroundTasks) -> None:
    if settings.queue_mode == "inline":
        from travelmind_api.jobs.handlers import process_job

        background_tasks.add_task(process_job, job_id)
        return

    if settings.queue_mode == "arq":
        try:
            asyncio.run(_enqueue_via_arq(settings.redis_url, job_id))
        except Exception as exc:
            message = str(exc).strip() or exc.__class__.__name__
            _mark_dispatch_failed(job_id, f"Failed to enqueue ARQ job: {message}")
        return

    _mark_dispatch_failed(job_id, f"Unsupported queue mode: {settings.queue_mode}")


def dispatch_job_now(job_id: str, settings: Settings) -> None:
    if settings.queue_mode == "inline":
        from travelmind_api.jobs.handlers import process_job

        process_job(job_id)
        return

    if settings.queue_mode == "arq":
        try:
            asyncio.run(_enqueue_via_arq(settings.redis_url, job_id))
        except Exception as exc:
            message = str(exc).strip() or exc.__class__.__name__
            _mark_dispatch_failed(job_id, f"Failed to enqueue ARQ job: {message}")
        return

    _mark_dispatch_failed(job_id, f"Unsupported queue mode: {settings.queue_mode}")

