from __future__ import annotations

from typing import Any

_SEARCH_ROLE_MODEL_ATTRIBUTES = {
    "poi_specialist": "poi_llm_model",
    "weather_specialist": "weather_llm_model",
    "hotel_specialist": "hotel_llm_model",
    "transport_specialist": "transport_llm_model",
}


def _has_text(value: object | None) -> bool:
    return bool(str(value or "").strip())


def user_poi_role_override_missing_fields(user: object | None) -> list[str]:
    if user is None:
        return []

    values = {
        "poi_base_url": getattr(user, "poi_llm_base_url", None),
        "poi_api_key": getattr(user, "poi_llm_api_key", None),
        "poi_model": getattr(user, "poi_llm_model", None),
    }
    if not any(_has_text(value) for value in values.values()):
        return []
    return [field for field, value in values.items() if not _has_text(value)]


def build_user_poi_role_overrides(user: object | None) -> dict[str, dict[str, Any]]:
    """Return per-role search models that share one saved endpoint and credential."""
    if user is None:
        return {}

    base_url = getattr(user, "poi_llm_base_url", None)
    api_key = getattr(user, "poi_llm_api_key", None)
    model = getattr(user, "poi_llm_model", None)
    if not (_has_text(base_url) and _has_text(api_key) and _has_text(model)):
        return {}

    saved_wire_api = getattr(user, "poi_llm_wire_api", None)
    provider_protocol = getattr(user, "poi_llm_provider_protocol", None)
    overrides: dict[str, dict[str, Any]] = {}
    for role_name, model_attribute in _SEARCH_ROLE_MODEL_ATTRIBUTES.items():
        role_model = getattr(user, model_attribute, None) or model
        override: dict[str, Any] = {
            "base_url": base_url,
            "api_key": api_key,
            "model": role_model,
        }
        normalized_model = str(role_model or "").strip().casefold()
        if normalized_model.startswith("console/"):
            override["wire_api"] = "responses"
        elif normalized_model.startswith("web/"):
            override["wire_api"] = "chat_completions"
        elif _has_text(saved_wire_api):
            override["wire_api"] = saved_wire_api
        if _has_text(provider_protocol):
            override["provider_protocol"] = provider_protocol
        overrides[role_name] = override
    return overrides
