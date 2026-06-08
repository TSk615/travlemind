from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field

WireApi = Literal["chat_completions", "responses"]
LlmProviderProtocol = Literal["openai", "gemini", "claude", "newapi", "neiapi"]
_ROLE_OVERRIDE_ENV_PREFIX = "TRAVELMIND_LLM_ROLE_"


_DEFAULT_BASE_URLS: dict[LlmProviderProtocol, str] = {
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "claude": "https://api.anthropic.com/v1",
    "newapi": "http://localhost:3000/v1",
    "neiapi": "https://api.neiapi.com/v1",
}


def default_wire_api_for_protocol(protocol: object | None) -> WireApi:
    normalized = normalize_provider_protocol(protocol)
    if normalized in {"newapi", "neiapi"}:
        return "chat_completions"
    return "responses"


def normalize_wire_api_for_protocol(value: object | None, protocol: object | None) -> WireApi:
    normalized_protocol = normalize_provider_protocol(protocol)
    if normalized_protocol == "openai":
        return "responses"
    return normalize_wire_api(value, default=default_wire_api_for_protocol(normalized_protocol))


def normalize_wire_api(value: object | None, *, default: WireApi = "chat_completions") -> WireApi:
    candidate = str(value or "").strip().lower()
    if candidate in {"responses", "response"}:
        return "responses"
    if candidate in {"chat_completions", "chat/completions", "chat-completions", "chat"}:
        return "chat_completions"
    return default


def normalize_provider_protocol(value: object | None, *, default: LlmProviderProtocol = "openai") -> LlmProviderProtocol:
    candidate = str(value or "").strip().lower().replace("-", "_")
    if candidate in {"open", "openai", "openai_official", "official_openai", "openai_compatible", "compatible"}:
        return "openai"
    if candidate in {"gemini", "google", "google_gemini", "google_ai"}:
        return "gemini"
    if candidate in {"claude", "anthropic", "anthropic_claude"}:
        return "claude"
    if candidate in {"newapi", "new_api", "new_api_gateway", "new-api"}:
        return "newapi"
    if candidate in {"nei", "neiapi", "nei_api"}:
        return "neiapi"
    return default


def is_supported_provider_protocol(value: object | None) -> bool:
    candidate = str(value or "").strip().lower().replace("-", "_")
    return candidate in {
        "open",
        "openai",
        "openai_official",
        "official_openai",
        "openai_compatible",
        "compatible",
        "gemini",
        "google",
        "google_gemini",
        "google_ai",
        "claude",
        "anthropic",
        "anthropic_claude",
        "newapi",
        "new_api",
        "new_api_gateway",
        "new-api",
        "nei",
        "neiapi",
        "nei_api",
    }


def default_base_url_for_protocol(protocol: object | None) -> str:
    return _DEFAULT_BASE_URLS[normalize_provider_protocol(protocol)]


class LlmEndpointConfig(BaseModel):
    base_url: str
    api_key: str
    model: str
    wire_api: WireApi = "chat_completions"
    provider_protocol: LlmProviderProtocol = "openai"
    timeout_seconds: float = Field(default=30.0, gt=0)

    @property
    def endpoint_url(self) -> str:
        normalized_base = self.base_url.rstrip("/")
        if self.provider_protocol == "claude":
            if normalized_base.endswith("/messages"):
                return normalized_base
            return f"{normalized_base}/messages"
        if self.provider_protocol == "gemini":
            base = normalized_base.removesuffix("/openai").rstrip("/")
            model_name = self.model if self.model.startswith("models/") else f"models/{self.model}"
            if base.endswith("/models"):
                return f"{base}/{model_name.removeprefix('models/')}:generateContent"
            return f"{base}/{model_name}:generateContent"

        if self.wire_api == "responses":
            if normalized_base.endswith("/responses"):
                return normalized_base
            return f"{normalized_base}/responses"

        if normalized_base.endswith("/chat/completions"):
            return normalized_base
        return f"{normalized_base}/chat/completions"


def _config_values_from_mapping(
    payload: Mapping[str, object] | None,
    *,
    default: LlmEndpointConfig | None = None,
) -> dict[str, object] | None:
    if payload is None and default is None:
        return None

    raw_payload = payload or {}
    base_url = str(raw_payload.get("base_url") or getattr(default, "base_url", "")).strip().rstrip("/")
    api_key = str(raw_payload.get("api_key") or getattr(default, "api_key", "")).strip()
    model = str(raw_payload.get("model") or getattr(default, "model", "")).strip()
    provider_protocol = normalize_provider_protocol(
        raw_payload.get("provider_protocol") or raw_payload.get("protocol"),
        default=getattr(default, "provider_protocol", "openai"),
    )
    wire_api = normalize_wire_api_for_protocol(
        raw_payload.get("wire_api"),
        provider_protocol,
    )
    if raw_payload.get("wire_api") is None and default is not None:
        wire_api = normalize_wire_api_for_protocol(getattr(default, "wire_api", None), provider_protocol)
    timeout_raw = str(raw_payload.get("timeout_seconds") or getattr(default, "timeout_seconds", "30")).strip()

    if not base_url or not api_key or not model:
        return None

    try:
        timeout_seconds = float(timeout_raw)
    except ValueError:
        timeout_seconds = float(getattr(default, "timeout_seconds", 30.0))

    return {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "wire_api": wire_api,
        "provider_protocol": provider_protocol,
        "timeout_seconds": timeout_seconds,
    }


