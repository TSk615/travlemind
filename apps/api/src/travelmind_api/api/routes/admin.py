from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.admin import AdminActionRequest
from travelmind_api.api.schemas.common import success_response
from travelmind_api.core.config import Settings, get_settings
from travelmind_api.core.database import get_db
from travelmind_api.core.deps import require_admin_user
from travelmind_api.db.models import User
from travelmind_api.services.admin_service import (
    delete_admin_community_post,
    delete_admin_trip,
    disable_admin_user,
    enable_admin_user,
    get_admin_community_post_detail,
    get_admin_job_detail,
    get_admin_trip_detail,
    get_admin_user_detail,
    list_admin_community_posts,
    list_admin_jobs,
    list_admin_trips,
    list_admin_users,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users")
def admin_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    query: str | None = None,
    status: str = Query(default="all"),
    admin_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_admin: User = Depends(require_admin_user),
):
    del current_admin
    payload = list_admin_users(
        db,
        settings,
        page=page,
        page_size=page_size,
        query=query,
        status_filter=status,
        admin_only=admin_only,
    )
    return success_response(payload.model_dump(mode="json"))


@router.get("/users/{user_id}")
def admin_user_detail(
    user_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_admin: User = Depends(require_admin_user),
):
    del current_admin
    return success_response(get_admin_user_detail(db, settings, user_id).model_dump(mode="json"))


@router.post("/users/{user_id}/disable")
def admin_disable_user(
    user_id: str,
    payload: AdminActionRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_admin: User = Depends(require_admin_user),
):
    user = disable_admin_user(db, settings, admin=current_admin, user_id=user_id, reason=payload.reason)
    return success_response(user.model_dump(mode="json"))


@router.post("/users/{user_id}/enable")
def admin_enable_user(
    user_id: str,
    payload: AdminActionRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_admin: User = Depends(require_admin_user),
):
    user = enable_admin_user(db, settings, admin=current_admin, user_id=user_id, reason=payload.reason)
    return success_response(user.model_dump(mode="json"))


@router.get("/trips")
def admin_trips(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    query: str | None = None,
    owner_id: str | None = None,
    destination: str | None = None,
    has_itinerary: bool | None = None,
    has_community_post: bool | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_admin: User = Depends(require_admin_user),
):
    del current_admin
    payload = list_admin_trips(
        db,
        settings,
        page=page,
        page_size=page_size,
        query=query,
        owner_id=owner_id,
        destination=destination,
        has_itinerary=has_itinerary,
        has_community_post=has_community_post,
    )
    return success_response(payload.model_dump(mode="json"))


@router.get("/trips/{trip_id}")
def admin_trip_detail(
    trip_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_admin: User = Depends(require_admin_user),
):
    del current_admin
    return success_response(get_admin_trip_detail(db, settings, trip_id).model_dump(mode="json"))


@router.post("/trips/{trip_id}/delete")
def admin_delete_trip(
    trip_id: str,
    payload: AdminActionRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin_user),
):
    return success_response(delete_admin_trip(db, admin=current_admin, trip_id=trip_id, reason=payload.reason))


@router.get("/community/posts")
def admin_community_posts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    query: str | None = None,
    author_id: str | None = None,
    destination: str | None = None,
    stale_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_admin: User = Depends(require_admin_user),
):
    del current_admin
    payload = list_admin_community_posts(
        db,
        settings,
        page=page,
        page_size=page_size,
        query=query,
        author_id=author_id,
        destination=destination,
        stale_only=stale_only,
    )
    return success_response(payload.model_dump(mode="json"))


@router.get("/community/posts/{post_id}")
def admin_community_post_detail(
    post_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_admin: User = Depends(require_admin_user),
):
    del current_admin
    return success_response(get_admin_community_post_detail(db, settings, post_id).model_dump(mode="json"))


@router.post("/community/posts/{post_id}/delete")
def admin_delete_community_post(
    post_id: str,
    payload: AdminActionRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin_user),
):
    return success_response(delete_admin_community_post(db, admin=current_admin, post_id=post_id, reason=payload.reason))


@router.get("/jobs")
def admin_jobs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    query: str | None = None,
    owner_id: str | None = None,
    trip_id: str | None = None,
    status: str | None = None,
    type: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_admin: User = Depends(require_admin_user),
):
    del current_admin
    payload = list_admin_jobs(
        db,
        settings,
        page=page,
        page_size=page_size,
        query=query,
        owner_id=owner_id,
        trip_id=trip_id,
        status_filter=status,
        job_type=type,
    )
    return success_response(payload.model_dump(mode="json"))


@router.get("/jobs/{job_id}")
def admin_job_detail(
    job_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_admin: User = Depends(require_admin_user),
):
    del current_admin
    return success_response(get_admin_job_detail(db, settings, job_id).model_dump(mode="json"))
