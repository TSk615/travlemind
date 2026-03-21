from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.common import success_response
from travelmind_api.api.schemas.trips import TripCreateRequest, TripItinerarySaveRequest, TripRefineRequest, TripUpdateRequest
from travelmind_api.core.config import Settings, get_settings
from travelmind_api.core.database import get_db
from travelmind_api.core.deps import get_current_user
from travelmind_api.db.models import User
from travelmind_api.services.job_service import create_job, dispatch_job, serialize_job
from travelmind_api.services.trip_service import create_trip, get_trip_or_404, list_trips, save_trip_itinerary, serialize_trip, update_trip

router = APIRouter(prefix="/trips", tags=["trips"])


@router.get("")
def get_trips(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    trips = [serialize_trip(trip).model_dump(mode="json") for trip in list_trips(db, current_user)]
    return success_response(trips)


@router.post("")
def create_trip_endpoint(payload: TripCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    trip = create_trip(db, current_user, payload)
    return success_response(serialize_trip(trip).model_dump(mode="json"))


@router.get("/{trip_id}")
def get_trip_endpoint(trip_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    trip = get_trip_or_404(db, current_user, trip_id)
    return success_response(serialize_trip(trip).model_dump(mode="json"))


@router.patch("/{trip_id}")
def update_trip_endpoint(trip_id: str, payload: TripUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    trip = get_trip_or_404(db, current_user, trip_id)
    trip = update_trip(db, trip, payload)
    return success_response(serialize_trip(trip).model_dump(mode="json"))


@router.put("/{trip_id}/itinerary")
def save_trip_itinerary_endpoint(
    trip_id: str,
    payload: TripItinerarySaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trip = get_trip_or_404(db, current_user, trip_id)
    trip = save_trip_itinerary(db, trip, payload)
    return success_response(serialize_trip(trip).model_dump(mode="json"))


@router.post("/{trip_id}/generate")
def generate_trip_endpoint(
    trip_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
):
    trip = get_trip_or_404(db, current_user, trip_id)
    job = create_job(
        db,
        job_type="trip.generate",
        owner_user_id=current_user.id,
        trip_id=trip.id,
        payload={"trip_id": trip.id},
    )
    dispatch_job(job.id, settings, background_tasks)
    return success_response(serialize_job(job).model_dump(mode="json"))


@router.post("/{trip_id}/refine")
def refine_trip_endpoint(
    trip_id: str,
    payload: TripRefineRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
):
    trip = get_trip_or_404(db, current_user, trip_id)
    job = create_job(
        db,
        job_type="trip.refine",
        owner_user_id=current_user.id,
        trip_id=trip.id,
        payload={
            "trip_id": trip.id,
            "instruction": payload.instruction,
            "scope": payload.scope,
            "day_index": payload.day_index,
        },
    )
    dispatch_job(job.id, settings, background_tasks)
    return success_response(serialize_job(job).model_dump(mode="json"))