from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.auth import LoginRequest, RegisterRequest, UserResponse
from travelmind_api.core.config import Settings
from travelmind_api.core.security import (
    create_access_token,
    generate_identifier,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from travelmind_api.db.models import RefreshSession, User


def _normalize_email(email: str) -> str:
    normalized = email.lower().strip()
    if not normalized:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": "invalid_email", "message": "Email cannot be empty"})
    return normalized


def _normalize_name(name: str) -> str:
    normalized = name.strip()
    if len(normalized) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_name", "message": "Name must contain at least 2 non-space characters"},
        )
    return normalized


def serialize_user(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar=user.avatar,
        locale=user.locale,
        created_at=user.created_at,
    )


def register_user(session: Session, payload: RegisterRequest) -> User:
    normalized_email = _normalize_email(payload.email)
    normalized_name = _normalize_name(payload.name)
    existing = session.scalar(select(User).where(User.email == normalized_email))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "email_taken", "message": "Email already registered"})

    user = User(
        id=generate_identifier("usr"),
        email=normalized_email,
        name=normalized_name,
        password_hash=hash_password(payload.password),
        locale="zh-CN",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def authenticate_user(session: Session, payload: LoginRequest) -> User:
    user = session.scalar(select(User).where(User.email == _normalize_email(payload.email)))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "invalid_credentials", "message": "Invalid email or password"})
    return user


def issue_tokens(session: Session, user: User, settings: Settings) -> tuple[str, str]:
    # Access tokens remain stateless; refresh sessions are persisted so browser
    # sessions can be revoked without server-side access-token storage.
    access_token = create_access_token({"sub": user.id, "email": user.email}, settings)
    refresh_token = generate_refresh_token()
    refresh_session = RefreshSession(
        id=generate_identifier("rfs"),
        user_id=user.id,
        token_hash=hash_refresh_token(refresh_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_days),
    )
    session.add(refresh_session)
    session.commit()
    return access_token, refresh_token


def attach_auth_cookies(response: Response, access_token: str, refresh_token: str, settings: Settings) -> None:
    # The web client talks directly to FastAPI, so auth lives in HttpOnly cookies
    # instead of localStorage to keep credential handling out of frontend code.
    response.set_cookie(
        key=settings.access_cookie_name,
        value=access_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=settings.access_token_minutes * 60,
        path="/",
    )
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=refresh_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        path="/",
    )


def revoke_refresh_session(session: Session, refresh_token: str | None) -> None:
    if not refresh_token:
        return
    token_hash = hash_refresh_token(refresh_token)
    session.query(RefreshSession).filter(RefreshSession.token_hash == token_hash).delete()
    session.commit()
