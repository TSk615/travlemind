from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.common import success_response
from travelmind_api.api.schemas.refine_sessions import TripCommunityGuideAttachRequest, TripRefineMessageCreateRequest, TripUploadedGuideCreateRequest
from travelmind_api.api.schemas.trips import TripCreateRequest, TripIntakeChatRequest, TripItinerarySaveRequest, TripRefineRequest, TripUpdateRequest
from travelmind_api.core.config import Settings, get_settings
from travelmind_api.core.database import get_db
from travelmind_api.core.deps import get_current_user
from travelmind_api.db.models import User
from travelmind_api.services.community_service import get_trip_community_post_map
from travelmind_api.services.job_service import create_job, dispatch_job, serialize_job
from travelmind_api.services.refine_session_service import (
    add_uploaded_guide,
    append_refine_message,
    attach_community_source,
    delete_refine_session,
    ensure_refine_session_owns_source,
    get_or_create_refine_session,
    remove_community_source,
    remove_uploaded_guide,
    serialize_refine_session,
)
from travelmind_api.services.trip_intake_service import run_trip_intake_chat
from travelmind_api.services.trip_service import create_trip, delete_trip, get_trip_or_404, list_trips, save_trip_itinerary, serialize_trip, update_trip

router = APIRouter(prefix="/trips", tags=["trips"])


def _serialize_trip_payload(db: Session, current_user: User, trip):
    community_post = get_trip_community_post_map(db, author_user_id=current_user.id, trip_ids=[trip.id]).get(trip.id)
    return serialize_trip(trip, community_post=community_post).model_dump(mode="json")


