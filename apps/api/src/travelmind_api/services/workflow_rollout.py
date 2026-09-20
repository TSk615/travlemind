from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
import json
from typing import Any

from sqlalchemy import MetaData, Table, inspect, select
from sqlalchemy.orm import Session

from travelmind_api.agents.provider import AGENT_PROVIDER_LANGGRAPH, normalize_agent_provider


ACTIVE_JOB_STATUSES = frozenset({"queued", "retrying", "running"})
TERMINAL_WORKFLOW_STATUSES = frozenset({"completed", "cancelled", "conflicted", "failed"})
WORKFLOW_JOB_TYPES = frozenset({"trip.generate", "trip.refine"})


@dataclass(frozen=True)
class WorkflowDrainAudit:
    safe_to_remove_legacy_runtime: bool
    schema_ready_for_langgraph: bool = True
    schema_blockers: list[str] = field(default_factory=list)
    active_jobs_by_provider: dict[str, int] = field(default_factory=dict)
    active_runs_by_provider: dict[str, int] = field(default_factory=dict)
    blocking_job_ids: list[str] = field(default_factory=list)
    blocking_run_ids: list[str] = field(default_factory=list)
    unknown_provider_job_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _payload_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _audit_provider(value: Any) -> str | None:
    candidate = str(value or "").strip().lower()
    if not candidate:
        return None
    if candidate in {"helloagents", "helloagents-poc"}:
        return "helloagents"
    return normalize_agent_provider(candidate)


def audit_workflow_drain(session: Session) -> WorkflowDrainAudit:
    """Report whether this database contains work that still needs a legacy runtime.

    Unknown provider snapshots are deliberately blocking: jobs created by an
    older deployment may not have persisted their provider yet, so treating
    them as safe could strand queued work during dependency removal.
    """

    bind = session.get_bind()
    schema = inspect(bind)
    table_names = set(schema.get_table_names())
    job_columns = {column["name"] for column in schema.get_columns("job_records")} if "job_records" in table_names else set()
    schema_blockers: list[str] = []
    if "workflow_run_id" not in job_columns:
        schema_blockers.append("job_records.workflow_run_id is missing; apply migration 0005_workflow_runs")
    if "workflow_runs" not in table_names:
        schema_blockers.append("workflow_runs table is missing; apply migration 0005_workflow_runs")

    metadata = MetaData()
    job_rows: list[Any] = []
    if "job_records" in table_names and {"id", "type", "status", "payload_json"}.issubset(job_columns):
        jobs_table = Table("job_records", metadata, autoload_with=bind)
        ordering = [column for name in ("created_at", "id") if (column := jobs_table.c.get(name)) is not None]
        job_rows = list(
            session.execute(
                select(jobs_table.c.id, jobs_table.c.payload_json)
                .where(
                    jobs_table.c.type.in_(WORKFLOW_JOB_TYPES),
                    jobs_table.c.status.in_(ACTIVE_JOB_STATUSES),
                )
                .order_by(*ordering)
            ).all()
        )

    run_rows: list[Any] = []
    if "workflow_runs" in table_names:
        runs_table = Table("workflow_runs", metadata, autoload_with=bind)
        ordering = [column for name in ("created_at", "id") if (column := runs_table.c.get(name)) is not None]
        run_rows = list(
            session.execute(
                select(runs_table.c.id, runs_table.c.provider)
                .where(~runs_table.c.status.in_(TERMINAL_WORKFLOW_STATUSES))
                .order_by(*ordering)
            ).all()
        )

    job_counts: Counter[str] = Counter()
    run_counts: Counter[str] = Counter()
    blocking_job_ids: list[str] = []
    blocking_run_ids: list[str] = []
    unknown_job_ids: list[str] = []

    for job in job_rows:
        payload = _payload_dict(job.payload_json)
        value = str(payload.get("workflow_provider") or "").strip()
        provider = _audit_provider(value)
        if provider is None:
            job_counts["unknown"] += 1
            unknown_job_ids.append(job.id)
            blocking_job_ids.append(job.id)
            continue
        job_counts[provider] += 1
        if provider != AGENT_PROVIDER_LANGGRAPH:
            blocking_job_ids.append(job.id)

    for run in run_rows:
        provider = _audit_provider(run.provider) or "unknown"
        run_counts[provider] += 1
        if provider != AGENT_PROVIDER_LANGGRAPH:
            blocking_run_ids.append(run.id)

    return WorkflowDrainAudit(
        safe_to_remove_legacy_runtime=not schema_blockers and not blocking_job_ids and not blocking_run_ids,
        schema_ready_for_langgraph=not schema_blockers,
        schema_blockers=schema_blockers,
        active_jobs_by_provider=dict(sorted(job_counts.items())),
        active_runs_by_provider=dict(sorted(run_counts.items())),
        blocking_job_ids=blocking_job_ids,
        blocking_run_ids=blocking_run_ids,
        unknown_provider_job_ids=unknown_job_ids,
    )
