from __future__ import annotations

import datetime as dt
from urllib.parse import urlparse

from fastapi import HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.auth import LoginRequest, RegisterRequest, UserResponse
from travelmind_api.api.schemas.settings import LlmSettingsResponse, LlmSettingsUpdateRequest
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
from travelmind_api.services.llm.config import normalize_wire_api


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



def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None



def _normalize_base_url(base_url: str | None) -> str | None:
    normalized = _normalize_optional_text(base_url)
    if normalized is None:
        return None
    normalized = normalized.rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_llm_base_url", "message": "base_url must be a valid http or https URL"},
        )
    return normalized



def _normalize_model(model: str | None) -> str | None:
    return _normalize_optional_text(model)



def _normalize_api_key(api_key: str | None) -> str | None:
    return _normalize_optional_text(api_key)



def _normalize_wire_api_value(wire_api: str | None) -> str | None:
    normalized = _normalize_optional_text(wire_api)
    if normalized is None:
      return None
    return normalize_wire_api(normalized, default="responses")



def mask_api_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    if len(api_key) <= 8:
        return f"{api_key[:2]}{'*' * max(len(api_key) - 2, 2)}"
    return f"{api_key[:4]}{'*' * (len(api_key) - 8)}{api_key[-4:]}"



def serialize_user(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar=user.avatar,
        locale=user.locale,
        created_at=user.created_at,
    )



def serialize_llm_settings(user: User) -> LlmSettingsResponse:
    return LlmSettingsResponse(
        base_url=user.llm_base_url,
        api_key_masked=mask_api_key(user.llm_api_key),
        has_api_key=bool(user.llm_api_key),
        model=user.llm_model,
        wire_api=user.llm_wire_api,
        configured=bool(user.llm_base_url and user.llm_api_key and user.llm_model),
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
        expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=settings.refresh_token_days),
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



def update_user_llm_settings(session: Session, user: User, payload: LlmSettingsUpdateRequest) -> User:
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return user

    if "base_url" in updates:
        user.llm_base_url = _normalize_base_url(updates["base_url"])
    if "api_key" in updates:
        user.llm_api_key = _normalize_api_key(updates["api_key"])
    if "model" in updates:
        user.llm_model = _normalize_model(updates["model"])
    if "wire_api" in updates:
        user.llm_wire_api = _normalize_wire_api_value(updates["wire_api"])

    session.add(user)
    session.commit()
    session.refresh(user)
    return user