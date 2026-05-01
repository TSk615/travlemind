from __future__ import annotations

import json
import re
from typing import Iterable

from travelmind_api.agents.base import PlanningRequest
from travelmind_api.services.llm.client import OpenAICompatibleClient
from travelmind_api.services.llm.parser import LlmPlanningPayload, parse_planning_response

ZH_LOCALE = "zh-CN"
EN_LOCALE = "en-US"
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_ENGLISH_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+./_-]*")
_ALLOWED_ENGLISH_TOKENS = {
    "ai",
    "api",
    "app",
    "apps",
    "arq",
    "gpt",
    "http",
    "https",
    "json",
    "llm",
    "mcp",
    "openai",
    "pdf",
    "poi",
    "pois",
    "url",
    "urls",
    "wifi",
}


def normalize_output_locale(value: object | None, *, default: str = EN_LOCALE) -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith("zh"):
        return ZH_LOCALE
    if raw.startswith("en"):
        return EN_LOCALE
    return ZH_LOCALE if str(default).lower().startswith("zh") else EN_LOCALE



def infer_output_locale(request: PlanningRequest) -> str:
    if getattr(request, "locale", None):
        return normalize_output_locale(request.locale)

    combined = " ".join(
        [
            str(getattr(request, "title", "") or ""),
            str(getattr(request, "origin", "") or ""),
            str(getattr(request, "destination", "") or ""),
            str(getattr(request, "accommodation_preference", "") or ""),
            *(str(item or "") for item in getattr(request, "interests", []) or []),
        ]
    )
    return ZH_LOCALE if _contains_cjk(combined) else EN_LOCALE



def build_output_language_instruction(request_or_locale: PlanningRequest | str) -> str:
    locale = infer_output_locale(request_or_locale) if isinstance(request_or_locale, PlanningRequest) else normalize_output_locale(request_or_locale)
    if locale == ZH_LOCALE:
        return (
            "All user-visible narrative output must be in Simplified Chinese. "
            "Summary, risks, each day title, each day summary, each item note, and all booking or reservation narrative fields must be written as natural Simplified Chinese sentences. "
            "Except for proper nouns, route numbers, station names, brand names, or unavoidable technical terms, do not output complete English phrases or sentences in those fields. "
            "If a Chinese form is commonly used for a place or attraction, prefer the Chinese form first and only keep the original proper noun when necessary."
        )
    return (
        "All user-visible narrative output must be in concise English. "
        "Do not switch into Chinese except for unavoidable official names or source titles."
    )



def planning_payload_needs_language_repair(payload: LlmPlanningPayload, request_or_locale: PlanningRequest | str) -> bool:
    locale = infer_output_locale(request_or_locale) if isinstance(request_or_locale, PlanningRequest) else normalize_output_locale(request_or_locale)
    return any(_text_needs_language_repair(text, locale) for text in _iter_user_visible_texts(payload))



def enforce_planning_payload_language(
    payload: LlmPlanningPayload,
    request: PlanningRequest,
    llm_client: OpenAICompatibleClient,
) -> LlmPlanningPayload:
    locale = infer_output_locale(request)
    if not planning_payload_needs_language_repair(payload, locale):
        return payload

    repaired = repair_planning_payload_language(payload=payload, request=request, llm_client=llm_client)
    if planning_payload_needs_language_repair(repaired, locale):
        raise ValueError(f"Planning payload still violates target output locale {locale}")
    return repaired



