from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.common import success_response
from travelmind_api.core.config import Settings, get_settings
from travelmind_api.core.database import SessionLocal, get_db
from travelmind_api.core.deps import get_current_user
from travelmind_api.db.models import User, WorkflowRun
from travelmind_api.services.job_service import TERMINAL_JOB_STATUSES, checkpoint_repair_exhausted, cancel_job, create_job, dispatch_job, extract_resume_checkpoint, extract_workflow_run_id, get_job, serialize_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _job_not_found_exception() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "job_not_found", "message": "Job not found"})


@router.get("/{job_id}")
def get_job_endpoint(job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = get_job(db, job_id, current_user.id)
    if not job:
        raise _job_not_found_exception()
    return success_response(serialize_job(job).model_dump(mode="json"))


@router.post("/{job_id}/retry")
def retry_failed_job_endpoint(
    job_id: str,
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
):
    job = get_job(db, job_id, current_user.id)
    if not job:
        raise _job_not_found_exception()
    if job.type != "trip.generate":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "job_retry_unsupported", "message": "Only failed trip generation jobs can be retried from a checkpoint."},
        )
    if job.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "job_not_failed", "message": "Only failed jobs can be retried from the last failed node."},
        )
    if checkpoint_repair_exhausted(job):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "job_resume_repair_exhausted",
                "message": "这次任务的修复次数已用完，无法从旧进度继续。请重新生成行程；此次请求不会扣减体验次数。",
            },
        )
    checkpoint = extract_resume_checkpoint(job)
    workflow_run_id = extract_workflow_run_id(job)
    workflow_run = db.get(WorkflowRun, workflow_run_id) if workflow_run_id else None
    if workflow_run is not None and (
        workflow_run.owner_user_id != current_user.id or workflow_run.trip_id != job.trip_id
    ):
        workflow_run = None
    if checkpoint is None and workflow_run is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "job_resume_checkpoint_missing", "message": "This failed job does not have a resume checkpoint. Start a new generation instead."},
        )
    if not job.trip_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "job_trip_missing", "message": "Cannot retry a generation job without an associated trip."},
        )

    source_payload = job.payload_json if isinstance(job.payload_json, dict) else {}
    retry_payload = {
        key: value
        for key, value in source_payload.items()
        if key not in {"resume_checkpoint", "resume_from_job_id"}
    }
    retry_payload.update({"trip_id": job.trip_id, "resume_from_job_id": job.id})
    if workflow_run is not None:
        retry_payload.update(
            {
                "workflow_run_id": workflow_run.id,
                "workflow_provider": workflow_run.provider,
                "workflow_graph_version": workflow_run.graph_version,
                "workflow_state_schema_version": workflow_run.state_schema_version,
            }
        )
    elif checkpoint is not None:
        retry_payload["resume_checkpoint"] = checkpoint
    retry_job = create_job(
        db,
        job_type="trip.generate",
        owner_user_id=current_user.id,
        trip_id=job.trip_id,
        payload=retry_payload,
        idempotency_key=idempotency_key,
        commit=False,
    )
    if workflow_run is not None:
        retry_job.workflow_run_id = workflow_run.id
        workflow_run.current_job_id = retry_job.id
        db.add(retry_job)
        db.add(workflow_run)
    db.commit()
    db.refresh(retry_job)
    dispatch_job(retry_job.id, settings, background_tasks)
    return success_response(serialize_job(retry_job).model_dump(mode="json"))


@router.post("/{job_id}/cancel")
def cancel_job_endpoint(job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = cancel_job(db, job_id, current_user.id)
    if not job:
        raise _job_not_found_exception()
    db.commit()
    db.refresh(job)
    return success_response(serialize_job(job).model_dump(mode="json"))


@router.get("/{job_id}/stream")
async def stream_job_endpoint(job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    owner_user_id = current_user.id
    if not get_job(db, job_id, owner_user_id):
        raise _job_not_found_exception()

    async def event_stream():
        while True:
            with SessionLocal() as session:
                job = get_job(session, job_id, owner_user_id)
                if not job:
                    break
                payload = success_response(serialize_job(job).model_dump(mode="json"), meta={"stream": True}).model_dump(mode="json")
            yield f"data: {json.dumps(payload)}\n\n"
            if job.status in TERMINAL_JOB_STATUSES:
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
