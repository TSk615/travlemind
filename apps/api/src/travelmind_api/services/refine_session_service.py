from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.refine_sessions import (
    TripCommunityGuideAttachRequest,
    TripRefineMessageCreateRequest,
    TripRefineSessionResponse,
    TripUploadedGuideCreateRequest,
)
from travelmind_api.core.security import generate_identifier
from travelmind_api.db.models import CommunityPost, Trip, TripRefineSession, User
from travelmind_api.services.community_service import get_published_community_post_or_404


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_datetime(value: datetime) -> str:
    return value.isoformat()


def _touch(record: TripRefineSession) -> None:
    record.updated_at = _utcnow()


def get_or_create_refine_session(session: Session, *, user: User, trip: Trip) -> TripRefineSession:
    record = session.scalar(
        select(TripRefineSession).where(
            TripRefineSession.trip_id == trip.id,
            TripRefineSession.user_id == user.id,
        )
    )
    if record is not None:
        return record

    record = TripRefineSession(
        id=generate_identifier("trs"),
        trip_id=trip.id,
        user_id=user.id,
        messages_json=[],
        uploaded_guides_json=[],
        community_sources_json=[],
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def serialize_refine_session(record: TripRefineSession) -> TripRefineSessionResponse:
    return TripRefineSessionResponse(
        id=record.id,
        trip_id=record.trip_id,
        messages=list(record.messages_json or []),
        uploaded_guides=list(record.uploaded_guides_json or []),
        community_sources=list(record.community_sources_json or []),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def append_refine_message(
    session: Session,
    *,
    record: TripRefineSession,
    payload: TripRefineMessageCreateRequest,
) -> TripRefineSession:
    messages = list(record.messages_json or [])
    messages.append(
        {
            "id": generate_identifier("msg"),
            "role": payload.role,
            "text": payload.text,
            "created_at": _json_datetime(_utcnow()),
        }
    )
    record.messages_json = messages[-40:]
    _touch(record)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def add_uploaded_guide(
    session: Session,
    *,
    record: TripRefineSession,
    payload: TripUploadedGuideCreateRequest,
) -> TripRefineSession:
    uploaded_guides = list(record.uploaded_guides_json or [])
    uploaded_guides.append(
        {
            "id": generate_identifier("guide"),
            "title": payload.title,
            "content": payload.content,
            "source_type": payload.source_type,
            "original_filename": payload.original_filename,
            "created_at": _json_datetime(_utcnow()),
        }
    )
    record.uploaded_guides_json = uploaded_guides[-12:]
    _touch(record)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def remove_uploaded_guide(
    session: Session,
    *,
    record: TripRefineSession,
    source_id: str,
) -> TripRefineSession:
    record.uploaded_guides_json = [source for source in list(record.uploaded_guides_json or []) if source.get("id") != source_id]
    _touch(record)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def attach_community_source(
    session: Session,
    *,
    record: TripRefineSession,
    payload: TripCommunityGuideAttachRequest,
) -> TripRefineSession:
    post, author_name = get_published_community_post_or_404(session, payload.post_id)
    community_sources = [source for source in list(record.community_sources_json or []) if source.get("post_id") != post.id]
    community_sources.append(_community_source_payload(post, author_name=author_name))
    record.community_sources_json = community_sources[-12:]
    _touch(record)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def remove_community_source(
    session: Session,
    *,
    record: TripRefineSession,
    source_id: str,
) -> TripRefineSession:
    record.community_sources_json = [source for source in list(record.community_sources_json or []) if source.get("id") != source_id]
    _touch(record)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def delete_refine_session(session: Session, *, record: TripRefineSession) -> None:
    session.delete(record)
    session.commit()


def _community_source_payload(post: CommunityPost, *, author_name: str) -> dict[str, Any]:
    snapshot = dict(post.snapshot_json or {})
    itinerary = snapshot.get("itinerary") if isinstance(snapshot.get("itinerary"), dict) else {}
    summary = str(itinerary.get("summary") or "").strip()
    if not summary:
        summary = str(post.share_note or "").strip() or "Community itinerary reference."
    return {
        "id": generate_identifier("csrc"),
        "post_id": post.id,
        "title": post.title,
        "destination": post.destination,
        "author_name": author_name,
        "share_note": post.share_note,
        "itinerary_summary": summary,
        "snapshot": snapshot,
        "created_at": _json_datetime(_utcnow()),
    }


def ensure_refine_session_owns_source(record: TripRefineSession, source_id: str, *, source_type: str) -> None:
    if source_type == "uploaded":
        sources = record.uploaded_guides_json or []
    elif source_type == "community":
        sources = record.community_sources_json or []
    else:
        sources = []
    if not any(source.get("id") == source_id for source in sources):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "refine_source_not_found", "message": "Refine source not found"},
        )
