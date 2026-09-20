from __future__ import annotations

from datetime import timedelta
from typing import Any

from travelmind_api.agents.base import PlanningRequest


def build_trip_request_payload(request: PlanningRequest) -> dict[str, Any]:
    """Build the credential-free trip payload shared by all orchestrators."""

    payload: dict[str, Any] = {
        "trip_id": request.trip_id,
        "title": request.title,
        "origin": request.origin,
        "destination": request.destination,
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "trip_days": max(1, (request.end_date - request.start_date).days + 1),
        "budget": request.budget,
        "travelers": request.travelers,
        "interests": list(request.interests),
        "accommodation_preference": request.accommodation_preference,
        "pace": request.pace,
        "transport_mode": request.transport_mode,
    }
    generated_at = request.planning_generated_at
    if generated_at is not None:
        local_generated_at = generated_at.astimezone() if generated_at.tzinfo is not None else generated_at
        earliest = local_generated_at.replace(second=0, microsecond=0) + timedelta(minutes=30)
        payload.update(
            {
                "planning_generated_at": local_generated_at.isoformat(timespec="minutes"),
                "current_local_date": local_generated_at.date().isoformat(),
                "current_local_time": local_generated_at.strftime("%H:%M"),
                "same_day_earliest_start_time": (
                    earliest.strftime("%H:%M") if request.start_date == local_generated_at.date() else None
                ),
            }
        )
    return payload