@router.get("")
def get_trips(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    records = list_trips(db, current_user)
    community_posts = get_trip_community_post_map(db, author_user_id=current_user.id, trip_ids=[trip.id for trip in records])
    trips = [serialize_trip(trip, community_post=community_posts.get(trip.id)).model_dump(mode="json") for trip in records]
    return success_response(trips)


@router.post("")
def create_trip_endpoint(payload: TripCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    trip = create_trip(db, current_user, payload)
    return success_response(_serialize_trip_payload(db, current_user, trip))


@router.get("/{trip_id}")
def get_trip_endpoint(trip_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    trip = get_trip_or_404(db, current_user, trip_id)
    return success_response(_serialize_trip_payload(db, current_user, trip))


@router.patch("/{trip_id}")
def update_trip_endpoint(trip_id: str, payload: TripUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    trip = get_trip_or_404(db, current_user, trip_id)
    trip = update_trip(db, trip, payload)
    return success_response(_serialize_trip_payload(db, current_user, trip))


@router.delete("/{trip_id}")
def delete_trip_endpoint(trip_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    trip = get_trip_or_404(db, current_user, trip_id)
    delete_trip(db, trip)
    return success_response({"success": True, "trip_id": trip_id})


@router.put("/{trip_id}/itinerary")
def save_trip_itinerary_endpoint(
    trip_id: str,
    payload: TripItinerarySaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trip = get_trip_or_404(db, current_user, trip_id)
    trip = save_trip_itinerary(db, trip, payload)
    return success_response(_serialize_trip_payload(db, current_user, trip))


@router.get("/{trip_id}/refine-session")
def get_refine_session_endpoint(
    trip_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trip = get_trip_or_404(db, current_user, trip_id)
    record = get_or_create_refine_session(db, user=current_user, trip=trip)
    return success_response(serialize_refine_session(record).model_dump(mode="json"))


@router.delete("/{trip_id}/refine-session")
def delete_refine_session_endpoint(
    trip_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trip = get_trip_or_404(db, current_user, trip_id)
    record = get_or_create_refine_session(db, user=current_user, trip=trip)
    delete_refine_session(db, record=record)
    return success_response({"success": True, "trip_id": trip.id})


@router.post("/{trip_id}/refine-session/messages")
def append_refine_message_endpoint(
    trip_id: str,
    payload: TripRefineMessageCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trip = get_trip_or_404(db, current_user, trip_id)
    record = get_or_create_refine_session(db, user=current_user, trip=trip)
    record = append_refine_message(db, record=record, payload=payload)
    return success_response(serialize_refine_session(record).model_dump(mode="json"))


@router.post("/{trip_id}/refine-session/uploaded-guides")
def add_uploaded_guide_endpoint(
    trip_id: str,
    payload: TripUploadedGuideCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trip = get_trip_or_404(db, current_user, trip_id)
    record = get_or_create_refine_session(db, user=current_user, trip=trip)
    record = add_uploaded_guide(db, record=record, payload=payload)
    return success_response(serialize_refine_session(record).model_dump(mode="json"))


@router.delete("/{trip_id}/refine-session/uploaded-guides/{source_id}")
def remove_uploaded_guide_endpoint(
    trip_id: str,
    source_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trip = get_trip_or_404(db, current_user, trip_id)
    record = get_or_create_refine_session(db, user=current_user, trip=trip)
    ensure_refine_session_owns_source(record, source_id, source_type="uploaded")
    record = remove_uploaded_guide(db, record=record, source_id=source_id)
    return success_response(serialize_refine_session(record).model_dump(mode="json"))


@router.post("/{trip_id}/refine-session/community-sources")
def attach_community_source_endpoint(
    trip_id: str,
    payload: TripCommunityGuideAttachRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trip = get_trip_or_404(db, current_user, trip_id)
    record = get_or_create_refine_session(db, user=current_user, trip=trip)
    record = attach_community_source(db, record=record, payload=payload)
    return success_response(serialize_refine_session(record).model_dump(mode="json"))


@router.delete("/{trip_id}/refine-session/community-sources/{source_id}")
def remove_community_source_endpoint(
    trip_id: str,
    source_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trip = get_trip_or_404(db, current_user, trip_id)
    record = get_or_create_refine_session(db, user=current_user, trip=trip)
    ensure_refine_session_owns_source(record, source_id, source_type="community")
    record = remove_community_source(db, record=record, source_id=source_id)
    return success_response(serialize_refine_session(record).model_dump(mode="json"))




@router.post("/intake/chat")
def trip_intake_chat_endpoint(
    payload: TripIntakeChatRequest,
    current_user: User = Depends(get_current_user),
):
    result = run_trip_intake_chat(
        user=current_user,
        draft_payload=payload.draft.model_dump(mode="json"),
        messages=[message.model_dump(mode="json") for message in payload.messages],
        user_message=payload.user_message,
    )
    return success_response(result)

@router.post("/{trip_id}/generate")
def generate_trip_endpoint(
    trip_id: str,
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
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
        idempotency_key=idempotency_key,
    )
    dispatch_job(job.id, settings, background_tasks)
    return success_response(serialize_job(job).model_dump(mode="json"))


@router.post("/{trip_id}/refine")
def refine_trip_endpoint(
    trip_id: str,
    payload: TripRefineRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
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
        idempotency_key=idempotency_key,
    )
    dispatch_job(job.id, settings, background_tasks)
    return success_response(serialize_job(job).model_dump(mode="json"))


@router.post("/{trip_id}/images/enrich")
def enrich_trip_images_endpoint(
    trip_id: str,
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
):
    trip = get_trip_or_404(db, current_user, trip_id)
    if not trip.itinerary_json:
        raise HTTPException(status_code=400, detail={"code": "trip_itinerary_required", "message": "Generate itinerary before enriching images"})
    job = create_job(
        db,
        job_type="trip.image_enrich",
        owner_user_id=current_user.id,
        trip_id=trip.id,
        payload={"trip_id": trip.id},
        idempotency_key=idempotency_key,
    )
    dispatch_job(job.id, settings, background_tasks)
    return success_response(serialize_job(job).model_dump(mode="json"))
