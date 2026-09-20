from __future__ import annotations

import datetime as dt

from fastapi import HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from travelmind_api.agents.provider import AGENT_PROVIDER_STANDARD, is_supported_agent_provider, normalize_agent_provider
from travelmind_api.api.schemas.auth import LoginRequest, RegisterRequest, UserResponse
from travelmind_api.api.schemas.settings import (
    AgentSettingsResponse,
    ImageSettingsResponse,
    RuntimeSettingsResponse,
    RuntimeSettingsUpdateRequest,
    SearchSettingsResponse,
)
from travelmind_api.core.config import Settings, get_settings
from travelmind_api.core.security import (
    create_access_token,
    generate_identifier,
    generate_csrf_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from travelmind_api.core.upstream_urls import UpstreamUrlError, normalize_upstream_base_url
from travelmind_api.db.models import RefreshSession, User
from travelmind_api.services.images.provider import IMAGE_PROVIDER_OPENAI_COMPATIBLE, is_supported_image_provider, normalize_image_provider
from travelmind_api.services.llm.config import is_supported_provider_protocol, normalize_provider_protocol, normalize_wire_api
from travelmind_api.services.llm.user_config import user_poi_role_override_missing_fields
from travelmind_api.services.search_connector import normalize_search_service_provider, normalize_search_service_transport


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)



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
    try:
        return normalize_upstream_base_url(normalized, get_settings())
    except UpstreamUrlError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_upstream_base_url", "message": str(exc)},
        ) from exc



def _normalize_model(model: str | None) -> str | None:
    return _normalize_optional_text(model)



def _normalize_api_key(api_key: str | None) -> str | None:
    return _normalize_optional_text(api_key)



def _normalize_wire_api_value(wire_api: str | None) -> str | None:
    normalized = _normalize_optional_text(wire_api)
    if normalized is None:
        return None
    return normalize_wire_api(normalized, default="responses")


def _normalize_provider_protocol_value(provider_protocol: str | None) -> str | None:
    normalized = _normalize_optional_text(provider_protocol)
    if normalized is None:
        return None
    if not is_supported_provider_protocol(normalized):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_llm_provider_protocol", "message": "provider_protocol must be openai, newapi, gemini, claude, or neiapi"},
        )
    return normalize_provider_protocol(normalized)



def _normalize_agent_provider_value(agent_provider: str | None) -> str | None:
    normalized = _normalize_optional_text(agent_provider)
    if normalized is None:
        return None
    if not is_supported_agent_provider(normalized):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_agent_provider", "message": "agent_provider must be standard or langgraph"},
        )
    return normalize_agent_provider(normalized, default=AGENT_PROVIDER_STANDARD)



def _normalize_search_provider_value(provider: str | None) -> str | None:
    normalized = _normalize_optional_text(provider)
    if normalized is None:
        return None
    if str(normalized).strip().lower() not in {"groksearch", "grok-search", "grok_search", "grok", "tavily"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_search_provider", "message": "search provider must be groksearch or tavily"},
        )
    return normalize_search_service_provider(normalized)


def _normalize_search_transport_value(transport: str | None) -> str | None:
    normalized = _normalize_optional_text(transport)
    if normalized is None:
        return None
    if str(normalized).strip().lower() not in {"mcp", "api", "rest", "http"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_search_transport", "message": "search transport must be mcp or api"},
        )
    return normalize_search_service_transport(normalized)


def _normalize_image_provider_value(provider: str | None) -> str | None:
    normalized = _normalize_optional_text(provider)
    if normalized is None:
        return None
    if not is_supported_image_provider(normalized):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_image_provider", "message": "image provider must be openai_compatible, huggingface, gitee_ai, modelscope, or a4f"},
        )
    return normalize_image_provider(normalized)


def _normalize_timeout_seconds(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_timeout_seconds", "message": "timeout_seconds must be a positive number"},
        ) from exc
    if normalized <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_timeout_seconds", "message": "timeout_seconds must be a positive number"},
        )
    return normalized


def mask_api_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    if len(api_key) <= 8:
        return f"{api_key[:2]}{'*' * max(len(api_key) - 2, 2)}"
    return f"{api_key[:4]}{'*' * (len(api_key) - 8)}{api_key[-4:]}"


def is_admin_user(user: User, settings: Settings) -> bool:
    return user.email.strip().lower() in settings.normalized_admin_emails


def ensure_user_active(user: User) -> None:
    if getattr(user, "disabled_at", None) is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "user_disabled", "message": "This account has been disabled"},
        )


