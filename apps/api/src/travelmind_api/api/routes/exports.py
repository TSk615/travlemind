from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.common import success_response
from travelmind_api.api.schemas.jobs import ExportPdfRequest, ExportRequest
from travelmind_api.core.config import Settings, get_settings
from travelmind_api.core.database import get_db
from travelmind_api.core.deps import get_current_user
from travelmind_api.db.models import User
from travelmind_api.services.export_service import normalize_export_formats, resolve_export_file_path
from travelmind_api.services.job_service import create_job, dispatch_job, get_job, serialize_job
from travelmind_api.services.trip_service import get_trip_or_404

router = APIRouter(prefix="/exports", tags=["exports"])


def _export_file_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "export_file_not_found", "message": "Export file not found"})


def _export_media_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".md":
        return "text/markdown; charset=utf-8"
    if suffix == ".json":
        return "application/json"
    if suffix == ".pdf":
        return "application/pdf"
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


@router.get("/files/{filename}")
def get_export_file(
    filename: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
):
    try:
        path = resolve_export_file_path(settings, filename)
    except ValueError as exc:
        raise _export_file_not_found() from exc

    job_id = Path(filename).stem
    if not get_job(db, job_id, current_user.id) or not path.is_file():
        raise _export_file_not_found()

    return FileResponse(path, media_type=_export_media_type(filename), filename=filename)


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
