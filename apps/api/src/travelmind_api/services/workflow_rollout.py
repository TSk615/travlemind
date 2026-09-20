from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from travelmind_api.agents.provider import AGENT_PROVIDER_LANGGRAPH, normalize_agent_provider
from travelmind_api.db.models import JobRecord, WorkflowRun


ACTIVE_JOB_STATUSES = frozenset({"queued", "retrying", "running"})
TERMINAL_WORKFLOW_STATUSES = frozenset({"completed", "cancelled", "conflicted", "failed"})
WORKFLOW_JOB_TYPES = frozenset({"trip.generate", "trip.refine"})


@dataclass(frozen=True)
class WorkflowDrainAudit:
    safe_to_remove_legacy_runtime: bool
    active_jobs_by_provider: dict[str, int] = field(default_factory=dict)
    active_runs_by_provider: dict[str, int] = field(default_factory=dict)
    blocking_job_ids: list[str] = field(default_factory=list)
    blocking_run_ids: list[str] = field(default_factory=list)
    unknown_provider_job_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _job_provider(job: JobRecord) -> str | None:
    payload = job.payload_json if isinstance(job.payload_json, dict) else {}
    value = str(payload.get("workflow_provider") or "").strip()
    return normalize_agent_provider(value) if value else None


def audit_workflow_drain(session: Session) -> WorkflowDrainAudit:
    """Report whether this database contains work that still needs a legacy runtime.

    Unknown provider snapshots are deliberately blocking: jobs created by an
    older deployment may not have persisted their provider yet, so treating
    them as safe could strand queued work during dependency removal.
    """

    jobs = (
        session.query(JobRecord)
        .filter(
            JobRecord.type.in_(WORKFLOW_JOB_TYPES),
            JobRecord.status.in_(ACTIVE_JOB_STATUSES),
        )
        .order_by(JobRecord.created_at.asc(), JobRecord.id.asc())
        .all()
    )
    runs = (
        session.query(WorkflowRun)
        .filter(~WorkflowRun.status.in_(TERMINAL_WORKFLOW_STATUSES))
        .order_by(WorkflowRun.created_at.asc(), WorkflowRun.id.asc())
        .all()
    )

    job_counts: Counter[str] = Counter()
    run_counts: Counter[str] = Counter()
    blocking_job_ids: list[str] = []
    blocking_run_ids: list[str] = []
    unknown_job_ids: list[str] = []

    for job in jobs:
        provider = _job_provider(job)
        if provider is None:
            job_counts["unknown"] += 1
            unknown_job_ids.append(job.id)
            blocking_job_ids.append(job.id)
            continue
        job_counts[provider] += 1
        if provider != AGENT_PROVIDER_LANGGRAPH:
            blocking_job_ids.append(job.id)

    for run in runs:
        provider = normalize_agent_provider(run.provider)
        run_counts[provider] += 1
        if provider != AGENT_PROVIDER_LANGGRAPH:
            blocking_run_ids.append(run.id)

    return WorkflowDrainAudit(
        safe_to_remove_legacy_runtime=not blocking_job_ids and not blocking_run_ids,
        active_jobs_by_provider=dict(sorted(job_counts.items())),
        active_runs_by_provider=dict(sorted(run_counts.items())),
        blocking_job_ids=blocking_job_ids,
        blocking_run_ids=blocking_run_ids,
        unknown_provider_job_ids=unknown_job_ids,
    )
