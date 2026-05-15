from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.common import success_response
from travelmind_api.core.database import SessionLocal, get_db
from travelmind_api.core.deps import get_current_user
from travelmind_api.db.models import User
from travelmind_api.services.job_service import TERMINAL_JOB_STATUSES, get_job, serialize_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _job_not_found_exception() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "job_not_found", "message": "Job not found"})


@router.get("/{job_id}")
def get_job_endpoint(job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = get_job(db, job_id, current_user.id)
    if not job:
        raise _job_not_found_exception()
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
