from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.community import CommunityPostDetail, CommunityPostSummary, CommunityTripSnapshot
from travelmind_api.api.schemas.trips import CommunityTripPublicationState
from travelmind_api.core.security import generate_identifier
from travelmind_api.db.models import CommunityPost, Trip, User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_datetime(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _validation_error(code: str, message: str, *, status_code: int = status.HTTP_422_UNPROCESSABLE_CONTENT) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _community_snapshot_from_trip(trip: Trip) -> dict[str, object]:
    itinerary = trip.itinerary_json or {}
    return {
        "title": trip.title,
        "origin": trip.origin,
        "destination": trip.destination,
        "start_date": trip.start_date.isoformat(),
        "end_date": trip.end_date.isoformat(),
        "budget": trip.budget,
        "travelers": trip.travelers,
        "interests": list(trip.interests or []),
        "accommodation_preference": trip.accommodation_preference,
        "pace": trip.pace,
        "transport_mode": trip.transport_mode,
        "itinerary": itinerary,
    }


def _extract_cover_image_url(trip: Trip) -> str | None:
    itinerary = trip.itinerary_json or {}
    for day in itinerary.get("days") or []:
        if not isinstance(day, dict):
            continue
        for item in day.get("items") or []:
            if not isinstance(item, dict):
                continue
            image_urls = item.get("image_urls") or []
            if isinstance(image_urls, list):
                for url in image_urls:
                    candidate = str(url or "").strip()
                    if candidate:
                        return candidate
    return None


def _coerce_snapshot(snapshot_json: dict[str, object]) -> CommunityTripSnapshot:
    return CommunityTripSnapshot.model_validate(snapshot_json)


def is_trip_community_post_stale(*, trip_updated_at: datetime, source_trip_updated_at: datetime) -> bool:
    return _normalize_datetime(trip_updated_at) > _normalize_datetime(source_trip_updated_at)


def serialize_trip_community_post(record: CommunityPost, *, trip_updated_at: datetime) -> CommunityTripPublicationState:
    return CommunityTripPublicationState(
        post_id=record.id,
        published_at=record.published_at,
        updated_at=record.updated_at,
        source_trip_updated_at=record.source_trip_updated_at,
        is_stale=is_trip_community_post_stale(
            trip_updated_at=trip_updated_at,
            source_trip_updated_at=record.source_trip_updated_at,
        ),
    )


def serialize_community_post_summary(record: CommunityPost, *, author_name: str) -> CommunityPostSummary:
    snapshot = _coerce_snapshot(record.snapshot_json or {})
    return CommunityPostSummary(
        id=record.id,
        title=record.title,
        destination=record.destination,
        share_note=record.share_note,
        cover_image_url=record.cover_image_url,
        author_name=author_name,
        published_at=record.published_at,
        updated_at=record.updated_at,
        start_date=snapshot.start_date,
        end_date=snapshot.end_date,
        budget=snapshot.budget,
        travelers=snapshot.travelers,
        interests=snapshot.interests,
        itinerary_summary=snapshot.itinerary.summary,
        day_count=len(snapshot.itinerary.days),
    )


def serialize_community_post_detail(record: CommunityPost, *, author_name: str) -> CommunityPostDetail:
    return CommunityPostDetail(
        id=record.id,
        title=record.title,
        destination=record.destination,
        share_note=record.share_note,
        cover_image_url=record.cover_image_url,
        author_name=author_name,
        published_at=record.published_at,
        updated_at=record.updated_at,
        snapshot=_coerce_snapshot(record.snapshot_json or {}),
    )


def get_trip_community_post_map(session: Session, *, author_user_id: str, trip_ids: list[str]) -> dict[str, CommunityPost]:
    normalized_trip_ids = [trip_id for trip_id in trip_ids if trip_id]
    if not normalized_trip_ids:
        return {}
    query = select(CommunityPost).where(
        CommunityPost.author_user_id == author_user_id,
        CommunityPost.trip_id.in_(normalized_trip_ids),
    )
    return {record.trip_id: record for record in session.scalars(query)}


def list_published_community_posts(session: Session) -> list[tuple[CommunityPost, str]]:
    query = (
        select(CommunityPost, User.name)
        .join(User, User.id == CommunityPost.author_user_id)
        .order_by(desc(CommunityPost.published_at))
    )
    return [(record, author_name) for record, author_name in session.execute(query).all()]


def get_published_community_post_or_404(session: Session, post_id: str) -> tuple[CommunityPost, str]:
    result = session.execute(
        select(CommunityPost, User.name)
        .join(User, User.id == CommunityPost.author_user_id)
        .where(CommunityPost.id == post_id)
    ).first()
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "community_post_not_found", "message": "Community post not found"},
        )
    return result


def get_owned_community_post_or_404(session: Session, user: User, post_id: str) -> CommunityPost:
    record = session.scalar(
        select(CommunityPost).where(CommunityPost.id == post_id, CommunityPost.author_user_id == user.id)
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "community_post_not_found", "message": "Community post not found"},
        )
    return record


def create_community_post(session: Session, *, user: User, trip: Trip, share_note: str) -> CommunityPost:
    if not trip.itinerary_json:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "trip_itinerary_required", "message": "Generate itinerary before publishing to community"},
        )

    existing = session.scalar(select(CommunityPost).where(CommunityPost.trip_id == trip.id))
    if existing is not None:
        raise _validation_error(
            "community_post_exists",
            "This trip already has a published community post",
            status_code=status.HTTP_409_CONFLICT,
        )

    record = CommunityPost(
        id=generate_identifier("post"),
        trip_id=trip.id,
        author_user_id=user.id,
        title=trip.title,
        destination=trip.destination,
        share_note=share_note,
        cover_image_url=_extract_cover_image_url(trip),
        snapshot_json=_community_snapshot_from_trip(trip),
        published_at=_utcnow(),
        updated_at=_utcnow(),
        source_trip_updated_at=_normalize_datetime(trip.updated_at),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def update_community_post_share_note(session: Session, *, record: CommunityPost, share_note: str) -> CommunityPost:
    record.share_note = share_note
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def refresh_community_post_from_trip(
    session: Session,
    *,
    record: CommunityPost,
    trip: Trip,
    share_note: str | None = None,
) -> CommunityPost:
    if not trip.itinerary_json:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "trip_itinerary_required", "message": "Generate itinerary before publishing to community"},
        )

    record.title = trip.title
    record.destination = trip.destination
    record.cover_image_url = _extract_cover_image_url(trip)
    record.snapshot_json = _community_snapshot_from_trip(trip)
    record.source_trip_updated_at = _normalize_datetime(trip.updated_at)
    if share_note is not None:
        record.share_note = share_note
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def delete_community_post(session: Session, *, record: CommunityPost) -> None:
    session.delete(record)
    session.commit()
