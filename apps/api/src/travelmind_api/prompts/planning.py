from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from travelmind_api.prompts.types import PromptMessages
from travelmind_api.services.llm.localization import build_output_language_instruction, infer_output_locale

if TYPE_CHECKING:
    from travelmind_api.agents.base import PlanningRequest, PlanningResult


PLANNING_PROMPT_VERSION = "planning.main.v2"
REFINEMENT_PROMPT_VERSION = "planning.refine.v1"

PLANNING_OUTPUT_SCHEMA: dict[str, Any] = {
    "summary": "One paragraph overview of the trip.",
    "total_budget_estimate": 0,
    "risks": ["Potential logistics or budget risks."],
    "days": [
        {
            "title": "2026-04-14 | Kyoto Temples",
            "summary": "Brief summary for the day.",
            "total_cost": 0,
            "items": [
                {
                    "type": "sight",
                    "name": "Ginkaku-ji",
                    "start_time": "09:00",
                    "end_time": "11:00",
                    "location": "Kyoto",
                    "score": 0.85,
                    "note": "Why this stop fits the plan.",
                    "booking_info": {
                        "price_label": "Adult ticket around 500 JPY",
                        "estimated_price": 25,
                        "booking_required": False,
                        "reservation_required": False,
                        "official_booking_url": "",
                        "booking_window": "",
                        "reminder": "",
                        "notes": ["Leave the official booking URL blank if you cannot verify one."],
                        "source_urls": [],
                    },
                    "visit_requirements": {
                        "reservation_policy": "not_needed",
                        "timed_entry": False,
                        "identity_required": False,
                        "advance_booking_note": "",
                        "notes": ["Mention timed entry, closure, or reservation limits when known."],
                    },
                }
            ],
        }
    ],
    "transport_booking_summary": {
        "summary": "Rail is the best fit for this route and budget.",
        "recommended_option": "Osaka to Kyoto Station by rail",
        "estimated_intercity_cost": 280,
        "estimated_local_transport_cost": 45,
        "booking_required": False,
        "official_booking_url": "",
        "booking_window": "",
        "pass_or_ticket_notes": ["Prefer point-to-point tickets unless a pass is clearly cheaper."],
        "reminders": ["Leave the URL blank when you cannot verify an official booking page."],
        "notes": ["Explain uncertainty instead of inventing precise fare rules."],
        "source_urls": [],
    },
}


def build_planning_prompt_bundle(request: PlanningRequest) -> PromptMessages:
    output_locale = infer_output_locale(request)
    trip_payload = _build_trip_payload(request, output_locale)

    system_prompt = (
        "You are TravelMind AI, a travel itinerary planner. "
        "Return one valid JSON object only, with no markdown fences or prose outside JSON. "
        "Keep the number of days exactly equal to the requested trip length. "
        "Each day must contain 2 to 4 items. "
        "Use 24-hour HH:MM times, realistic sequencing, and scores between 0 and 1. "
        "Keep the total budget estimate aligned with the requested budget whenever feasible, and use risks to explain unavoidable budget pressure. "
        "When grounded information is available, include per-item booking_info and visit_requirements plus a trip-level transport_booking_summary. "
        "Prefer official booking URLs. Leave any booking URL blank instead of inventing one. "
        "For Chinese output, summary, risks, each day title, each day summary, each item note, and booking or reservation narrative text must be natural Simplified Chinese. "
        "Except for proper nouns or unavoidable route and brand terms, do not output complete English phrases or sentences in those fields. "
        f"{build_output_language_instruction(output_locale)} "
        f"The JSON schema shape must match this example: {json.dumps(PLANNING_OUTPUT_SCHEMA, ensure_ascii=True)}"
    )
    user_prompt = (
        "Create a practical itinerary draft for this trip request. "
        "Prefer grounded, logistically coherent activities that fit the destination, budget, pace, and interests. "
        f"Target output locale: {output_locale}. "
        f"Trip request: {json.dumps(trip_payload, ensure_ascii=True)}"
    )
    return PromptMessages(
        version=PLANNING_PROMPT_VERSION,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )



def build_refinement_prompt_bundle(
    request: PlanningRequest,
    current_plan: PlanningResult,
    *,
    instruction: str,
    scope: str,
    day_index: int | None,
) -> PromptMessages:
    output_locale = infer_output_locale(request)
    trip_payload = _build_trip_payload(request, output_locale)
    current_itinerary = current_plan.model_dump(mode="json", exclude={"trace"})
    refinement_payload = {
        "trip_request": trip_payload,
        "current_itinerary": current_itinerary,
        "refine_instruction": {
            "instruction": instruction,
            "scope": scope,
            "day_index": day_index,
        },
        "refinement_rules": [
            "Treat the current itinerary as the source of truth.",
            "Preserve structure, pacing, and unchanged content unless the refine instruction requires edits.",
            "If day_index is provided, keep all other days as close to the current itinerary as possible.",
            "Always return the full updated itinerary JSON, not a patch or commentary.",
            "Do not drop valid context from the current itinerary unless the refine instruction explicitly conflicts with it.",
        ],
        "output_schema": PLANNING_OUTPUT_SCHEMA,
    }

    system_prompt = (
        "You are TravelMind AI, refining an existing itinerary. "
        "Return one valid JSON object only, with no markdown fences or prose outside JSON. "
        "The current itinerary is authoritative context. Modify only what is necessary to satisfy the refine direction, and preserve all other useful content. "
        "Keep the number of days exactly equal to the requested trip length. "
        "Each day must contain 2 to 4 items. "
        "Use 24-hour HH:MM times, realistic sequencing, and scores between 0 and 1. "
        "Keep the total budget estimate aligned with the requested budget whenever feasible, and use risks to explain unavoidable budget pressure. "
        "When grounded information is available, preserve or refresh per-item booking_info and visit_requirements plus the trip-level transport_booking_summary. "
        "Prefer official booking URLs. Leave any booking URL blank instead of inventing one. "
        "For Chinese output, summary, risks, each day title, each day summary, each item note, and booking or reservation narrative text must be natural Simplified Chinese. "
        "Except for proper nouns or unavoidable route and brand terms, do not output complete English phrases or sentences in those fields. "
        f"{build_output_language_instruction(output_locale)} "
        f"The JSON schema shape must match this example: {json.dumps(PLANNING_OUTPUT_SCHEMA, ensure_ascii=True)}"
    )
    user_prompt = (
        "Refine the current itinerary using the provided instruction. "
        "Preserve all unaffected context from the existing itinerary and return one full updated itinerary JSON object. "
        f"Target output locale: {output_locale}. "
        f"Refinement payload: {json.dumps(refinement_payload, ensure_ascii=True)}"
    )
    return PromptMessages(
        version=REFINEMENT_PROMPT_VERSION,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )



def build_planning_messages(request: PlanningRequest) -> list[dict[str, str]]:
    return build_planning_prompt_bundle(request).as_messages()



def _build_trip_payload(request: PlanningRequest, output_locale: str) -> dict[str, Any]:
    return {
        "trip_id": request.trip_id,
        "title": request.title,
        "origin": request.origin,
        "destination": request.destination,
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "budget": request.budget,
        "travelers": request.travelers,
        "interests": request.interests,
        "accommodation_preference": request.accommodation_preference,
        "pace": request.pace,
        "transport_mode": request.transport_mode,
        "output_locale": output_locale,
    }
