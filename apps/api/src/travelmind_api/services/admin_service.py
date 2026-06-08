from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.admin import (
    AdminCommunityPostDetail,
    AdminCommunityPostSummary,
    AdminJobDetail,
    AdminJobSummary,
    AdminOwnerSummary,
    AdminPageResponse,
    AdminTripDetail,
    AdminTripSummary,
    AdminUserDetail,
    AdminUserSummary,
)
from travelmind_api.core.config import Settings
from travelmind_api.core.security import generate_identifier
from travelmind_api.db.models import AdminAuditLog, CommunityPost, JobRecord, RefreshSession, Trip, User
from travelmind_api.services.auth_service import is_admin_user
from travelmind_api.services.community_service import is_trip_community_post_stale
from travelmind_api.services.trip_service import delete_trip


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_query(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _page_values(page: int, page_size: int) -> tuple[int, int]:
    return max(1, int(page or 1)), min(100, max(1, int(page_size or 20)))


def _paginate(session: Session, query: Select, *, page: int, page_size: int) -> tuple[list[Any], int, int, int]:
    normalized_page, normalized_page_size = _page_values(page, page_size)
    count_query = select(func.count()).select_from(query.order_by(None).subquery())
    total = int(session.scalar(count_query) or 0)
    items = session.execute(
        query.limit(normalized_page_size).offset((normalized_page - 1) * normalized_page_size)
    ).all()
    return items, normalized_page, normalized_page_size, total


def _owner_summary(user: User | None, settings: Settings) -> AdminOwnerSummary | None:
    if user is None:
        return None
    return AdminOwnerSummary(
        id=user.id,
        email=user.email,
        name=user.name,
        is_admin=is_admin_user(user, settings),
        disabled_at=user.disabled_at,
    )


def _user_counts(session: Session, user_ids: list[str]) -> dict[str, dict[str, int]]:
    if not user_ids:
        return {}
    counts = {user_id: {"trip_count": 0, "community_post_count": 0, "job_count": 0} for user_id in user_ids}
    for user_id, value in session.execute(
        select(Trip.user_id, func.count(Trip.id)).where(Trip.user_id.in_(user_ids)).group_by(Trip.user_id)
    ):
        counts[user_id]["trip_count"] = int(value)
    for user_id, value in session.execute(
        select(CommunityPost.author_user_id, func.count(CommunityPost.id))
        .where(CommunityPost.author_user_id.in_(user_ids))
        .group_by(CommunityPost.author_user_id)
    ):
        counts[user_id]["community_post_count"] = int(value)
    for user_id, value in session.execute(
        select(JobRecord.owner_user_id, func.count(JobRecord.id))
        .where(JobRecord.owner_user_id.in_(user_ids))
        .group_by(JobRecord.owner_user_id)
    ):
        counts[user_id]["job_count"] = int(value)
    return counts


def serialize_admin_user_summary(user: User, settings: Settings, counts: dict[str, int] | None = None) -> AdminUserSummary:
    counts = counts or {}
    return AdminUserSummary(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar=user.avatar,
        locale=user.locale,
        created_at=user.created_at,
        is_admin=is_admin_user(user, settings),
        disabled_at=user.disabled_at,
        disabled_reason=user.disabled_reason,
        trip_count=int(counts.get("trip_count", 0)),
        community_post_count=int(counts.get("community_post_count", 0)),
        job_count=int(counts.get("job_count", 0)),
    )


def serialize_admin_user_detail(session: Session, user: User, settings: Settings) -> AdminUserDetail:
    counts = _user_counts(session, [user.id]).get(user.id, {})
    summary = serialize_admin_user_summary(user, settings, counts)
    return AdminUserDetail(
        **summary.model_dump(),
        xhs_source_enabled=bool(user.xhs_source_enabled),
        has_llm_api_key=bool(user.llm_api_key),
        has_search_api_key=bool(user.search_service_api_key),
        has_image_api_key=bool(user.image_api_key),
    )


def _audit(
    session: Session,
    *,
    admin: User,
    action: str,
    target_type: str,
    target_id: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        AdminAuditLog(
            id=generate_identifier("aud"),
            admin_user_id=admin.id,
            admin_email_snapshot=admin.email,
            action=action,
            target_type=target_type,
            target_id=target_id,
            reason=reason,
            details_json=details or {},
        )
    )


def _get_user_or_404(session: Session, user_id: str) -> User:
    user = session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "admin_user_not_found", "message": "User not found"})
    return user