def repair_planning_payload_language(
    *,
    payload: LlmPlanningPayload,
    request: PlanningRequest,
    llm_client: OpenAICompatibleClient,
) -> LlmPlanningPayload:
    locale = infer_output_locale(request)
    target_language = "Simplified Chinese" if locale == ZH_LOCALE else "English"
    messages = [
        {
            "role": "system",
            "content": (
                "You are TravelMind itinerary localization formatter. "
                "Return one valid JSON object only, with no markdown fences or prose outside JSON. "
                "Return only the rewritten itinerary object itself, not the wrapper fields such as target_locale, trip_request, rewrite_fields, preserve_fields, or itinerary. "
                f"Rewrite user-visible narrative fields into {target_language}. "
                "Preserve the JSON structure, field names, day count, item count, numbers, dates, times, scores, and budget values exactly. "
                "Do not rename destinations, attractions, hotels, or other proper nouns unless a standard localized form is obvious. "
                "Only rewrite the natural-language text so the output matches the requested language. "
                f"{build_output_language_instruction(locale)}"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "target_locale": locale,
                    "trip_request": {
                        "title": request.title,
                        "origin": request.origin,
                        "destination": request.destination,
                        "interests": request.interests,
                        "accommodation_preference": request.accommodation_preference,
                        "pace": request.pace,
                        "transport_mode": request.transport_mode,
                    },
                    "rewrite_fields": [
                        "summary",
                        "risks[]",
                        "days[].title",
                        "days[].summary",
                        "days[].items[].note",
                        "days[].items[].booking_info.price_label",
                        "days[].items[].booking_info.booking_window",
                        "days[].items[].booking_info.reminder",
                        "days[].items[].booking_info.notes[]",
                        "days[].items[].visit_requirements.reservation_policy",
                        "days[].items[].visit_requirements.advance_booking_note",
                        "days[].items[].visit_requirements.notes[]",
                        "transport_booking_summary.summary",
                        "transport_booking_summary.recommended_option",
                        "transport_booking_summary.booking_window",
                        "transport_booking_summary.pass_or_ticket_notes[]",
                        "transport_booking_summary.reminders[]",
                        "transport_booking_summary.notes[]",
                    ],
                    "preserve_fields": [
                        "total_budget_estimate",
                        "days[].total_cost",
                        "days[].items[].type",
                        "days[].items[].name",
                        "days[].items[].location",
                        "days[].items[].start_time",
                        "days[].items[].end_time",
                        "days[].items[].score",
                        "days[].items[].booking_info.estimated_price",
                        "days[].items[].booking_info.booking_required",
                        "days[].items[].booking_info.reservation_required",
                        "days[].items[].booking_info.official_booking_url",
                        "days[].items[].booking_info.source_urls[]",
                        "days[].items[].visit_requirements.timed_entry",
                        "days[].items[].visit_requirements.identity_required",
                        "transport_booking_summary.estimated_intercity_cost",
                        "transport_booking_summary.estimated_local_transport_cost",
                        "transport_booking_summary.booking_required",
                        "transport_booking_summary.official_booking_url",
                        "transport_booking_summary.source_urls[]",
                    ],
                    "itinerary": payload.model_dump(mode="json"),
                },
                ensure_ascii=False,
            ),
        },
    ]
    content = llm_client.create_chat_completion(messages=messages, temperature=0.1, max_tokens=2400)
    return parse_planning_response(content)



def is_chinese_output(request_or_locale: PlanningRequest | str) -> bool:
    locale = infer_output_locale(request_or_locale) if isinstance(request_or_locale, PlanningRequest) else normalize_output_locale(request_or_locale)
    return locale == ZH_LOCALE



def _iter_user_visible_texts(payload: LlmPlanningPayload) -> Iterable[str]:
    yield payload.summary
    for risk in payload.risks:
        yield risk
    for day in payload.days:
        yield day.title
        yield day.summary
        for item in day.items:
            yield item.note
            if item.booking_info is not None:
                for candidate in (
                    item.booking_info.price_label,
                    item.booking_info.booking_window,
                    item.booking_info.reminder,
                    *(item.booking_info.notes or []),
                ):
                    if candidate:
                        yield candidate
            if item.visit_requirements is not None:
                for candidate in (
                    item.visit_requirements.reservation_policy,
                    item.visit_requirements.advance_booking_note,
                    *(item.visit_requirements.notes or []),
                ):
                    if candidate:
                        yield candidate
    if payload.transport_booking_summary is not None:
        for candidate in (
            payload.transport_booking_summary.summary,
            payload.transport_booking_summary.recommended_option,
            payload.transport_booking_summary.booking_window,
            *(payload.transport_booking_summary.pass_or_ticket_notes or []),
            *(payload.transport_booking_summary.reminders or []),
            *(payload.transport_booking_summary.notes or []),
        ):
            if candidate:
                yield candidate



def _text_needs_language_repair(text: str, locale: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False

    english_tokens = _english_tokens(normalized)
    cjk_count = len(_CJK_RE.findall(normalized))

    if locale == ZH_LOCALE:
        if not english_tokens:
            return False
        if cjk_count == 0:
            return True
        return len(english_tokens) >= 4 and cjk_count < len(english_tokens) * 2

    if locale == EN_LOCALE:
        if cjk_count == 0:
            return False
        return not english_tokens or cjk_count >= max(4, len(english_tokens) * 2)

    return False



def _english_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _ENGLISH_TOKEN_RE.findall(text):
        normalized = match.strip().strip("._-/").casefold()
        if not normalized or normalized in _ALLOWED_ENGLISH_TOKENS:
            continue
        tokens.append(match)
    return tokens



def _contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(str(text or "")))
