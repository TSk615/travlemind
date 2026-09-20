from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Iterator

import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from psycopg.rows import dict_row
from sqlalchemy.orm import Session

from travelmind_api.agents.provider import AGENT_PROVIDER_LANGGRAPH
from travelmind_api.agents.workflows.state import (
    TRIP_GENERATION_GRAPH_VERSION,
    TRIP_GENERATION_STATE_SCHEMA_VERSION,
    TripGenerationState,
)
from travelmind_api.core.config import Settings
from travelmind_api.core.security import generate_identifier
from travelmind_api.db.models import JobRecord, Trip, WorkflowRun


_POSTGRES_SETUP_LOCK = Lock()
_POSTGRES_SETUP_URLS: set[str] = set()
_POSTGRES_CHECKPOINT_SETUP_LOCK_ID = 741852964


class WorkflowRunError(RuntimeError):
    """Base error for invalid or stale durable workflow execution state."""


class WorkflowRunVersionError(WorkflowRunError):
    """Raised when a persisted run cannot be resumed by the current graph."""


class WorkflowCommitConflict(WorkflowRunError):
    """Raised when a completed workflow would overwrite a newer trip edit."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _strict_serializer() -> JsonPlusSerializer:
    # Graph state is intentionally JSON-like. Disallowing arbitrary msgpack
    # extension modules keeps a compromised checkpoint store from importing
    # application-controlled Python types while deserializing state.
    return JsonPlusSerializer(pickle_fallback=False, allowed_msgpack_modules=[])


def _sqlite_path(checkpoint_url: str) -> str:
    value = checkpoint_url.strip()
    if value.startswith("sqlite:///"):
        value = value.removeprefix("sqlite:///")
    if value == ":memory:":
        return value
    path = Path(value).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


@contextmanager
def workflow_checkpointer(settings: Settings) -> Iterator[BaseCheckpointSaver[Any]]:
    """Yield a process-safe durable checkpointer for one graph execution.

    SQLite is opened per execution for local deployments. PostgreSQL also uses
    a short-lived connection, while its schema setup is performed once per
    process and remains safe when multiple workers initialize concurrently.
    """

    checkpoint_url = settings.resolved_workflow_checkpoint_url
    if checkpoint_url.lower().startswith(("postgres://", "postgresql://")):
        connection = psycopg.connect(checkpoint_url, autocommit=True, row_factory=dict_row)
        try:
            saver = PostgresSaver(connection, serde=_strict_serializer())
            with _POSTGRES_SETUP_LOCK:
                if checkpoint_url not in _POSTGRES_SETUP_URLS:
                    # The Python lock protects threads in this process; the
                    # session-level advisory lock serializes first-time setup
                    # across independently started ARQ worker processes.
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT pg_advisory_lock(%s)",
                            (_POSTGRES_CHECKPOINT_SETUP_LOCK_ID,),
                        )
                    try:
                        saver.setup()
                        _POSTGRES_SETUP_URLS.add(checkpoint_url)
                    finally:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "SELECT pg_advisory_unlock(%s)",
                                (_POSTGRES_CHECKPOINT_SETUP_LOCK_ID,),
                            )
            yield saver
        finally:
            connection.close()
        return

    connection = sqlite3.connect(_sqlite_path(checkpoint_url), check_same_thread=False, timeout=30)
    try:
        saver = SqliteSaver(connection, serde=_strict_serializer())
        saver.setup()
        yield saver
    finally:
        connection.close()


def checkpoint_exists(checkpointer: BaseCheckpointSaver[Any], run_id: str) -> bool:
    config = {"configurable": {"thread_id": run_id}}
    return checkpointer.get_tuple(config) is not None


def bind_workflow_run(
    session: Session,
    *,
    job: JobRecord,
    trip: Trip,
    provider: str,
    graph_version: str = TRIP_GENERATION_GRAPH_VERSION,
    state_schema_version: int = TRIP_GENERATION_STATE_SCHEMA_VERSION,
) -> WorkflowRun | None:
    """Create or bind a stable run to the currently executing Job."""

    if provider != AGENT_PROVIDER_LANGGRAPH:
        return None
    if not job.owner_user_id or not job.trip_id:
        raise WorkflowRunError("LangGraph generation requires an owning user and trip")

    payload = dict(job.payload_json or {})
    requested_run_id = str(job.workflow_run_id or payload.get("workflow_run_id") or "").strip()
    run = session.get(WorkflowRun, requested_run_id) if requested_run_id else None
    if requested_run_id and run is None:
        raise WorkflowRunError("The requested workflow run no longer exists")
    if run is None:
        now = utcnow()
        run = WorkflowRun(
            id=generate_identifier("run"),
            owner_user_id=job.owner_user_id,
            trip_id=job.trip_id,
            original_job_id=job.id,
            current_job_id=job.id,
            provider=provider,
            graph_version=graph_version,
            state_schema_version=state_schema_version,
            expected_trip_updated_at=trip.updated_at,
            status="running",
            created_at=now,
            updated_at=now,
        )
        session.add(run)
        session.flush()
    else:
        if run.owner_user_id != job.owner_user_id or run.trip_id != job.trip_id:
            raise WorkflowRunError("Workflow run ownership or trip association does not match the Job")
        if run.provider != provider:
            raise WorkflowRunVersionError("Workflow provider changed; start a new generation")
        if (
            run.graph_version != graph_version
            or run.state_schema_version != state_schema_version
        ):
            raise WorkflowRunVersionError("Workflow graph or state schema changed; start a new generation")
        run.current_job_id = job.id
        if run.committed_at is None:
            run.status = "running"
            run.failure_message = None
        run.updated_at = utcnow()

    job.workflow_run_id = run.id
    payload.update(
        {
            "workflow_run_id": run.id,
            "workflow_provider": run.provider,
            "workflow_graph_version": run.graph_version,
            "workflow_state_schema_version": run.state_schema_version,
        }
    )
    job.payload_json = payload
    session.add(job)
    session.add(run)
    return run


def record_workflow_state(
    session: Session,
    run: WorkflowRun,
    state: TripGenerationState | None,
    *,
    status: str | None = None,
    failure_message: str | None = None,
) -> None:
    if state:
        fingerprint = str(state.get("input_fingerprint") or "").strip()
        if fingerprint:
            if run.input_fingerprint and run.input_fingerprint != fingerprint:
                raise WorkflowRunVersionError("Workflow input fingerprint changed; start a new generation")
            run.input_fingerprint = fingerprint
    if status:
        run.status = status
    run.failure_message = failure_message
    run.updated_at = utcnow()
    session.add(run)


def normalize_database_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def trip_version_matches(run: WorkflowRun, trip: Trip) -> bool:
    return normalize_database_datetime(run.expected_trip_updated_at) == normalize_database_datetime(trip.updated_at)