def list_admin_users(
    session: Session,
    settings: Settings,
    *,
    page: int = 1,
    page_size: int = 20,
    query: str | None = None,
    status_filter: str = "all",
    admin_only: bool = False,
) -> AdminPageResponse:
    stmt = select(User)
    normalized_query = _normalize_query(query)
    if normalized_query:
        like = f"%{normalized_query.lower()}%"
        stmt = stmt.where(or_(func.lower(User.email).like(like), func.lower(User.name).like(like)))
    if status_filter == "active":
        stmt = stmt.where(User.disabled_at.is_(None))
    elif status_filter == "disabled":
        stmt = stmt.where(User.disabled_at.is_not(None))
    elif status_filter != "all":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": "invalid_user_status", "message": "status must be active, disabled, or all"})
    if admin_only:
        admin_emails = sorted(settings.normalized_admin_emails)
        stmt = stmt.where(func.lower(User.email).in_(admin_emails or [""]))
    stmt = stmt.order_by(User.created_at.desc())

    rows, normalized_page, normalized_page_size, total = _paginate(session, stmt, page=page, page_size=page_size)
    users = [row[0] for row in rows]
    counts = _user_counts(session, [user.id for user in users])
    return AdminPageResponse(
        items=[serialize_admin_user_summary(user, settings, counts.get(user.id, {})).model_dump(mode="json") for user in users],
        page=normalized_page,
        page_size=normalized_page_size,
        total=total,
    )


def get_admin_user_detail(session: Session, settings: Settings, user_id: str) -> AdminUserDetail:
    return serialize_admin_user_detail(session, _get_user_or_404(session, user_id), settings)