def serialize_user(user: User, settings: Settings | None = None) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar=user.avatar,
        locale=user.locale,
        created_at=user.created_at,
        is_admin=is_admin_user(user, settings) if settings is not None else False,
    )



def serialize_runtime_settings(user: User, settings: Settings) -> RuntimeSettingsResponse:
    search_provider_raw = str(getattr(user, "search_service_provider", None) or "").strip().lower()
    search_transport_raw = str(getattr(user, "search_service_transport", None) or "").strip().lower()
    search_provider = normalize_search_service_provider(search_provider_raw or None, default="groksearch")
    search_transport = normalize_search_service_transport(search_transport_raw or None, default="mcp")
    provider_supported = not search_provider_raw or search_provider_raw in {"groksearch", "grok-search", "grok_search", "grok", "tavily"}
    transport_supported = not search_transport_raw or search_transport_raw in {"mcp", "api", "rest", "http"}
    search_supported = provider_supported and transport_supported and (
        (search_provider == "groksearch" and search_transport == "mcp") or (search_provider == "tavily" and search_transport == "api")
    )
    if not search_supported:
        search_provider = "groksearch"
        search_transport = "mcp"

    return RuntimeSettingsResponse(
        agent=AgentSettingsResponse(
            provider_protocol=normalize_provider_protocol(getattr(user, "llm_provider_protocol", None)),
            base_url=user.llm_base_url,
            api_key_masked=mask_api_key(user.llm_api_key),
            has_api_key=bool(user.llm_api_key),
            model=user.llm_model,
            wire_api=user.llm_wire_api,
            agent_provider=normalize_agent_provider(user.llm_agent_provider, default=normalize_agent_provider(settings.agent_provider)),
            configured=bool(user.llm_base_url and user.llm_api_key and user.llm_model),
            poi_provider_protocol=normalize_provider_protocol(getattr(user, "poi_llm_provider_protocol", None)),
            poi_base_url=getattr(user, "poi_llm_base_url", None),
            poi_api_key_masked=mask_api_key(getattr(user, "poi_llm_api_key", None)),
            poi_has_api_key=bool(getattr(user, "poi_llm_api_key", None)),
            poi_model=getattr(user, "poi_llm_model", None),
            weather_model=getattr(user, "weather_llm_model", None) or getattr(user, "poi_llm_model", None),
            hotel_model=getattr(user, "hotel_llm_model", None) or getattr(user, "poi_llm_model", None),
            transport_model=getattr(user, "transport_llm_model", None) or getattr(user, "poi_llm_model", None),
            poi_wire_api=getattr(user, "poi_llm_wire_api", None),
            poi_configured=bool(getattr(user, "poi_llm_base_url", None) and getattr(user, "poi_llm_api_key", None) and getattr(user, "poi_llm_model", None)),
        ),
        search=SearchSettingsResponse(
            provider=search_provider,
            transport=search_transport,
            base_url=getattr(user, "search_service_base_url", None) if search_supported else None,
            api_key_masked=mask_api_key(getattr(user, "search_service_api_key", None)) if search_supported else None,
            has_api_key=bool(getattr(user, "search_service_api_key", None)) if search_supported else False,
            timeout_seconds=float(getattr(user, "search_service_timeout_seconds", 30.0) or 30.0),
            xhs_source_enabled=bool(getattr(user, "xhs_source_enabled", False)),
            configured=search_supported and bool(getattr(user, "search_service_base_url", None) and getattr(user, "search_service_api_key", None)),
        ),
        image=ImageSettingsResponse(
            base_url=getattr(user, "image_base_url", None),
            api_key_masked=mask_api_key(getattr(user, "image_api_key", None)),
            has_api_key=bool(getattr(user, "image_api_key", None)),
            model=getattr(user, "image_model", None),
            provider=normalize_image_provider(getattr(user, "image_provider", None), default=IMAGE_PROVIDER_OPENAI_COMPATIBLE),
            configured=bool(getattr(user, "image_base_url", None) and getattr(user, "image_api_key", None) and getattr(user, "image_model", None)),
        ),
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
    ensure_user_active(user)
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
        expires_at=_utcnow() + dt.timedelta(days=settings.refresh_token_days),
    )
    session.add(refresh_session)
    session.commit()
    return access_token, refresh_token



def issue_access_token(user: User, settings: Settings) -> str:
    return create_access_token({"sub": user.id, "email": user.email}, settings)



