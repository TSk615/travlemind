from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from travelmind_api.agents.base import PlanningRequest


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
                }
            ],
        }
    ],
}


def build_planning_messages(request: PlanningRequest) -> list[dict[str, str]]:
    trip_payload = {
        "trip_id": request.trip_id,
        "title": request.title,
        "destination": request.destination,
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "budget": request.budget,
        "travelers": request.travelers,
        "interests": request.interests,
        "accommodation_preference": request.accommodation_preference,
        "pace": request.pace,
        "transport_mode": request.transport_mode,
    }

    return [
        {
            "role": "system",
            "content": (
                "You are TravelMind AI, a travel itinerary planner. "
                "Return one valid JSON object only, with no markdown fences or prose outside JSON. "
                "Keep the number of days exactly equal to the requested trip length. "
                "Each day must contain 2 to 4 items. "
                "Use 24-hour HH:MM times, realistic sequencing, and scores between 0 and 1. "
                f"The JSON schema shape must match this example: {json.dumps(PLANNING_OUTPUT_SCHEMA, ensure_ascii=True)}"
            ),
        },
        {
            "role": "user",
            "content": (
                "Create a practical itinerary draft for this trip request. "
                "Prefer grounded, logistically coherent activities that fit the destination, budget, pace, and interests. "
                f"Trip request: {json.dumps(trip_payload, ensure_ascii=True)}"
            ),
        },
    ]