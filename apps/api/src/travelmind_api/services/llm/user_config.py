from __future__ import annotations

from typing import Any

WEATHER_SPECIALIST_MODEL = "grok-4.20-multi-agent-medium"
_POI_MODEL_ROLES = ("poi_specialist", "hotel_specialist", "transport_specialist")


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
    """Return saved POI model overrides for roles that share the user's Grok endpoint."""
    if user is None:
        return {}

    base_url = getattr(user, "poi_llm_base_url", None)
    api_key = getattr(user, "poi_llm_api_key", None)
    model = getattr(user, "poi_llm_model", None)
    if not (_has_text(base_url) and _has_text(api_key) and _has_text(model)):
        return {}

    override: dict[str, Any] = {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
    }
    wire_api = getattr(user, "poi_llm_wire_api", None)
    provider_protocol = getattr(user, "poi_llm_provider_protocol", None)
    if _has_text(wire_api):
        override["wire_api"] = wire_api
    if _has_text(provider_protocol):
        override["provider_protocol"] = provider_protocol
    overrides = {role_name: dict(override) for role_name in _POI_MODEL_ROLES}
    weather_override = dict(override)
    weather_override["model"] = WEATHER_SPECIALIST_MODEL
    overrides["weather_specialist"] = weather_override
    return overrides
