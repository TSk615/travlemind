from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.common import success_response
from travelmind_api.api.schemas.community import (
    CommunityPostCreateRequest,
    CommunityPostRefreshRequest,
    CommunityPostUpdateRequest,
)
from travelmind_api.core.database import get_db
from travelmind_api.core.deps import get_current_user
from travelmind_api.db.models import User
from travelmind_api.services.community_service import (
    create_community_post,
    delete_community_post,
    get_owned_community_post_or_404,
    get_published_community_post_or_404,
    list_published_community_posts,
    refresh_community_post_from_trip,
    serialize_community_post_detail,
    serialize_community_post_summary,
    update_community_post_share_note,
)
from travelmind_api.services.trip_service import get_trip_or_404

router = APIRouter(prefix="/community", tags=["community"])


@router.get("/posts")
def get_community_posts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    del current_user
    records = [
        serialize_community_post_summary(record, author_name=author_name).model_dump(mode="json")
        for record, author_name in list_published_community_posts(db)
    ]
    return success_response(records)


@router.get("/posts/{post_id}")
def get_community_post_detail(post_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    del current_user
    record, author_name = get_published_community_post_or_404(db, post_id)
    return success_response(serialize_community_post_detail(record, author_name=author_name).model_dump(mode="json"))


@router.post("/posts")
def create_community_post_endpoint(
    payload: CommunityPostCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trip = get_trip_or_404(db, current_user, payload.trip_id)
    record = create_community_post(db, user=current_user, trip=trip, share_note=payload.share_note)
    return success_response(serialize_community_post_detail(record, author_name=current_user.name).model_dump(mode="json"))


@router.patch("/posts/{post_id}")
def update_community_post_endpoint(
    post_id: str,
    payload: CommunityPostUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = get_owned_community_post_or_404(db, current_user, post_id)
    updated = update_community_post_share_note(db, record=record, share_note=payload.share_note)
    return success_response(serialize_community_post_detail(updated, author_name=current_user.name).model_dump(mode="json"))


@router.post("/posts/{post_id}/refresh-from-trip")
def refresh_community_post_endpoint(
    post_id: str,
    payload: CommunityPostRefreshRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = get_owned_community_post_or_404(db, current_user, post_id)
    trip = get_trip_or_404(db, current_user, record.trip_id)
    updated = refresh_community_post_from_trip(db, record=record, trip=trip, share_note=payload.share_note)
    return success_response(serialize_community_post_detail(updated, author_name=current_user.name).model_dump(mode="json"))


@router.delete("/posts/{post_id}")
def delete_community_post_endpoint(
    post_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = get_owned_community_post_or_404(db, current_user, post_id)
    delete_community_post(db, record=record)
    return success_response({"success": True, "post_id": post_id})