def attach_auth_cookies(response: Response, access_token: str, refresh_token: str, settings: Settings) -> None:
    # The web client talks directly to FastAPI, so auth lives in HttpOnly cookies
    # instead of localStorage to keep credential handling out of frontend code.
    response.set_cookie(
        key=settings.access_cookie_name,
        value=access_token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.access_token_minutes * 60,
        path="/",
    )
    attach_csrf_cookie(response, settings)
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=refresh_token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        path="/",
    )



def attach_access_cookie(response: Response, access_token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.access_cookie_name,
        value=access_token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.access_token_minutes * 60,
        path="/",
    )
    attach_csrf_cookie(response, settings)


def attach_csrf_cookie(response: Response, settings: Settings) -> None:
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=generate_csrf_token(),
        httponly=False,
        secure=settings.auth_cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        path="/",
    )



def clear_auth_cookies(response: Response, settings: Settings) -> None:
    cookie_options = {
        "path": "/",
        "secure": settings.auth_cookie_secure,
        "httponly": True,
        "samesite": settings.cookie_samesite,
    }
    response.delete_cookie(settings.access_cookie_name, **cookie_options)
    response.delete_cookie(settings.refresh_cookie_name, **cookie_options)
    response.delete_cookie(
        settings.csrf_cookie_name,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=False,
        samesite=settings.cookie_samesite,
    )



def refresh_access_token(session: Session, refresh_token: str | None, settings: Settings) -> str:
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "refresh_session_not_found", "message": "Refresh session not found"},
        )

    token_hash = hash_refresh_token(refresh_token)
    refresh_session = session.scalar(select(RefreshSession).where(RefreshSession.token_hash == token_hash))
    if refresh_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "refresh_session_not_found", "message": "Refresh session not found"},
        )

    expires_at = refresh_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=dt.timezone.utc)
    if expires_at <= _utcnow():
        session.delete(refresh_session)
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "refresh_session_expired", "message": "Refresh session expired"},
        )

    user = session.scalar(select(User).where(User.id == refresh_session.user_id))
    if user is None:
        session.delete(refresh_session)
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "user_not_found", "message": "User not found"},
        )
    if getattr(user, "disabled_at", None) is not None:
        session.delete(refresh_session)
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "user_disabled", "message": "This account has been disabled"},
        )

    return issue_access_token(user, settings)



def revoke_refresh_session(session: Session, refresh_token: str | None) -> None:
    if not refresh_token:
        return
    token_hash = hash_refresh_token(refresh_token)
    session.query(RefreshSession).filter(RefreshSession.token_hash == token_hash).delete()
    session.commit()



