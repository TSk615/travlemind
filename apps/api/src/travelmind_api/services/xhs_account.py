from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.account import XhsAccountStatusResponse, XhsBindingStatusResponse
from travelmind_api.core.config import Settings, get_settings
from travelmind_api.core.database import session_scope
from travelmind_api.db.models import User, XhsAccountSession, XhsBindingAttempt
from travelmind_api.services.xhs_crawler import XhsCrawlerBindingState, XhsCrawlerClient, XhsCrawlerClientError

_LOGGER = logging.getLogger(__name__)
_TERMINAL_BIND_STATUSES = {"authorized", "expired", "cancelled", "failed"}


@dataclass(frozen=True)
class XhsSearchState:
    xhs_bound: bool
    xhs_binding_required: bool
    xhs_session_expired: bool
    xhs_message: str | None
    session_payload: dict[str, Any] | None


def get_xhs_account_status(session: Session, user: User | str) -> XhsAccountStatusResponse:
    user_id = user.id if isinstance(user, User) else str(user)
    binding = session.scalar(select(XhsAccountSession).where(XhsAccountSession.user_id == user_id))
    if _expire_binding_if_needed(binding):
        session.add(binding)
        session.commit()
        session.refresh(binding)
    active_attempt = session.scalar(
        select(XhsBindingAttempt)
        .where(XhsBindingAttempt.user_id == user_id)
        .order_by(XhsBindingAttempt.created_at.desc())
    )
    return _serialize_status(binding, active_attempt)


def start_xhs_binding(session: Session, user: User, client: XhsCrawlerClient) -> XhsBindingStatusResponse:
    for attempt in session.scalars(select(XhsBindingAttempt).where(XhsBindingAttempt.user_id == user.id)):
        if attempt.status not in _TERMINAL_BIND_STATUSES:
            attempt.status = "cancelled"
            attempt.error_message = "Superseded by a newer binding flow."
            attempt.completed_at = _utcnow()

    binding_state = client.start_binding(user_id=user.id)
    attempt = XhsBindingAttempt(
        id=binding_state.bind_id,
        user_id=user.id,
        status=binding_state.status,
        verification_url=binding_state.verification_url,
        verification_code=binding_state.verification_code,
        qr_image_data_url=binding_state.qr_image_data_url,
        error_message=binding_state.message,
        expires_at=_parse_datetime(binding_state.expires_at),
        completed_at=_parse_datetime(binding_state.completed_at),
    )
    attempt = session.merge(attempt)
    session.commit()
    session.refresh(attempt)
    return _serialize_binding_attempt(attempt)


def poll_xhs_binding(session: Session, user: User, bind_id: str, client: XhsCrawlerClient) -> XhsBindingStatusResponse:
    attempt = session.scalar(select(XhsBindingAttempt).where(XhsBindingAttempt.id == bind_id, XhsBindingAttempt.user_id == user.id))
    if attempt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "xhs_bind_not_found", "message": "XHS bind flow not found"})

    if attempt.status not in _TERMINAL_BIND_STATUSES:
        binding_state = client.get_binding(bind_id=attempt.id)
        _apply_binding_state(attempt, binding_state)
        if binding_state.status == "authorized" and binding_state.session_payload:
            _store_bound_session(session, user.id, binding_state)
        session.add(attempt)
        session.commit()
        session.refresh(attempt)

    return _serialize_binding_attempt(attempt)


def delete_xhs_binding(session: Session, user: User, client: XhsCrawlerClient | None = None) -> XhsAccountStatusResponse:
    session.execute(delete(XhsBindingAttempt).where(XhsBindingAttempt.user_id == user.id))
    session.execute(delete(XhsAccountSession).where(XhsAccountSession.user_id == user.id))
    session.commit()
    if client is not None:
        try:
            client.delete_session(user_id=user.id)
        except XhsCrawlerClientError as exc:
            _LOGGER.warning("XHS crawler delete_session failed for user %s: %s", user.id, exc)
    return XhsAccountStatusResponse(
        xhs_bound=False,
        xhs_binding_required=True,
        xhs_session_expired=False,
        xhs_message="Bind Xiaohongshu to enable Xiaohongshu grounding.",
        active_binding=None,
    )


