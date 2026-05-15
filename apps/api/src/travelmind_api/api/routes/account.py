from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.common import success_response
from travelmind_api.core.database import get_db
from travelmind_api.core.deps import get_current_user
from travelmind_api.db.models import User
from travelmind_api.services.auth_service import serialize_user
from travelmind_api.services.xhs_account import delete_xhs_binding, get_xhs_account_status, poll_xhs_binding, start_xhs_binding
from travelmind_api.services.xhs_crawler import XhsCrawlerClient, XhsCrawlerConfig

router = APIRouter(tags=["account"])


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return success_response(serialize_user(current_user).model_dump(mode="json"))


def _build_xhs_client() -> XhsCrawlerClient:
    config = XhsCrawlerConfig.from_env()
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "xhs_crawler_unavailable", "message": "XHS browser node is not configured"},
        )
    return XhsCrawlerClient(config)


@router.get("/account/xhs/status")
def xhs_status(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return success_response(get_xhs_account_status(db, current_user).model_dump(mode="json"))


@router.post("/account/xhs/bind")
def start_account_xhs_bind(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    response = start_xhs_binding(db, current_user, _build_xhs_client())
    return success_response(response.model_dump(mode="json"))


@router.get("/account/xhs/bind/{bind_id}")
def poll_account_xhs_bind(bind_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    response = poll_xhs_binding(db, current_user, bind_id, _build_xhs_client())
    return success_response(response.model_dump(mode="json"))


@router.delete("/account/xhs/bind")
def delete_account_xhs_bind(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    config = XhsCrawlerConfig.from_env()
    client = XhsCrawlerClient(config) if config is not None else None
    response = delete_xhs_binding(db, current_user, client)
    return success_response(response.model_dump(mode="json"))
