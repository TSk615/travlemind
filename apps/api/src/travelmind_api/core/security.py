import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from travelmind_api.core.config import Settings


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    iterations = 120000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations)
    # Encode iterations with the hash so the cost factor can change later
    # without forcing a global password reset or migration.
    return f"{iterations}${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    iterations_str, salt, digest = password_hash.split("$")
    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        int(iterations_str)
    ).hex()
    return hmac.compare_digest(candidate, digest)


def create_access_token(subject: dict[str, Any], settings: Settings) -> str:
    # Access tokens stay stateless; refresh tokens are the server-tracked handle
    # that lets us revoke browser sessions.
    payload = {
        **subject,
        "exp": _utcnow() + timedelta(minutes=settings.access_token_minutes),
        "iat": _utcnow()
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_workflow_id() -> str:
    return f"wf_{secrets.token_hex(8)}"


def generate_identifier(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(10)}"