def disable_admin_user(session: Session, settings: Settings, *, admin: User, user_id: str, reason: str) -> AdminUserDetail:
    user = _get_user_or_404(session, user_id)
    if user.id == admin.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "cannot_disable_self", "message": "Administrators cannot disable their own account"})
    if user.disabled_at is None:
        user.disabled_at = _utcnow()
    user.disabled_reason = reason
    session.query(RefreshSession).filter(RefreshSession.user_id == user.id).delete(synchronize_session=False)
    _audit(
        session,
        admin=admin,
        action="user.disable",
        target_type="user",
        target_id=user.id,
        reason=reason,
        details={"email": user.email},
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return serialize_admin_user_detail(session, user, settings)


def enable_admin_user(session: Session, settings: Settings, *, admin: User, user_id: str, reason: str) -> AdminUserDetail:
    user = _get_user_or_404(session, user_id)
    user.disabled_at = None
    user.disabled_reason = None
    _audit(
        session,
        admin=admin,
        action="user.enable",
        target_type="user",
        target_id=user.id,
        reason=reason,
        details={"email": user.email},
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return serialize_admin_user_detail(session, user, settings)


def _trip_summary(trip: Trip, owner: User | None, settings: Settings, community_post_id: str | None) -> AdminTripSummary:
    return AdminTripSummary(
        id=trip.id,
        user_id=trip.user_id,
        owner=_owner_summary(owner, settings),
        title=trip.title,
        origin=trip.origin,
        destination=trip.destination,
        start_date=trip.start_date,
        end_date=trip.end_date,
        budget=trip.budget,
        travelers=trip.travelers,
        created_at=trip.created_at,
        updated_at=trip.updated_at,
        has_itinerary=bool(trip.itinerary_json),
        has_community_post=bool(community_post_id),
    )


def list_admin_trips(
    session: Session,
    settings: Settings,
    *,
    page: int = 1,
    page_size: int = 20,
    query: str | None = None,
    owner_id: str | None = None,
    destination: str | None = None,
    has_itinerary: bool | None = None,
    has_community_post: bool | None = None,
) -> AdminPageResponse:
    stmt = select(Trip, User, CommunityPost.id).join(User, User.id == Trip.user_id).outerjoin(CommunityPost, CommunityPost.trip_id == Trip.id)
    normalized_query = _normalize_query(query)
    if normalized_query:
        like = f"%{normalized_query.lower()}%"
        stmt = stmt.where(or_(func.lower(Trip.title).like(like), func.lower(Trip.destination).like(like), func.lower(User.email).like(like), func.lower(User.name).like(like)))
    if owner_id:
        stmt = stmt.where(Trip.user_id == owner_id)
    normalized_destination = _normalize_query(destination)
    if normalized_destination:
        stmt = stmt.where(func.lower(Trip.destination).like(f"%{normalized_destination.lower()}%"))
    if has_itinerary is True:
        stmt = stmt.where(Trip.itinerary_json.is_not(None))
    elif has_itinerary is False:
        stmt = stmt.where(Trip.itinerary_json.is_(None))
    if has_community_post is True:
        stmt = stmt.where(CommunityPost.id.is_not(None))
    elif has_community_post is False:
        stmt = stmt.where(CommunityPost.id.is_(None))
    stmt = stmt.order_by(Trip.created_at.desc())

    rows, normalized_page, normalized_page_size, total = _paginate(session, stmt, page=page, page_size=page_size)
    return AdminPageResponse(
        items=[_trip_summary(trip, owner, settings, post_id).model_dump(mode="json") for trip, owner, post_id in rows],
        page=normalized_page,
        page_size=normalized_page_size,
        total=total,
    )


def get_admin_trip_detail(session: Session, settings: Settings, trip_id: str) -> AdminTripDetail:
    row = session.execute(
        select(Trip, User, CommunityPost.id)
        .join(User, User.id == Trip.user_id)
        .outerjoin(CommunityPost, CommunityPost.trip_id == Trip.id)
        .where(Trip.id == trip_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "admin_trip_not_found", "message": "Trip not found"})
    trip, owner, post_id = row
    summary = _trip_summary(trip, owner, settings, post_id)
    return AdminTripDetail(
        **summary.model_dump(),
        interests=trip.interests or [],
        accommodation_preference=trip.accommodation_preference,
        pace=trip.pace,
        transport_mode=trip.transport_mode,
        itinerary=trip.itinerary_json,
        latest_agent_trace=trip.latest_agent_trace_json,
    )


def delete_admin_trip(session: Session, *, admin: User, trip_id: str, reason: str) -> dict[str, Any]:
    trip = session.scalar(select(Trip).where(Trip.id == trip_id))
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "admin_trip_not_found", "message": "Trip not found"})
    details = {"title": trip.title, "user_id": trip.user_id, "destination": trip.destination}
    _audit(session, admin=admin, action="trip.delete", target_type="trip", target_id=trip.id, reason=reason, details=details)
    delete_trip(session, trip)
    return {"success": True, "trip_id": trip_id}


def _community_summary(record: CommunityPost, author: User | None, trip: Trip | None, settings: Settings) -> AdminCommunityPostSummary:
    return AdminCommunityPostSummary(
        id=record.id,
        trip_id=record.trip_id,
        author_user_id=record.author_user_id,
        author=_owner_summary(author, settings),
        title=record.title,
        destination=record.destination,
        share_note=record.share_note,
        cover_image_url=record.cover_image_url,
        published_at=record.published_at,
        updated_at=record.updated_at,
        source_trip_updated_at=record.source_trip_updated_at,
        is_stale=is_trip_community_post_stale(trip_updated_at=trip.updated_at, source_trip_updated_at=record.source_trip_updated_at) if trip is not None else False,
    )


def list_admin_community_posts(
    session: Session,
    settings: Settings,
    *,
    page: int = 1,
    page_size: int = 20,
    query: str | None = None,
    author_id: str | None = None,
    destination: str | None = None,
    stale_only: bool = False,
) -> AdminPageResponse:
    stmt = select(CommunityPost, User, Trip).join(User, User.id == CommunityPost.author_user_id).outerjoin(Trip, Trip.id == CommunityPost.trip_id)
    normalized_query = _normalize_query(query)
    if normalized_query:
        like = f"%{normalized_query.lower()}%"
        stmt = stmt.where(or_(func.lower(CommunityPost.title).like(like), func.lower(CommunityPost.destination).like(like), func.lower(User.email).like(like), func.lower(User.name).like(like)))
    if author_id:
        stmt = stmt.where(CommunityPost.author_user_id == author_id)
    normalized_destination = _normalize_query(destination)
    if normalized_destination:
        stmt = stmt.where(func.lower(CommunityPost.destination).like(f"%{normalized_destination.lower()}%"))
    if stale_only:
        stmt = stmt.where(Trip.updated_at > CommunityPost.source_trip_updated_at)
    stmt = stmt.order_by(CommunityPost.published_at.desc())

    rows, normalized_page, normalized_page_size, total = _paginate(session, stmt, page=page, page_size=page_size)
    return AdminPageResponse(
        items=[_community_summary(record, author, trip, settings).model_dump(mode="json") for record, author, trip in rows],
        page=normalized_page,
        page_size=normalized_page_size,
        total=total,
    )


