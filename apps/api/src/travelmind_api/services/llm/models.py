from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel

from travelmind_api.services.llm.config import default_base_url_for_protocol, normalize_provider_protocol


class LlmModelInfo(BaseModel):
    id: str
    name: str | None = None
    description: str | None = None
    owned_by: str | None = None
    created_at: str | int | None = None
    input_token_limit: int | None = None
    output_token_limit: int | None = None


class LlmModelListResult(BaseModel):
    provider_protocol: str
    base_url: str
    models: list[LlmModelInfo]


def _build_models_url(provider_protocol: str, base_url: str) -> str:
    protocol = normalize_provider_protocol(provider_protocol)
    base = base_url.strip().rstrip("/")
    if protocol in {"openai", "newapi", "neiapi"}:
        if base.endswith("/models"):
            return base
        if base.endswith("/chat/completions"):
            return f"{base[: -len('/chat/completions')]}/models"
        if base.endswith("/responses"):
            return f"{base[: -len('/responses')]}/models"
        return f"{base}/models"
    if protocol == "gemini":
        normalized = base.removesuffix("/openai").rstrip("/")
        return normalized if normalized.endswith("/models") else f"{normalized}/models"
    if base.endswith("/models"):
        return base
    if base.endswith("/messages"):
        return f"{base[: -len('/messages')]}/models"
    return f"{base}/models"


def _headers_for_models(provider_protocol: str, api_key: str) -> dict[str, str]:
    protocol = normalize_provider_protocol(provider_protocol)
    if protocol == "gemini":
        return {"Accept": "application/json", "x-goog-api-key": api_key}
    if protocol == "claude":
        return {"Accept": "application/json", "anthropic-version": "2023-06-01", "x-api-key": api_key}
    return {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_openai_models(payload: Any) -> list[LlmModelInfo]:
    data = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        return []
    models: list[LlmModelInfo] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if not model_id:
            continue
        models.append(
            LlmModelInfo(
                id=model_id,
                name=str(item.get("name") or item.get("display_name") or model_id).strip() or model_id,
                owned_by=str(item.get("owned_by") or item.get("owner") or "").strip() or None,
                created_at=item.get("created") or item.get("created_at"),
            )
        )
    return models


def _parse_gemini_models(payload: Any) -> list[LlmModelInfo]:
    data = payload.get("models") if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        return []
    models: list[LlmModelInfo] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        raw_name = str(item.get("name") or "").strip()
        if not raw_name:
            continue
        supported = item.get("supportedGenerationMethods")
        if isinstance(supported, list) and "generateContent" not in supported:
            continue
        model_id = raw_name.removeprefix("models/")
        display_name = str(item.get("displayName") or model_id).strip() or model_id
        models.append(
            LlmModelInfo(
                id=model_id,
                name=display_name,
                description=str(item.get("description") or "").strip() or None,
                input_token_limit=_coerce_int(item.get("inputTokenLimit")),
                output_token_limit=_coerce_int(item.get("outputTokenLimit")),
            )
        )
    return models


def _parse_claude_models(payload: Any) -> list[LlmModelInfo]:
    data = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        return []
    models: list[LlmModelInfo] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if not model_id:
            continue
        models.append(
            LlmModelInfo(
                id=model_id,
                name=str(item.get("display_name") or item.get("name") or model_id).strip() or model_id,
                created_at=item.get("created_at"),
            )
        )
    return models


def _parse_models(provider_protocol: str, payload: Any) -> list[LlmModelInfo]:
    protocol = normalize_provider_protocol(provider_protocol)
    if protocol == "gemini":
        return _parse_gemini_models(payload)
    if protocol == "claude":
        return _parse_claude_models(payload)
    return _parse_openai_models(payload)


def fetch_llm_models(
    *,
    provider_protocol: str,
    base_url: str | None,
    api_key: str,
    timeout_seconds: float = 30.0,
    http_client: httpx.Client | None = None,
) -> LlmModelListResult:
    protocol = normalize_provider_protocol(provider_protocol)
    resolved_base_url = (base_url or default_base_url_for_protocol(protocol)).strip().rstrip("/")
    endpoint = _build_models_url(protocol, resolved_base_url)
    headers = _headers_for_models(protocol, api_key)

    if http_client is not None:
        response = http_client.get(endpoint, headers=headers)
    else:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            response = client.get(endpoint, headers=headers)
    response.raise_for_status()
    payload = response.json()
    return LlmModelListResult(
        provider_protocol=protocol,
        base_url=resolved_base_url,
        models=_parse_models(protocol, payload),
    )
