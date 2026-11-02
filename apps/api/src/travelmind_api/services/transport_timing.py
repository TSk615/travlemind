"""Bind exact arrival dates to selected sourced services, not route summaries."""
from __future__ import annotations


def service_timing_errors(item, booking, transport, departure_date, arrival_date) -> list[str]:
    number = str(getattr(booking, "service_number", None) or "").strip().casefold()
    if not number:
        if getattr(booking, "schedule_verified", False):
            return [f"{item.name} 声称班次已核验，但未关联具体班次"]
        return []  # An explicitly unknown travel window is not a verified train.
    candidates = [c for c in getattr(transport, "service_candidates", [])
                  if str(getattr(c, "service_number", "")).strip().casefold() == number
                  and getattr(c, "scope", None) == booking.transport_scope
                  and getattr(c, "departure_date", None) == departure_date
                  and getattr(c, "evidence_status", "unknown") in {"verified", "referenced"}]
    if not candidates:
        if getattr(booking, "schedule_verified", False):
            return [f"{item.name} 未找到对应日期与方向的有来源班次，不能声称已核验"]
        return []
    timings = {(c.departure_time, c.arrival_time, c.arrival_date) for c in candidates}
    if len(timings) != 1:
        return [f"{item.name} 对应班次的来源时刻互相冲突"]
    candidate = candidates[0]
    errors = []
    if candidate.departure_time != item.start_time or candidate.arrival_time != item.end_time:
        errors.append(f"{item.name} 起止时间与所选有来源班次不一致")
    if candidate.arrival_date and candidate.arrival_date != arrival_date:
        errors.append(f"{item.name} 到达日期与所选有来源班次不一致")
    return errors
