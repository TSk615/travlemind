from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.common import success_response
from travelmind_api.api.schemas.jobs import ExportPdfRequest, ExportRequest
from travelmind_api.core.config import Settings, get_settings
from travelmind_api.core.database import get_db
from travelmind_api.core.deps import get_current_user
from travelmind_api.db.models import User
from travelmind_api.services.export_service import normalize_export_formats
from travelmind_api.services.job_service import create_job, dispatch_job, serialize_job
from travelmind_api.services.trip_service import get_trip_or_404

router = APIRouter(prefix="/exports", tags=["exports"])


@router.post("")
def export_trip_endpoint(
    payload: ExportRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
):
    trip = get_trip_or_404(db, current_user, payload.trip_id)
    job = create_job(
        db,
        job_type="export.pdf",
        owner_user_id=current_user.id,
        trip_id=trip.id,
        payload={"trip_id": trip.id, "formats": normalize_export_formats(payload.formats)},
    )
    dispatch_job(job.id, settings, background_tasks)
    return success_response(serialize_job(job).model_dump(mode="json"))


@router.post("/pdf")
def export_pdf_endpoint(
    payload: ExportPdfRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
):
    trip = get_trip_or_404(db, current_user, payload.trip_id)
    job = create_job(
        db,
        job_type="export.pdf",
        owner_user_id=current_user.id,
        trip_id=trip.id,
        payload={"trip_id": trip.id, "formats": ["pdf"]},
    )
    dispatch_job(job.id, settings, background_tasks)
    return success_response(serialize_job(job).model_dump(mode="json"))
