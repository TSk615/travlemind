"""Transport preference policy, independent of any supplier or model implementation."""
from __future__ import annotations


def transport_selection_policy(mode: str, *, same_city: bool = False) -> dict:
    normalized = (mode or "auto").strip().lower()
    automatic = normalized in {"auto", "any", "flexible", ""}
    return {
        "selection": "local_only" if same_city else "model_comparison" if automatic else "user_preference",
        "requested_mode": normalized,
        "compare_modes": [] if same_city else ["rail", "flight"] if automatic or normalized == "mixed" else [normalized],
        "criteria": ["total_party_cost", "door_to_door_minutes", "transfer_and_security_buffer", "travel_dates", "budget", "pace"],
        "railway_tool_does_not_imply_rail_preference": True,
        "unverified_fares_must_remain_unknown": True,
    }


def prefer_rail_followup(payload: dict) -> bool:
    """Only explicit rail preference can force railway to fill an evidence gap.

    Automatic/mixed choices keep generic search available for flight evidence.
    Tool availability is not a user preference or a model transport decision.
    """
    trip, context = payload.get("trip_request") or {}, payload.get("transport_context") or {}
    mode = str(trip.get("transport_mode") or context.get("transport_mode") or "auto").strip().lower()
    return context.get("intercity_required") is not False and mode in {"rail", "train"}


def _date_value(value):
    from datetime import date
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def transport_candidate_fits_dates(candidate, start_date, end_date) -> bool:
    """Reject an out-of-window service; never rewrite its sourced times/dates."""
    get = candidate.get if isinstance(candidate, dict) else lambda key: getattr(candidate, key, None)
    start, end = _date_value(start_date), _date_value(end_date)
    departure, arrival = _date_value(get("departure_date")), _date_value(get("arrival_date"))
    if start is None or end is None or departure is None:
        return True  # Missing dates remain the schema/evidence validator's responsibility.
    if not start <= departure <= end:
        return False
    if arrival is not None:
        return departure <= arrival <= end
    # A last-day overnight service cannot be assumed to arrive before the deadline.
    # Ambiguous cross-timezone flights need a sourced arrival date, not invented rollover.
    dep_time, arr_time = get("departure_time"), get("arrival_time")
    return not (departure == end and dep_time and arr_time and arr_time < dep_time)


def constrain_transport_dates(transport, start_date, end_date):
    normalized = transport.model_copy(deep=True)
    rejected = [c for c in normalized.service_candidates if not transport_candidate_fits_dates(c, start_date, end_date)]
    normalized.service_candidates = [c for c in normalized.service_candidates if transport_candidate_fits_dates(c, start_date, end_date)]
    rejected_legs = [leg for leg in normalized.legs if not transport_candidate_fits_dates(leg, start_date, end_date)]
    normalized.legs = [leg for leg in normalized.legs if transport_candidate_fits_dates(leg, start_date, end_date)]
    if rejected or rejected_legs:
        note = "已排除超出本次起止日期或无法确认按期到达的交通候选；返程必须在结束日期内到达，请比较更早班次或飞机，不得延长日期或改写来源时刻。"
        normalized.notes = list(dict.fromkeys([*normalized.notes, note]))
        normalized.transport_risks = list(dict.fromkeys([*normalized.transport_risks, note]))
        if hasattr(normalized, "unconfirmed_service_candidates"):
            normalized.unconfirmed_service_candidates.extend({"candidate": c.model_dump(mode="json"), "reason": "outside_trip_dates"} for c in rejected)
    return normalized
