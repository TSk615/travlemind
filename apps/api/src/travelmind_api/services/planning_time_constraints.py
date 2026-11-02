"""Expose the validator's clock boundary before drafting, not just after failure."""
from datetime import timedelta


def planning_time_constraints(request, transport) -> dict:
    policy = {
        "flexible_windows_only_in_actual_gaps": True,
        "flexible_windows_must_not_overlap_items_or_each_other": True,
        "do_not_move_verified_services_or_invent_later_departures": True,
        "exact_service_dates_and_clocks_bind_selected_sourced_service": True,
        "route_summary_is_not_a_verified_service_timetable": True,
        "schedule_allocation": {
            "sum_of_meal_transfer_buffer_flexible_minutes_must_not_exceed_item_duration": True,
            "buffer_minutes_is_additional_not_included_in_transfer_minutes": True,
            "unknown_components_remain_null_not_invented": True,
        },
    }
    generated = request.planning_generated_at
    if generated is None or request.start_date != generated.date():
        return policy
    preparation_minutes = 30
    transfer_minutes = max(0, transport.departure_transfer_minutes)
    station_minutes = max(0, transport.station_buffer_minutes)
    earliest = generated.replace(second=0, microsecond=0) + timedelta(
        minutes=preparation_minutes + transfer_minutes + station_minutes,
    )
    policy["same_day_departure"] = {
        "planning_generated_at": generated.isoformat(),
        "preparation_minutes": preparation_minutes,
        "departure_transfer_minutes": transfer_minutes,
        "station_buffer_minutes": station_minutes,
        "first_intercity_departure_not_before": earliest.isoformat(),
        "earliest_departure_day_offset": (earliest.date() - request.start_date).days,
        "instruction": (
            "首个城际出发必须晚于或等于该时间边界，不能只在备注中提醒。"
            "若已核验班次早于边界，不可修改班次时间或编造新班次；"
            "应选择有证据的可行安排，无法满足时明确说明限制。"
            "flexible_windows 只能覆盖实际留白，不得与已排项目或其他留白重叠。"
        ),
    }
    return policy
