from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.trips import TripCreateRequest, TripItinerarySaveRequest, TripResponse, TripUpdateRequest
from travelmind_api.core.security import generate_identifier
from travelmind_api.db.models import CommunityPost, JobRecord, Trip, TripRefineSession, User
from travelmind_api.services.community_service import serialize_trip_community_post



def _validation_error(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": code, "message": message})



def _normalize_required_text(value: str, *, code: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise _validation_error(code, f"{label} cannot be empty")
    return normalized



def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip()


def _build_trip_title(*, origin: str, destination: str, locale: str | None) -> str:
    normalized_origin = (origin or "").strip()
    normalized_destination = (destination or "").strip()
    if not normalized_destination:
        return "Trip"
    if str(locale or "").lower().startswith("zh"):
        return f"{normalized_origin}出发去{normalized_destination}" if normalized_origin else f"{normalized_destination}行程"
    return f"{normalized_destination} trip from {normalized_origin}" if normalized_origin else f"{normalized_destination} Trip"



def _normalize_interests(interests: list[str] | None) -> list[str] | None:
    if interests is None:
        return None

    normalized: list[str] = []
    seen: set[str] = set()
    for interest in interests:
        candidate = interest.strip()
        if not candidate:
            continue
        dedupe_key = candidate.casefold()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(candidate)
    return normalized



def _validate_trip_dates(start_date: date, end_date: date) -> None:
    if start_date < date.today():
        raise _validation_error("invalid_trip_start_date", "start_date must be today or later")
    if end_date < start_date:
        raise _validation_error("invalid_trip_dates", "end_date must be on or after start_date")



def _reject_null_updates(updates: dict[str, object]) -> None:
    null_fields = [field for field, value in updates.items() if value is None]
    if not null_fields:
        return
    fields = ", ".join(sorted(null_fields))
    raise _validation_error("null_update_value", f"Null is not allowed for: {fields}")



def serialize_trip(trip: Trip, *, community_post: CommunityPost | None = None) -> TripResponse:
    return TripResponse(
        id=trip.id,
        user_id=trip.user_id,
        title=trip.title,
        origin=trip.origin,
        destination=trip.destination,
        start_date=trip.start_date,
        end_date=trip.end_date,
        budget=trip.budget,
        travelers=trip.travelers,
        interests=trip.interests or [],
        accommodation_preference=trip.accommodation_preference,
        pace=trip.pace,
        transport_mode=trip.transport_mode,
        created_at=trip.created_at,
        updated_at=trip.updated_at,
        itinerary=trip.itinerary_json,
        latest_agent_trace=trip.latest_agent_trace_json,
        community_post=serialize_trip_community_post(community_post, trip_updated_at=trip.updated_at) if community_post else None,
    )



def create_trip(session: Session, user: User, payload: TripCreateRequest) -> Trip:
    _validate_trip_dates(payload.start_date, payload.end_date)
    normalized_origin = _normalize_required_text(payload.origin, code="invalid_trip_origin", label="origin")
    normalized_destination = _normalize_required_text(payload.destination, code="invalid_trip_destination", label="destination")
    normalized_title = _normalize_optional_text(payload.title) or _build_trip_title(
        origin=normalized_origin,
        destination=normalized_destination,
        locale=getattr(user, "locale", None),
    )
    trip = Trip(
        id=generate_identifier("trip"),
        user_id=user.id,
        title=normalized_title,
        origin=normalized_origin,
        destination=normalized_destination,
        start_date=payload.start_date,
        end_date=payload.end_date,
        budget=payload.budget,
        travelers=payload.travelers,
        interests=_normalize_interests(payload.interests) or [],
        accommodation_preference=_normalize_optional_text(payload.accommodation_preference) or "",
        pace=_normalize_optional_text(payload.pace) or "balanced",
        transport_mode=_normalize_optional_text(payload.transport_mode) or "mixed",
    )
    session.add(trip)
    session.commit()
    session.refresh(trip)
    return trip



def list_trips(session: Session, user: User) -> list[Trip]:
    return list(session.scalars(select(Trip).where(Trip.user_id == user.id).order_by(Trip.created_at.desc())))



def get_trip_or_404(session: Session, user: User, trip_id: str) -> Trip:
    trip = session.scalar(select(Trip).where(Trip.id == trip_id, Trip.user_id == user.id))
    if not trip:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "trip_not_found", "message": "Trip not found"})
    return trip



def update_trip(session: Session, trip: Trip, payload: TripUpdateRequest) -> Trip:
    updates = payload.model_dump(exclude_unset=True)
    _reject_null_updates(updates)

    merged_start_date = updates.get("start_date", trip.start_date)
    merged_end_date = updates.get("end_date", trip.end_date)
    _validate_trip_dates(merged_start_date, merged_end_date)

    if "title" in updates:
        updates["title"] = _normalize_required_text(updates["title"], code="invalid_trip_title", label="title")
    if "origin" in updates:
        updates["origin"] = _normalize_required_text(updates["origin"], code="invalid_trip_origin", label="origin")
    if "destination" in updates:
        updates["destination"] = _normalize_required_text(updates["destination"], code="invalid_trip_destination", label="destination")
    if "accommodation_preference" in updates:
        updates["accommodation_preference"] = _normalize_optional_text(updates["accommodation_preference"]) or ""
    if "pace" in updates:
        updates["pace"] = _normalize_optional_text(updates["pace"]) or "balanced"
    if "transport_mode" in updates:
        updates["transport_mode"] = _normalize_optional_text(updates["transport_mode"]) or "mixed"
    if "interests" in updates:
        updates["interests"] = _normalize_interests(updates["interests"]) or []

    for field, value in updates.items():
        setattr(trip, field, value)
    session.add(trip)
    session.commit()
    session.refresh(trip)
    return trip



def delete_trip(session: Session, trip: Trip) -> None:
    session.query(JobRecord).filter(JobRecord.trip_id == trip.id, JobRecord.owner_user_id == trip.user_id).delete(synchronize_session=False)
    session.query(CommunityPost).filter(CommunityPost.trip_id == trip.id, CommunityPost.author_user_id == trip.user_id).delete(synchronize_session=False)
    session.query(TripRefineSession).filter(TripRefineSession.trip_id == trip.id, TripRefineSession.user_id == trip.user_id).delete(synchronize_session=False)
    session.delete(trip)
    session.commit()



def save_trip_itinerary(session: Session, trip: Trip, payload: TripItinerarySaveRequest) -> Trip:
    trip.itinerary_json = payload.itinerary
    if payload.latest_agent_trace is not None:
        trip.latest_agent_trace_json = payload.latest_agent_trace
    session.add(trip)
    session.commit()
    session.refresh(trip)
    return trip