def _endpoint_config_from_mapping(
    payload: Mapping[str, object] | None,
    *,
    default: LlmEndpointConfig | None = None,
) -> LlmEndpointConfig | None:
    values = _config_values_from_mapping(payload, default=default)
    if values is None:
        return None
    return LlmEndpointConfig(**values)


def _role_override_from_env(role_name: str, *, default: LlmEndpointConfig) -> LlmEndpointConfig | None:
    prefix = f"{_ROLE_OVERRIDE_ENV_PREFIX}{role_name.upper()}_"
    raw_payload = {
        "base_url": os.getenv(f"{prefix}BASE_URL"),
        "api_key": os.getenv(f"{prefix}API_KEY"),
        "model": os.getenv(f"{prefix}MODEL"),
        "wire_api": os.getenv(f"{prefix}WIRE_API"),
        "provider_protocol": os.getenv(f"{prefix}PROVIDER_PROTOCOL") or os.getenv(f"{prefix}PROTOCOL"),
        "timeout_seconds": os.getenv(f"{prefix}TIMEOUT_SECONDS"),
    }
    if not any(value is not None and str(value).strip() for value in raw_payload.values()):
        return None
    return _endpoint_config_from_mapping(raw_payload, default=default)


def _collect_role_overrides_from_mapping(
    payload: Mapping[str, object] | None,
    *,
    default: LlmEndpointConfig,
) -> dict[str, LlmEndpointConfig]:
    raw_overrides = payload.get("role_overrides") if payload is not None else None
    if not isinstance(raw_overrides, Mapping):
        return {}

    overrides: dict[str, LlmEndpointConfig] = {}
    for raw_role_name, raw_override in raw_overrides.items():
        if not isinstance(raw_override, Mapping):
            continue
        role_name = str(raw_role_name or "").strip()
        if not role_name:
            continue
        override = _endpoint_config_from_mapping(raw_override, default=default)
        if override is not None:
            overrides[role_name] = override
    return overrides


def _collect_role_overrides_from_env(*, default: LlmEndpointConfig) -> dict[str, LlmEndpointConfig]:
    role_names: set[str] = set()
    for key, value in os.environ.items():
        if not key.startswith(_ROLE_OVERRIDE_ENV_PREFIX) or not str(value).strip():
            continue
        suffix = key[len(_ROLE_OVERRIDE_ENV_PREFIX) :]
        parts = suffix.split("_")
        if len(parts) < 2:
            continue
        role_name = "_".join(part.lower() for part in parts[:-1] if part)
        if role_name:
            role_names.add(role_name)

    overrides: dict[str, LlmEndpointConfig] = {}
    for role_name in sorted(role_names):
        override = _role_override_from_env(role_name, default=default)
        if override is not None:
            overrides[role_name] = override
    return overrides


class LlmConfig(LlmEndpointConfig):
    role_overrides: dict[str, LlmEndpointConfig] = Field(default_factory=dict)

    def config_for_role(self, role_name: str) -> LlmEndpointConfig:
        role_key = str(role_name or "").strip()
        return self.role_overrides.get(role_key) or LlmEndpointConfig(
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model,
            wire_api=self.wire_api,
            provider_protocol=self.provider_protocol,
            timeout_seconds=self.timeout_seconds,
        )

    @classmethod
    def from_env(cls) -> LlmConfig | None:
        default_config = _endpoint_config_from_mapping(
            {
                "base_url": os.getenv("TRAVELMIND_LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
                "api_key": os.getenv("TRAVELMIND_LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
                "model": os.getenv("TRAVELMIND_LLM_MODEL") or os.getenv("OPENAI_MODEL"),
                "wire_api": os.getenv("TRAVELMIND_LLM_WIRE_API") or os.getenv("OPENAI_WIRE_API"),
                "provider_protocol": (
                    os.getenv("TRAVELMIND_LLM_PROVIDER_PROTOCOL")
                    or os.getenv("TRAVELMIND_LLM_PROTOCOL")
                    or os.getenv("OPENAI_PROVIDER_PROTOCOL")
                    or os.getenv("OPENAI_PROTOCOL")
                ),
                "timeout_seconds": os.getenv("TRAVELMIND_LLM_TIMEOUT_SECONDS") or "30",
            }
        )
        if default_config is None:
            return None

        return cls(
            **default_config.model_dump(),
            role_overrides=_collect_role_overrides_from_env(default=default_config),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object] | None) -> LlmConfig | None:
        default_config = _endpoint_config_from_mapping(payload)
        if default_config is None:
            return None

        return cls(
            **default_config.model_dump(),
            role_overrides=_collect_role_overrides_from_mapping(payload, default=default_config),
        )
