from __future__ import annotations

import json
from datetime import date
from typing import Any

from fastapi import HTTPException, status

from travelmind_api.core.config import get_settings
from travelmind_api.core.upstream_urls import UpstreamUrlError, normalize_upstream_base_url
from travelmind_api.db.models import User
from travelmind_api.prompts.trip_intake import build_trip_intake_initial_prompt, build_trip_intake_system_prompt
from travelmind_api.services.llm import LlmConfig, OpenAICompatibleClient
from travelmind_api.services.llm.parser import _extract_json_payload
from travelmind_api.services.llm.user_config import build_user_poi_role_overrides

REQUIRED_FIELDS = (
    "origin",
    "destination",
    "start_date",
    "end_date",
    "budget",
    "travelers",
    "pace",
    "transport_mode",
    "interests",
)
OPTIONAL_FIELDS = ("accommodation_preference", "title")
ALL_FIELDS = (*REQUIRED_FIELDS, *OPTIONAL_FIELDS)


def _empty_draft() -> dict[str, Any]:
    return {
        "title": "",
        "origin": "",
        "destination": "",
        "start_date": "",
        "end_date": "",
        "budget": 0,
        "travelers": 0,
        "interests": [],
        "accommodation_preference": "",
        "pace": "",
        "transport_mode": "",
    }



def _normalize_text(value: Any) -> str:
    return str(value or "").strip()



def _normalize_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0



def _normalize_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0



def _normalize_date_text(value: Any, *, fallback_year: int | None = None) -> str:
    raw = _normalize_text(value)
    if not raw:
        return ""

    candidates = [raw.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").replace(".", "-")]
    for candidate in candidates:
        parts = [part for part in candidate.split("-") if part]
        if len(parts) == 3:
            try:
                year = int(parts[0])
                month = int(parts[1])
                day = int(parts[2])
                return date(year, month, day).isoformat()
            except ValueError:
                continue
        if len(parts) == 2:
            try:
                year = fallback_year or date.today().year
                month = int(parts[0])
                day = int(parts[1])
                return date(year, month, day).isoformat()
            except ValueError:
                continue
    return raw



def _normalize_interests(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = str(value or "").replace("，", ",").replace("、", ",").split(",")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        candidate = str(item or "").strip()
        if not candidate:
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(candidate)
    return normalized



def normalize_intake_draft(payload: dict[str, Any] | None) -> dict[str, Any]:
    base = _empty_draft()
    source = payload or {}
    base["title"] = _normalize_text(source.get("title"))
    base["origin"] = _normalize_text(source.get("origin"))
    base["destination"] = _normalize_text(source.get("destination"))
    start_date = _normalize_date_text(source.get("start_date"))
    fallback_year = None
    if start_date and len(start_date) >= 4 and start_date[:4].isdigit():
        fallback_year = int(start_date[:4])
    end_date = _normalize_date_text(source.get("end_date"), fallback_year=fallback_year)
    base["start_date"] = start_date
    base["end_date"] = end_date
    base["budget"] = _normalize_float(source.get("budget"))
    base["travelers"] = _normalize_int(source.get("travelers"))
    base["interests"] = _normalize_interests(source.get("interests"))
    base["accommodation_preference"] = _normalize_text(source.get("accommodation_preference"))
    pace = _normalize_text(source.get("pace")).lower()
    base["pace"] = pace if pace in {"slow", "balanced", "packed"} else ""
    transport = _normalize_text(source.get("transport_mode")).lower()
    base["transport_mode"] = transport if transport in {"auto", "rail", "flight", "car", "walking", "mixed"} else ""
    return base



def _derive_title(draft: dict[str, Any], locale: str) -> None:
    if _normalize_text(draft.get("title")):
        return
    destination = _normalize_text(draft.get("destination"))
    if not destination:
        return
    origin = _normalize_text(draft.get("origin"))
    if locale == "zh-CN":
        draft["title"] = f"{origin}出发去{destination}" if origin else f"{destination}行程"
        return
    draft["title"] = f"{destination} trip from {origin}" if origin else f"{destination} Trip"



def missing_intake_fields(draft: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field in REQUIRED_FIELDS:
        value = draft.get(field)
        if field == "budget" and not (_normalize_float(value) > 0):
            missing.append(field)
            continue
        if field == "travelers" and not (_normalize_int(value) >= 1):
            missing.append(field)
            continue
        if field == "interests" and len(_normalize_interests(value)) == 0:
            missing.append(field)
            continue
        if field in {"pace", "transport_mode", "origin", "destination", "start_date", "end_date"} and not _normalize_text(value):
            missing.append(field)
    return missing



def _resolve_llm_config(user: User) -> LlmConfig:
    config = LlmConfig.from_mapping(
        {
            "base_url": user.llm_base_url,
            "api_key": user.llm_api_key,
            "model": user.llm_model,
            "wire_api": user.llm_wire_api,
            "provider_protocol": getattr(user, "llm_provider_protocol", None),
            "role_overrides": build_user_poi_role_overrides(user),
        }
    )
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "trip_intake_llm_not_configured", "message": "Configure base_url, api_key, model, and API format before using guided chat intake."},
        )
    try:
        normalized_base_url = normalize_upstream_base_url(config.base_url, get_settings())
    except UpstreamUrlError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_upstream_base_url", "message": str(exc)},
        ) from exc
    return config.model_copy(update={"base_url": normalized_base_url}) if normalized_base_url else config



def run_trip_intake_chat(
    *,
    user: User,
    draft_payload: dict[str, Any] | None,
    messages: list[dict[str, str]],
    user_message: str | None,
) -> dict[str, Any]:
    draft = normalize_intake_draft(draft_payload)
    locale = getattr(user, "locale", "zh-CN") or "zh-CN"

    if not _normalize_text(user_message):
        _derive_title(draft, locale)
        missing = missing_intake_fields(draft)
        return {
            "assistant_message": build_trip_intake_initial_prompt(locale, missing),
            "draft": draft,
            "missing_required_fields": missing,
            "ready_to_create": len(missing) == 0,
        }

    config = _resolve_llm_config(user)
    client = OpenAICompatibleClient(config)
    normalized_messages = [
        {"role": str(message.get("role") or "assistant"), "content": str(message.get("text") or "").strip()}
        for message in messages[-8:]
        if str(message.get("text") or "").strip()
    ]
    latest_user_message = _normalize_text(user_message)
    system_prompt = build_trip_intake_system_prompt()
    user_payload = {
        "locale": locale,
        "current_draft": draft,
        "missing_required_fields": missing_intake_fields(draft),
        "conversation_history": normalized_messages,
        "latest_user_message": latest_user_message,
        "required_fields": list(REQUIRED_FIELDS),
        "optional_fields": list(OPTIONAL_FIELDS),
    }
    content = client.create_chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        temperature=0.2,
        max_tokens=700,
    )
    payload = _extract_json_payload(content)
    next_draft = normalize_intake_draft(payload.get("draft") if isinstance(payload, dict) else None)
    _derive_title(next_draft, locale)
    missing = missing_intake_fields(next_draft)
    assistant_message = _normalize_text(payload.get("assistant_message") if isinstance(payload, dict) else "")
    if not assistant_message:
        assistant_message = build_trip_intake_initial_prompt(locale, missing)
    return {
        "assistant_message": assistant_message,
        "draft": next_draft,
        "missing_required_fields": missing,
        "ready_to_create": len(missing) == 0,
    }
