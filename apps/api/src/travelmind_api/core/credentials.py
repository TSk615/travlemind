from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Engine, inspect, text
from sqlalchemy.types import Text, TypeDecorator

from travelmind_api.core.config import Settings, get_settings


ENCRYPTED_CREDENTIAL_PREFIX = "travelmind:credential:v1:"
USER_CREDENTIAL_COLUMNS = (
    "llm_api_key",
    "poi_llm_api_key",
    "image_api_key",
    "search_service_api_key",
)


class CredentialDecryptionError(RuntimeError):
    pass


def _cipher(settings: Settings | None = None) -> Fernet:
    active_settings = settings or get_settings()
    secret = active_settings.credential_encryption_key.encode("utf-8")
    derived_key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(derived_key)


def is_encrypted_credential(value: str | None) -> bool:
    return bool(value and value.startswith(ENCRYPTED_CREDENTIAL_PREFIX))


def encrypt_credential(value: str | None, settings: Settings | None = None) -> str | None:
    if value is None:
        return None
    plaintext = str(value)
    if not plaintext:
        return plaintext
    token = _cipher(settings).encrypt(plaintext.encode("utf-8")).decode("ascii")
    return f"{ENCRYPTED_CREDENTIAL_PREFIX}{token}"


def decrypt_credential(value: str | None, settings: Settings | None = None) -> str | None:
    if value is None or not is_encrypted_credential(value):
        return value
    token = value.removeprefix(ENCRYPTED_CREDENTIAL_PREFIX)
    try:
        return _cipher(settings).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise CredentialDecryptionError(
            "Stored credentials could not be decrypted. Check TRAVELMIND_CREDENTIAL_ENCRYPTION_KEY."
        ) from exc


class EncryptedCredential(TypeDecorator[str | None]):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        del dialect
        return encrypt_credential(value)

    def process_result_value(self, value: str | None, dialect) -> str | None:
        del dialect
        return decrypt_credential(value)


def migrate_legacy_plaintext_credentials(engine: Engine) -> int:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return 0

    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    credential_columns = [column for column in USER_CREDENTIAL_COLUMNS if column in existing_columns]
    if not credential_columns:
        return 0

    migrated_values = 0
    with engine.begin() as connection:
        selected_columns = ", ".join(["id", *credential_columns])
        rows = connection.execute(text(f"SELECT {selected_columns} FROM users")).mappings().all()
        for row in rows:
            updates = {
                column: encrypt_credential(row[column])
                for column in credential_columns
                if row[column] and not is_encrypted_credential(row[column])
            }
            if not updates:
                continue
            assignments = ", ".join(f"{column} = :{column}" for column in updates)
            connection.execute(
                text(f"UPDATE users SET {assignments} WHERE id = :user_id"),
                {**updates, "user_id": row["id"]},
            )
            migrated_values += len(updates)
    return migrated_values
