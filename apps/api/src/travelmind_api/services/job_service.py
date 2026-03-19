from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from arq.connections import RedisSettings, create_pool
from fastapi import BackgroundTasks
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.jobs import JobResponse
from travelmind_api.core.config import Settings
from travelmind_api.core.database import session_scope
from travelmind_api.core.security import generate_identifier
from travelmind_api.db.models import JobRecord


TERMINAL_JOB_STATUSES = {"completed", "failed"}
UNSET = object()
_JOB_SCHEMA_CACHE: set[str] = set()
_JOB_SCHEMA_COLUMNS = {
    "stage": "VARCHAR(64)",
    "stage_message": "TEXT",
    "progress_percent": "INTEGER",
    "timeline_json": "JSON",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_progress(progress_percent: int | float | None) -> int | None:
    if progress_percent is None:
        return None
    return max(0, min(100, int(round(progress_percent))))


def _cache_key(session: Session) -> str:
    bind = session.get_bind()
    url = getattr(bind, "url", None)
    return str(url) if url is not None else repr(bind)


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


def ensure_job_record_schema(session: Session) -> None:
    cache_key = _cache_key(session)
    if cache_key in _JOB_SCHEMA_CACHE:
        return

    bind = session.get_bind()
    inspector = inspect(bind)
    if "job_records" not in inspector.get_table_names():
        _JOB_SCHEMA_CACHE.add(cache_key)
        return

    existing_columns = {column["name"] for column in inspector.get_columns("job_records")}
    statements = [
        f"ALTER TABLE job_records ADD COLUMN {column_name} {column_type}"
        for column_name, column_type in _JOB_SCHEMA_COLUMNS.items()
        if column_name not in existing_columns
    ]
    if statements:
        with bind.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
    _JOB_SCHEMA_CACHE.add(cache_key)


def serialize_job(job: JobRecord) -> JobResponse:
    return JobResponse(
        job_id=job.id,
        status=job.status,
        type=job.type,
        trip_id=job.trip_id,
        created_at=job.created_at,
        updated_at=job.updated_at,
        stage=job.stage,
        stage_message=job.stage_message,
        progress_percent=job.progress_percent,
        timeline_json=job.timeline_json or [],
        result=job.result_json,
        error_message=job.error_message,
    )


def create_job(session: Session, *, job_type: str, owner_user_id: str, trip_id: str | None, payload: dict) -> JobRecord:
    ensure_job_record_schema(session)
    now = _utcnow()
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
        created_at=now,
        updated_at=now,
    )
    _append_timeline_entry(job, now)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def get_job(session: Session, job_id: str, owner_user_id: str) -> JobRecord | None:
    ensure_job_record_schema(session)
    return session.query(JobRecord).filter(JobRecord.id == job_id, JobRecord.owner_user_id == owner_user_id).one_or_none()


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
) -> JobRecord | None:
    ensure_job_record_schema(session)
    job = session.query(JobRecord).filter(JobRecord.id == job_id).one_or_none()
    if not job:
        return None

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
    job.updated_at = now
    _append_timeline_entry(job, now)
    session.add(job)
    return job


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
        await pool.enqueue_job("process_job", job_id=job_id)
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