def load_xhs_search_state(user_id: str) -> XhsSearchState:
    settings = get_settings()
    with session_scope() as session:
        binding = session.scalar(select(XhsAccountSession).where(XhsAccountSession.user_id == user_id))
        _expire_binding_if_needed(binding)
        if binding is None:
            return XhsSearchState(
                xhs_bound=False,
                xhs_binding_required=True,
                xhs_session_expired=False,
                xhs_message="Bind Xiaohongshu to enable Xiaohongshu grounding.",
                session_payload=None,
            )
        if binding.status == "expired":
            return XhsSearchState(
                xhs_bound=False,
                xhs_binding_required=True,
                xhs_session_expired=True,
                xhs_message=binding.last_error or "Xiaohongshu session expired. Rebind to continue using Xiaohongshu grounding.",
                session_payload=None,
            )
        if binding.status != "bound" or not binding.session_ciphertext:
            return XhsSearchState(
                xhs_bound=False,
                xhs_binding_required=True,
                xhs_session_expired=False,
                xhs_message=binding.last_error or "Bind Xiaohongshu to enable Xiaohongshu grounding.",
                session_payload=None,
            )
        try:
            session_payload = decrypt_session_payload(binding.session_ciphertext, settings)
        except ValueError:
            _expire_binding(binding, "Stored Xiaohongshu session could not be restored. Rebind required.")
            session.add(binding)
            return XhsSearchState(
                xhs_bound=False,
                xhs_binding_required=True,
                xhs_session_expired=True,
                xhs_message=binding.last_error,
                session_payload=None,
            )
        return XhsSearchState(
            xhs_bound=True,
            xhs_binding_required=False,
            xhs_session_expired=False,
            xhs_message=None,
            session_payload=session_payload,
        )


def mark_xhs_session_available(user_id: str) -> None:
    with session_scope() as session:
        binding = session.scalar(select(XhsAccountSession).where(XhsAccountSession.user_id == user_id))
        if binding is None:
            return
        binding.status = "bound"
        binding.last_available_at = _utcnow()
        binding.last_error = None
        session.add(binding)


def mark_xhs_session_expired(user_id: str, message: str | None = None) -> None:
    with session_scope() as session:
        binding = session.scalar(select(XhsAccountSession).where(XhsAccountSession.user_id == user_id))
        if binding is None:
            return
        _expire_binding(binding, message or "Xiaohongshu session expired. Rebind to continue using Xiaohongshu grounding.")
        session.add(binding)


def encrypt_session_payload(payload: dict[str, Any], settings: Settings | None = None) -> str:
    active_settings = settings or get_settings()
    plaintext = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    secret = _secret_bytes(active_settings)
    nonce = secrets.token_bytes(16)
    ciphertext = _xor_with_keystream(plaintext, secret, nonce)
    tag = hmac.new(secret, nonce + ciphertext, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + tag + ciphertext).decode("ascii")


def decrypt_session_payload(ciphertext: str, settings: Settings | None = None) -> dict[str, Any]:
    active_settings = settings or get_settings()
    secret = _secret_bytes(active_settings)
    try:
        blob = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
    except Exception as exc:  # pragma: no cover
        raise ValueError("Invalid XHS session ciphertext") from exc
    if len(blob) < 48:
        raise ValueError("Invalid XHS session ciphertext")
    nonce = blob[:16]
    tag = blob[16:48]
    encrypted = blob[48:]
    expected_tag = hmac.new(secret, nonce + encrypted, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected_tag):
        raise ValueError("Invalid XHS session ciphertext")
    plaintext = _xor_with_keystream(encrypted, secret, nonce)
    try:
        payload = json.loads(plaintext.decode("utf-8"))
    except ValueError as exc:
        raise ValueError("Invalid XHS session payload") from exc
    if not isinstance(payload, dict):
        raise ValueError("Invalid XHS session payload")
    return payload