def update_user_runtime_settings(session: Session, user: User, payload: RuntimeSettingsUpdateRequest) -> User:
    agent_updates = payload.agent.model_dump(exclude_unset=True) if payload.agent is not None else {}
    search_updates = payload.search.model_dump(exclude_unset=True) if payload.search is not None else {}
    image_updates = payload.image.model_dump(exclude_unset=True) if payload.image is not None else {}
    if not agent_updates and not search_updates and not image_updates:
        return user

    if "base_url" in agent_updates:
        user.llm_base_url = _normalize_base_url(agent_updates["base_url"])
    if "provider_protocol" in agent_updates:
        user.llm_provider_protocol = _normalize_provider_protocol_value(agent_updates["provider_protocol"])
    if "api_key" in agent_updates:
        user.llm_api_key = _normalize_api_key(agent_updates["api_key"])
    if "model" in agent_updates:
        user.llm_model = _normalize_model(agent_updates["model"])
    if "wire_api" in agent_updates:
        user.llm_wire_api = _normalize_wire_api_value(agent_updates["wire_api"])
    if "agent_provider" in agent_updates:
        user.llm_agent_provider = _normalize_agent_provider_value(agent_updates["agent_provider"])
    if "poi_base_url" in agent_updates:
        user.poi_llm_base_url = _normalize_base_url(agent_updates["poi_base_url"])
    if "poi_provider_protocol" in agent_updates:
        user.poi_llm_provider_protocol = _normalize_provider_protocol_value(agent_updates["poi_provider_protocol"])
    if "poi_api_key" in agent_updates:
        user.poi_llm_api_key = _normalize_api_key(agent_updates["poi_api_key"])
    if "poi_model" in agent_updates:
        user.poi_llm_model = _normalize_model(agent_updates["poi_model"])
    if "weather_model" in agent_updates:
        user.weather_llm_model = _normalize_model(agent_updates["weather_model"])
    if "hotel_model" in agent_updates:
        user.hotel_llm_model = _normalize_model(agent_updates["hotel_model"])
    if "transport_model" in agent_updates:
        user.transport_llm_model = _normalize_model(agent_updates["transport_model"])
    if "poi_wire_api" in agent_updates:
        user.poi_llm_wire_api = _normalize_wire_api_value(agent_updates["poi_wire_api"])
    clearing_saved_poi_config = (
        "poi_base_url" in agent_updates
        and "poi_model" in agent_updates
        and not user.poi_llm_base_url
        and not user.poi_llm_model
        and "poi_api_key" not in agent_updates
    )
    if clearing_saved_poi_config:
        user.poi_llm_api_key = None

    normalized_llm_protocol = normalize_provider_protocol(getattr(user, "llm_provider_protocol", None))
    if normalized_llm_protocol == "openai":
        user.llm_wire_api = "responses"
    elif "provider_protocol" in agent_updates and "wire_api" not in agent_updates and normalized_llm_protocol in {"newapi", "neiapi"}:
        user.llm_wire_api = "chat_completions"

    normalized_poi_llm_protocol = normalize_provider_protocol(getattr(user, "poi_llm_provider_protocol", None))
    if getattr(user, "poi_llm_base_url", None) and getattr(user, "poi_llm_model", None):
        if normalized_poi_llm_protocol == "openai":
            user.poi_llm_wire_api = "responses"
        elif "poi_provider_protocol" in agent_updates and "poi_wire_api" not in agent_updates and normalized_poi_llm_protocol in {"newapi", "neiapi"}:
            user.poi_llm_wire_api = "chat_completions"
    missing_poi_fields = user_poi_role_override_missing_fields(user)
    if missing_poi_fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "poi_llm_override_incomplete",
                "message": "Complete POI base URL, API key, and model, or clear all POI model fields.",
                "missing_fields": missing_poi_fields,
            },
        )

    if search_updates:
        next_search_provider = normalize_search_service_provider(getattr(user, "search_service_provider", None), default="groksearch")
        next_search_transport = normalize_search_service_transport(getattr(user, "search_service_transport", None), default="mcp")
        next_search_base_url = getattr(user, "search_service_base_url", None)
        next_search_api_key = getattr(user, "search_service_api_key", None)
        next_search_timeout = float(getattr(user, "search_service_timeout_seconds", 30.0) or 30.0)
        next_xhs_source_enabled = bool(getattr(user, "xhs_source_enabled", False))

        if "provider" in search_updates:
            normalized_provider = _normalize_search_provider_value(search_updates["provider"])
            if normalized_provider is not None:
                next_search_provider = normalized_provider
        if "transport" in search_updates:
            normalized_transport = _normalize_search_transport_value(search_updates["transport"])
            if normalized_transport is not None:
                next_search_transport = normalized_transport
        if next_search_provider == "groksearch" and next_search_transport != "mcp":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "invalid_search_transport", "message": "groksearch currently only supports mcp transport"},
            )
        if next_search_provider == "tavily" and next_search_transport != "api":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "invalid_search_transport", "message": "tavily currently only supports api transport"},
            )
        if "base_url" in search_updates:
            next_search_base_url = _normalize_base_url(search_updates["base_url"])
        if "api_key" in search_updates:
            next_search_api_key = _normalize_api_key(search_updates["api_key"])
        if "timeout_seconds" in search_updates:
            normalized_timeout = _normalize_timeout_seconds(search_updates["timeout_seconds"])
            if normalized_timeout is not None:
                next_search_timeout = normalized_timeout
        if "xhs_source_enabled" in search_updates and search_updates["xhs_source_enabled"] is not None:
            next_xhs_source_enabled = bool(search_updates["xhs_source_enabled"])

        user.search_service_provider = next_search_provider
        user.search_service_transport = next_search_transport
        user.search_service_base_url = next_search_base_url
        user.search_service_api_key = next_search_api_key
        user.search_service_timeout_seconds = next_search_timeout
        user.xhs_source_enabled = next_xhs_source_enabled

    if "base_url" in image_updates:
        user.image_base_url = _normalize_base_url(image_updates["base_url"])
    if "api_key" in image_updates:
        user.image_api_key = _normalize_api_key(image_updates["api_key"])
    if "model" in image_updates:
        user.image_model = _normalize_model(image_updates["model"])
    if "provider" in image_updates:
        user.image_provider = _normalize_image_provider_value(image_updates["provider"])

    session.add(user)
    session.commit()
    session.refresh(user)
    return user
