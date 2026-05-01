from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.auth import LoginRequest, LogoutResponse, RefreshResponse, RegisterRequest
from travelmind_api.api.schemas.common import Envelope, ErrorPayload, success_response
from travelmind_api.core.config import Settings, get_settings
from travelmind_api.core.database import get_db
from travelmind_api.services.auth_service import (
    attach_access_cookie,
    attach_auth_cookies,
    authenticate_user,
    clear_auth_cookies,
    issue_tokens,
    refresh_access_token,
    register_user,
    revoke_refresh_session,
    serialize_user,
)

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


@router.post("/refresh")
def refresh(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        access_token = refresh_access_token(db, request.cookies.get(settings.refresh_cookie_name), settings)
    except HTTPException as exc:
        if exc.status_code != status.HTTP_401_UNAUTHORIZED:
            raise
        response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=Envelope(
                data=None,
                error=ErrorPayload(**exc.detail),
                meta={},
            ).model_dump(mode="json"),
        )
        clear_auth_cookies(response, settings)
        return response

    response = JSONResponse(content=success_response(RefreshResponse().model_dump()).model_dump(mode="json"))
    attach_access_cookie(response, access_token, settings)
    return response


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    revoke_refresh_session(db, request.cookies.get(settings.refresh_cookie_name))
    clear_auth_cookies(response, settings)
    return success_response(LogoutResponse().model_dump())