def get_admin_community_post_detail(session: Session, settings: Settings, post_id: str) -> AdminCommunityPostDetail:
    row = session.execute(
        select(CommunityPost, User, Trip)
        .join(User, User.id == CommunityPost.author_user_id)
        .outerjoin(Trip, Trip.id == CommunityPost.trip_id)
        .where(CommunityPost.id == post_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "admin_community_post_not_found", "message": "Community post not found"})
    record, author, trip = row
    summary = _community_summary(record, author, trip, settings)
    return AdminCommunityPostDetail(**summary.model_dump(), snapshot=record.snapshot_json or {})


def delete_admin_community_post(session: Session, *, admin: User, post_id: str, reason: str) -> dict[str, Any]:
    record = session.scalar(select(CommunityPost).where(CommunityPost.id == post_id))
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "admin_community_post_not_found", "message": "Community post not found"})
    details = {"title": record.title, "author_user_id": record.author_user_id, "trip_id": record.trip_id}
    _audit(session, admin=admin, action="community_post.delete", target_type="community_post", target_id=record.id, reason=reason, details=details)
    session.delete(record)
    session.commit()
    return {"success": True, "post_id": post_id}


def _job_summary(job: JobRecord, owner: User | None, settings: Settings) -> AdminJobSummary:
    return AdminJobSummary(
        job_id=job.id,
        owner_user_id=job.owner_user_id,
        owner=_owner_summary(owner, settings),
        status=job.status,
        type=job.type,
        trip_id=job.trip_id,
        created_at=job.created_at,
        updated_at=job.updated_at,
        stage=job.stage,
        stage_message=job.stage_message,
        progress_percent=job.progress_percent,
        error_message=job.error_message,
    )


def list_admin_jobs(
    session: Session,
    settings: Settings,
    *,
    page: int = 1,
    page_size: int = 20,
    query: str | None = None,
    owner_id: str | None = None,
    trip_id: str | None = None,
    status_filter: str | None = None,
    job_type: str | None = None,
) -> AdminPageResponse:
    stmt = select(JobRecord, User).outerjoin(User, User.id == JobRecord.owner_user_id)
    normalized_query = _normalize_query(query)
    if normalized_query:
        like = f"%{normalized_query.lower()}%"
        stmt = stmt.where(or_(func.lower(JobRecord.id).like(like), func.lower(JobRecord.type).like(like), func.lower(User.email).like(like), func.lower(User.name).like(like)))
    if owner_id:
        stmt = stmt.where(JobRecord.owner_user_id == owner_id)
    if trip_id:
        stmt = stmt.where(JobRecord.trip_id == trip_id)
    if status_filter:
        stmt = stmt.where(JobRecord.status == status_filter)
    if job_type:
        stmt = stmt.where(JobRecord.type == job_type)
    stmt = stmt.order_by(JobRecord.updated_at.desc())

    rows, normalized_page, normalized_page_size, total = _paginate(session, stmt, page=page, page_size=page_size)
    return AdminPageResponse(
        items=[_job_summary(job, owner, settings).model_dump(mode="json") for job, owner in rows],
        page=normalized_page,
        page_size=normalized_page_size,
        total=total,
    )


def get_admin_job_detail(session: Session, settings: Settings, job_id: str) -> AdminJobDetail:
    row = session.execute(select(JobRecord, User).outerjoin(User, User.id == JobRecord.owner_user_id).where(JobRecord.id == job_id)).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "admin_job_not_found", "message": "Job not found"})
    job, owner = row
    summary = _job_summary(job, owner, settings)
    return AdminJobDetail(
        **summary.model_dump(),
        timeline_json=job.timeline_json or [],
        result=job.result_json,
        payload=job.payload_json,
    )
