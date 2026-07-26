from __future__ import annotations

import pytest
from fastapi import Response
from pydantic import ValidationError

from travelmind_api.core.config import Settings
from travelmind_api.core.credentials import (
    CredentialDecryptionError,
    decrypt_credential,
    encrypt_credential,
    is_encrypted_credential,
)
from travelmind_api.services.auth_service import attach_auth_cookies


def _production_settings(**overrides) -> Settings:
    values = {
        "environment": "production",
        "jwt_secret": "jwt-production-secret-with-at-least-32-characters",
        "credential_encryption_key": "credential-production-secret-at-least-32-characters",
        "database_url": "postgresql+psycopg://travelmind:secret@db.example/travelmind",
        "public_api_url": "https://api.travelmind.example",
        "cors_origins": ["https://travelmind.example"],
        "upstream_private_url_policy": "deny",
        "rate_limit_backend": "redis",
    }
    values.update(overrides)
    return Settings(**values)


def test_credentials_are_authenticated_and_require_the_same_key():
    first = Settings(credential_encryption_key="first-encryption-secret-with-at-least-32-characters")
    second = Settings(credential_encryption_key="second-encryption-secret-with-at-least-32-characters")

    encrypted = encrypt_credential("sk-sensitive-value", first)

    assert is_encrypted_credential(encrypted)
    assert "sk-sensitive-value" not in encrypted
    assert decrypt_credential(encrypted, first) == "sk-sensitive-value"
    with pytest.raises(CredentialDecryptionError):
        decrypt_credential(encrypted, second)


def test_production_rejects_insecure_defaults():
    with pytest.raises(ValidationError, match="Invalid production security configuration"):
        Settings(environment="production")


def test_production_cookie_policy_uses_secure_httponly_cookies():
    settings = _production_settings()
    response = Response()

    attach_auth_cookies(response, "access-token", "refresh-token", settings)

    cookie_headers = [value.decode("latin-1") for name, value in response.raw_headers if name == b"set-cookie"]
    assert len(cookie_headers) == 3
    auth_headers = [header for header in cookie_headers if "travelmind_csrf=" not in header]
    csrf_header = next(header for header in cookie_headers if "travelmind_csrf=" in header)
    assert len(auth_headers) == 2
    assert all("HttpOnly" in header for header in auth_headers)
    assert "HttpOnly" not in csrf_header
    assert all("Secure" in header for header in cookie_headers)
    assert all("SameSite=lax" in header for header in cookie_headers)


def test_samesite_none_requires_secure_cookies():
    with pytest.raises(ValidationError, match="SameSite=None"):
        Settings(cookie_samesite="none", cookie_secure=False)
