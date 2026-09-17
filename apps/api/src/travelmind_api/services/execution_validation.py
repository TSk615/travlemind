from datetime import timedelta
import re


_CLOSED_WEEKDAY_PATTERNS = {
    0: (r"(?:每|逢)?(?:周一|星期一)(?:全天)?(?:闭馆|闭园|休馆|不开放)", r"(?:closed|not open)\s+(?:on\s+)?mondays?"),
    1: (r"(?:每|逢)?(?:周二|星期二)(?:全天)?(?:闭馆|闭园|休馆|不开放)", r"(?:closed|not open)\s+(?:on\s+)?tuesdays?"),
    2: (r"(?:每|逢)?(?:周三|星期三)(?:全天)?(?:闭馆|闭园|休馆|不开放)", r"(?:closed|not open)\s+(?:on\s+)?wednesdays?"),
    3: (r"(?:每|逢)?(?:周四|星期四)(?:全天)?(?:闭馆|闭园|休馆|不开放)", r"(?:closed|not open)\s+(?:on\s+)?thursdays?"),
    4: (r"(?:每|逢)?(?:周五|星期五)(?:全天)?(?:闭馆|闭园|休馆|不开放)", r"(?:closed|not open)\s+(?:on\s+)?fridays?"),
    5: (r"(?:每|逢)?(?:周六|星期六)(?:全天)?(?:闭馆|闭园|休馆|不开放)", r"(?:closed|not open)\s+(?:on\s+)?saturdays?"),
    6: (r"(?:每|逢)?(?:周日|周天|星期日|星期天)(?:全天)?(?:闭馆|闭园|休馆|不开放)", r"(?:closed|not open)\s+(?:on\s+)?sundays?"),
}


def has_closed_weekday_constraint(text: str, weekday: int) -> bool:
    return any(re.search(pattern, str(text or ""), re.I) for pattern in _CLOSED_WEEKDAY_PATTERNS[weekday])


def validate_timeline(payload, request, transport) -> list[str]:
    """Sort without moving clocks; validate intervals on one absolute timeline."""
    errors = []
    previous_end = -1
    previous_name = ""
    for index, day in enumerate(payload.days):
        day.items.sort(key=lambda item: item.start_time)
        for item in day.items:
            try:
                sh, sm = map(int, item.start_time.split(":"))
                eh, em = map(int, item.end_time.split(":"))
                if not (0 <= sh < 24 and 0 <= eh < 24 and 0 <= sm < 60 and 0 <= em < 60):
                    raise ValueError()
            except (ValueError, AttributeError):
                errors.append(f"{item.name} 缺少有效起止时间")
                continue
            start = index * 1440 + sh * 60 + sm
            end = (index + item.end_day_offset) * 1440 + eh * 60 + em
            if end <= start:
                errors.append(f"{item.name} 结束时间不晚于开始时间；跨夜必须填写 end_day_offset")
            if not item.end_day_offset and any(word in item.name + item.note for word in ("跨夜", "次日抵达", "overnight")):
                errors.append(f"{item.name} 描述跨夜但未填写跨日到达信息")
            if start < previous_end:
                errors.append(f"{previous_name} 与 {item.name} 时间重叠")
            if end > len(payload.days) * 1440:
                errors.append(f"{item.name} 到达时间超出行程结束日期")
            previous_end, previous_name = max(previous_end, end), item.name
            booking = item.booking_info
            target_date = request.start_date + timedelta(days=index)
            constraint_text = " ".join([
                str(item.note or ""),
                *([str(value) for value in booking.notes] if booking else []),
                *(
                    [
                        str(item.visit_requirements.advance_booking_note or ""),
                        *[str(value) for value in item.visit_requirements.notes],
                    ]
                    if item.visit_requirements else []
                ),
            ])
            if has_closed_weekday_constraint(constraint_text, target_date.weekday()):
                errors.append(f"{item.name} 安排在 {target_date.isoformat()}，但其证据注明当天闭馆")
            if item.type in {"hotel", "stay", "accommodation", "lodging"} and sh < 14 and (
                "入住" in item.name or "check-in" in item.name.lower()
            ) and (booking is None or not booking.early_check_in_confirmed):
                errors.append(f"{item.name} 提前入住未确认，应改为寄存行李或明确已确认提前入住")
            if booking:
                duration_min = booking.duration_minutes_min
                if duration_min and end - start < duration_min:
                    errors.append(f"{item.name} 出行窗口短于已提供的最短耗时 {duration_min} 分钟")
                if booking.transport_scope in {"outbound", "return", "intercity"}:
                    matching = [leg for leg in transport.legs if leg.scope == booking.transport_scope
                                and leg.departure_date == request.start_date + timedelta(days=index)]
                    for leg in matching:
                        if leg.duration_minutes_min and end - start < leg.duration_minutes_min:
                            errors.append(f"{item.name} 短于交通专家线路耗时")
                        if leg.arrival_date and leg.arrival_date != request.start_date + timedelta(days=index + item.end_day_offset):
                            errors.append(f"{item.name} 到达日期与交通段不一致")
                    before = [other for other in day.items if other is not item
                              and other.end_time <= item.start_time and not other.end_day_offset]
                    if before:
                        prior = max(before, key=lambda other: other.end_time)
                        # An explicit station arrival fixes the start of station dwell.
                        if prior.type in {"transport", "transit", "transfer"} and any(
                            token in prior.name for token in ("站", "机场", "airport", "station")
                        ):
                            prior_text = f"{prior.name} {prior.note}".casefold()
                            if any(token in prior_text for token in ("候车", "安检", "进站", "候机", "security", "waiting")):
                                continue
                            ph, pm = map(int, prior.end_time.split(":"))
                            if sh * 60 + sm - ph * 60 - pm < transport.station_buffer_minutes:
                                errors.append(f"{item.name} 到站后的安检候车缓冲不足")
                    if index == 0 and request.planning_generated_at and request.start_date == request.planning_generated_at.date():
                        now = request.planning_generated_at
                        earliest = now.hour * 60 + now.minute + 30 + transport.departure_transfer_minutes + transport.station_buffer_minutes
                        if sh * 60 + sm < earliest:
                            errors.append(f"{item.name} 当日出发未留足准备、接驳和候车时间")
                if item.type in {"hotel", "stay", "accommodation", "lodging"}:
                    if booking.check_in_date and booking.check_out_date:
                        nights = (booking.check_out_date - booking.check_in_date).days
                        if nights <= 0 or (booking.nights is not None and nights != booking.nights):
                            errors.append(f"{item.name} 入住、退房日期与晚数不一致")
    return errors
