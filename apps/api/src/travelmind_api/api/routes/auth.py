from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.auth import LoginRequest, LogoutResponse, RegisterRequest
from travelmind_api.api.schemas.common import success_response
from travelmind_api.core.config import Settings, get_settings
from travelmind_api.core.database import get_db
from travelmind_api.services.auth_service import attach_auth_cookies, authenticate_user, issue_tokens, register_user, revoke_refresh_session, serialize_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
def register(payload: RegisterRequest, response: Response, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user = register_user(db, payload)
    access_token, refresh_token = issue_tokens(db, user, settings)
    attach_auth_cookies(response, access_token, refresh_token, settings)
    return success_response(serialize_user(user).model_dump(mode="json"))


@router.post("/login")
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user = authenticate_user(db, payload)
    access_token, refresh_token = issue_tokens(db, user, settings)
    attach_auth_cookies(response, access_token, refresh_token, settings)
    return success_response(serialize_user(user).model_dump(mode="json"))


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    revoke_refresh_session(db, request.cookies.get(settings.refresh_cookie_name))
    response.delete_cookie(settings.access_cookie_name, path="/")
    response.delete_cookie(settings.refresh_cookie_name, path="/")
    return success_response(LogoutResponse().model_dump())