def _store_bound_session(session: Session, user_id: str, binding_state: XhsCrawlerBindingState) -> XhsAccountSession:
    now = _utcnow()
    binding = session.scalar(select(XhsAccountSession).where(XhsAccountSession.user_id == user_id))
    if binding is None:
        binding = XhsAccountSession(user_id=user_id)
    binding.status = "bound"
    binding.xhs_user_id = binding_state.xhs_user_id
    binding.display_name = binding_state.display_name
    binding.session_ciphertext = encrypt_session_payload(binding_state.session_payload or {})
    binding.session_expires_at = _parse_datetime(binding_state.session_expires_at)
    binding.last_bound_at = now
    binding.last_available_at = now
    binding.last_error = None
    session.add(binding)
    return binding


def _serialize_status(binding: XhsAccountSession | None, active_attempt: XhsBindingAttempt | None) -> XhsAccountStatusResponse:
    if binding is None:
        return XhsAccountStatusResponse(
            xhs_bound=False,
            xhs_binding_required=True,
            xhs_session_expired=False,
            xhs_message="Bind Xiaohongshu to enable Xiaohongshu grounding.",
            active_binding=_serialize_binding_attempt(active_attempt) if active_attempt is not None and active_attempt.status not in _TERMINAL_BIND_STATUSES else None,
        )

    xhs_session_expired = binding.status == "expired"
    return XhsAccountStatusResponse(
        xhs_bound=binding.status == "bound" and bool(binding.session_ciphertext),
        xhs_binding_required=binding.status != "bound" or not bool(binding.session_ciphertext),
        xhs_session_expired=xhs_session_expired,
        xhs_message=binding.last_error
        if xhs_session_expired
        else (None if binding.status == "bound" else "Bind Xiaohongshu to enable Xiaohongshu grounding."),
        xhs_display_name=binding.display_name,
        xhs_last_bound_at=binding.last_bound_at,
        xhs_last_available_at=binding.last_available_at,
        active_binding=_serialize_binding_attempt(active_attempt) if active_attempt is not None and active_attempt.status not in _TERMINAL_BIND_STATUSES else None,
    )


def _serialize_binding_attempt(attempt: XhsBindingAttempt | None) -> XhsBindingStatusResponse | None:
    if attempt is None:
        return None
    return XhsBindingStatusResponse(
        bind_id=attempt.id,
        status=attempt.status,
        verification_url=attempt.verification_url,
        verification_code=attempt.verification_code,
        qr_image_data_url=attempt.qr_image_data_url,
        expires_at=attempt.expires_at,
        completed_at=attempt.completed_at,
        message=attempt.error_message,
    )


def _apply_binding_state(attempt: XhsBindingAttempt, binding_state: XhsCrawlerBindingState) -> None:
    attempt.status = binding_state.status
    attempt.verification_url = binding_state.verification_url
    attempt.verification_code = binding_state.verification_code
    attempt.qr_image_data_url = binding_state.qr_image_data_url
    attempt.expires_at = _parse_datetime(binding_state.expires_at)
    attempt.completed_at = _parse_datetime(binding_state.completed_at)
    attempt.error_message = binding_state.message


def _expire_binding_if_needed(binding: XhsAccountSession | None) -> bool:
    if binding is None or binding.session_expires_at is None:
        return False
    expires_at = binding.session_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= _utcnow():
        _expire_binding(binding, "Xiaohongshu session expired. Rebind to continue using Xiaohongshu grounding.")
        return True
    return False


def _expire_binding(binding: XhsAccountSession, message: str) -> None:
    binding.status = "expired"
    binding.session_ciphertext = None
    binding.session_expires_at = None
    binding.last_error = message


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: str | None) -> datetime | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _secret_bytes(settings: Settings) -> bytes:
    source = settings.xhs_session_secret.strip() or settings.jwt_secret
    return hashlib.sha256(source.encode("utf-8")).digest()


def _xor_with_keystream(data: bytes, secret: bytes, nonce: bytes) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < len(data):
        block = hashlib.sha256(secret + nonce + counter.to_bytes(8, "big")).digest()
        output.extend(block)
        counter += 1
    return bytes(left ^ right for left, right in zip(data, output[: len(data)], strict=False))
