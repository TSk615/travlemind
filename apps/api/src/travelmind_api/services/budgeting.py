from __future__ import annotations
import re
from datetime import timedelta
from math import isfinite

from travelmind_api.agents.base import (
    BudgetBreakdown,
    BudgetLineItem,
    BudgetSummary,
    PlannedDay,
    PlanningRequest,
    PlanningResult,
    TransportBookingSummary,
)
from travelmind_api.services.llm.localization import is_chinese_output

_CATEGORY_ORDER = ("tickets", "dining", "accommodation", "transport", "other")
_CATEGORY_LABELS = {
    "tickets": "Tickets",
    "dining": "Dining",
    "accommodation": "Accommodation",
    "transport": "Transport",
    "other": "Other",
}
_CATEGORY_LABELS_ZH = {
    "tickets": "\u95e8\u7968",
    "dining": "\u9910\u996e",
    "accommodation": "\u4f4f\u5bbf",
    "transport": "\u4ea4\u901a",
    "other": "\u5176\u4ed6",
}
_BASE_WEIGHTS = {
    "tickets": 0.7,
    "dining": 1.0,
    "accommodation": 1.4,
    "transport": 0.6,
    "other": 0.45,
}
_ITEM_TYPE_WEIGHTS = {
    "sight": {"tickets": 1.35},
    "photo": {"tickets": 0.75},
    "meal": {"dining": 1.65},
    "food": {"dining": 1.65},
    "hotel": {"accommodation": 2.3},
    "stay": {"accommodation": 2.3},
    "transit": {"transport": 1.55},
    "transport": {"transport": 1.55},
    "explore": {"other": 1.15},
}


def enrich_plan_with_budget(plan: PlanningResult, request: PlanningRequest) -> PlanningResult:
    enriched = plan.model_copy(deep=True)
    zh_output = is_chinese_output(request)
    stated_day_totals = {day.day_index: round(max(day.total_cost, 0.0), 2) for day in enriched.days}
    transport_override = _extract_transport_budget_override(enriched)
    _sync_transport_item_prices(enriched, request, transport_override)
    transport_total = round((transport_override[0] + transport_override[1]) if transport_override else 0.0, 2)
    transport_by_day, transport_lines = _transport_ledger(enriched, request, transport_override)

    totals = {category: 0.0 for category in _CATEGORY_ORDER}
    line_items: list[BudgetLineItem] = []
    for day in enriched.days:
        explicit = _resolve_grounded_category_amounts(day)
        if transport_override is not None:
            explicit["transport"] = transport_by_day.get(day.day_index, 0.0)
        breakdown = BudgetBreakdown(
            tickets=round(explicit["tickets"], 2),
            dining=round(explicit["dining"], 2),
            accommodation=round(explicit["accommodation"], 2),
            transport=round(explicit["transport"], 2),
            other=round(explicit["other"], 2),
            total=round(sum(explicit.values()), 2),
        )
        day.total_cost = breakdown.total
        day.budget_breakdown = breakdown
        for category in _CATEGORY_ORDER:
            amount = getattr(breakdown, category)
            totals[category] += amount
            if amount <= 0 or (category == "transport" and transport_override is not None):
                continue
            line_items.append(
                BudgetLineItem(
                    key=f"day_{day.day_index}_{category}",
                    title=_build_budget_line_title(day.day_index, category, zh_output),
                    category=category,
                    amount=amount,
                    day_index=day.day_index,
                    note=day.title,
                )
            )

    if transport_override is not None:
        line_items.extend(transport_lines)

    total_breakdown = BudgetBreakdown(
        tickets=round(totals["tickets"], 2),
        dining=round(totals["dining"], 2),
        accommodation=round(totals["accommodation"], 2),
        transport=round(totals["transport"], 2),
        other=round(totals["other"], 2),
        total=round(sum(totals.values()), 2),
    )
    estimated_total = total_breakdown.total
    transport_total = total_breakdown.transport
    enriched.total_budget_estimate = estimated_total
    if zh_output:
        enriched.summary = re.sub(
            r"(?:总(?:估算|预计)?费用(?:为|约)?|统一预算账本合计为)\s*\d+(?:\.\d+)?\s*元",
            f"统一预算账本合计为{estimated_total:g}元",
            enriched.summary,
        )
        # Models often phrase the same claim as “合计约XXXX元” or embed it
        # after a longer noun phrase.  Replace those numeric claims as well so
        # the prose cannot disagree with the deterministic ledger below.
        enriched.summary = re.sub(
            r"约\s*\d+(?:\.\d+)?\s*元",
            f"约{estimated_total:g}元",
            enriched.summary,
        )

    requested_budget = round(max(request.budget, 0.0), 2)
    remaining_budget = round(max(requested_budget - estimated_total, 0.0), 2)
    over_budget = round(max(estimated_total - requested_budget, 0.0), 2)
    utilization_ratio = round((estimated_total / requested_budget) if requested_budget > 0 else 0.0, 4)
    status = _resolve_budget_status(requested_budget, estimated_total)
    enriched.risks = [
        risk for risk in enriched.risks
        if not re.search(
            r"预计花费(?:超出|已接近)预算上限|Estimated spending (?:exceeds|is using most of)",
            str(risk),
            re.I,
        )
    ]
    if zh_output:
        enriched.risks = [
            _reconcile_budget_amount_claims(str(risk), remaining_budget=remaining_budget)
            for risk in enriched.risks
        ]

    enriched.budget_summary = BudgetSummary(
        incomplete=False,
        requested_budget=requested_budget,
        estimated_total=estimated_total,
        remaining_budget=remaining_budget,
        over_budget=over_budget,
        utilization_ratio=utilization_ratio,
        status=status,
        breakdown=total_breakdown,
        line_items=line_items,
        transport_budget_ratio=round(transport_total / requested_budget, 4) if requested_budget else None,
    )

    unknown = [
        f"第{day.day_index}天：{item.name}"
        for day in enriched.days for item in day.items
        if not (transport_override and _grounded_budget_category_for_item(item.type) == "transport")
        and (item.booking_info is None or (
            item.booking_info.price_status != "free"
            and (item.booking_info.estimated_price is None or item.booking_info.estimated_price <= 0)
        ))
    ]
    if not any(_grounded_budget_category_for_item(item.type) == "dining" for day in enriched.days for item in day.items):
        unknown.append("餐饮费用尚未计入")
    enriched.budget_summary.unpriced_items = unknown
    provisional = any("待核实" in (line.note or "") for line in transport_lines)
    if provisional:
        unknown.append("交通分段日期或金额待核实")
    enriched.budget_summary.incomplete = bool(unknown)
    if unknown:
        note = "预算尚有未计价或待核实项目；余额仅为已计费用后的余额，不代表全部行程的可支配结余。"
        if note not in enriched.risks:
            enriched.risks.append(note)
        if zh_output:
            sentences = [sentence.strip() for sentence in re.split(r"(?<=。)", enriched.summary) if sentence.strip()]
            sentences = [
                sentence for sentence in sentences
                if not (
                    "当前已计价小计" in sentence
                    or (
                        "预算" in sentence
                        and re.search(r"\d+(?:\.\d+)?\s*元|低于|不超|结余|余额", sentence)
                    )
                )
            ]
            incomplete_summary = (
                f"当前已计价小计为{estimated_total:g}元；待核实项目包括"
                f"{'、'.join(unknown[:3])}{'等' if len(unknown) > 3 else ''}，"
                "该金额不代表最终总费用或可支配结余。"
            )
            enriched.summary = "".join(sentences).strip() + incomplete_summary
    # Percentage claims in model prose are not a second budget authority.
    if enriched.transport_booking_summary:
        summary = enriched.transport_booking_summary
        for field in ("notes", "pass_or_ticket_notes", "reminders"):
            setattr(summary, field, [
                note for note in getattr(summary, field)
                if not (re.search(r"[%％]|百分之", note) and re.search(r"预算|budget", note, re.I))
            ])
        if requested_budget:
            summary.notes.append(f"交通预计 {transport_total:g}，占总预算 {transport_total / requested_budget:.1%}；该比例仅用于说明，不是支出上限。")

    budget_risk = _build_budget_risk(status, requested_budget, estimated_total, over_budget, zh_output=zh_output)
    if budget_risk and budget_risk not in enriched.risks:
        enriched.risks.append(budget_risk)

    totals_recalculated = any(
        stated_day_totals.get(day.day_index, 0.0) != round(day.total_cost, 2)
        for day in enriched.days
    )
    if totals_recalculated:
        reconciliation_note = (
            "预算已按项目价格明细和交通专项估算重新计算；规划器原始日总额及未分配的预算上限未计入预计支出。"
            if zh_output
            else "The budget was recalculated from itemized prices and the transport estimate; planner-stated day totals and unallocated budget capacity were not counted as estimated spending."
        )
        if reconciliation_note not in enriched.risks:
            enriched.risks.append(reconciliation_note)

    return enriched


def _sync_transport_item_prices(plan: PlanningResult, request: PlanningRequest, override) -> None:
    """Make visible transport item prices use the same totals as the ledger."""
    if override is None:
        return
    intercity_total, local_total, _ = override
    summary = plan.transport_booking_summary
    legs = list(summary.legs if summary else [])

    entries = []
    for day in plan.days:
        target_date = request.start_date + timedelta(days=max(day.day_index - 1, 0))
        for item in day.items:
            booking = item.booking_info
            if booking is None or not booking.transport_scope:
                continue
            entries.append((day.day_index, target_date, item, booking))

    intercity_entries = [row for row in entries if row[3].transport_scope != "local"]
    assigned: set[int] = set()
    for leg in [row for row in legs if row.scope != "local" and row.estimated_total is not None]:
        matches = [
            row for row in intercity_entries
            if id(row[2]) not in assigned
            and row[3].transport_scope == leg.scope
            and row[1] == leg.departure_date
        ]
        if len(matches) == 1:
            _set_transport_item_price(matches[0][3], float(leg.estimated_total))
            assigned.add(id(matches[0][2]))
    _scale_transport_entries(intercity_entries, intercity_total)

    local_entries = [row for row in entries if row[3].transport_scope == "local"]
    _scale_transport_entries(local_entries, local_total)


def _scale_transport_entries(entries, target_total: float) -> None:
    if not entries or target_total < 0:
        return
    current = []
    for row in entries:
        try:
            current.append(max(float(row[3].estimated_price or 0.0), 0.0))
        except (TypeError, ValueError):
            current.append(0.0)
    current_total = round(sum(current), 2)
    if abs(current_total - target_total) <= .02:
        return
    if current_total > 0:
        amounts = [round(target_total * amount / current_total, 2) for amount in current]
    else:
        share = round(target_total / len(entries), 2)
        amounts = [share for _ in entries]
    amounts[-1] = round(target_total - sum(amounts[:-1]), 2)
    for row, amount in zip(entries, amounts):
        _set_transport_item_price(row[3], amount)


def _set_transport_item_price(booking, amount: float) -> None:
    booking.estimated_price = round(max(amount, 0.0), 2)
    booking.price_status = "estimated" if amount > 0 else "free"
    label = str(booking.price_label or "").strip()
    if not label:
        return
    display_amount = f"{booking.estimated_price:g}"
    reconciled, replacements = re.subn(
        r"((?:合计|共)\s*(?:约)?)\s*\d+(?:\.\d+)?\s*元",
        rf"\g<1>{display_amount}元",
        label,
    )
    if replacements == 0 and any(marker in label for marker in ("两人", "全体旅客", "总额", "市内交通")):
        reconciled = re.sub(r"约\s*\d+(?:\.\d+)?\s*元(?!.*元)", f"约{display_amount}元", label)
    booking.price_label = reconciled


def _reconcile_budget_amount_claims(text: str, *, remaining_budget: float) -> str:
    """Keep model-authored remaining-budget prose aligned with the ledger."""
    return re.sub(
        r"((?:剩余|余额|结余)\s*(?:约)?)\s*\d+(?:\.\d+)?\s*元",
        rf"\g<1>{remaining_budget:g}元",
        text,
    )


def _allocate_transport_to_days(days: list[PlannedDay], transport_total: float) -> dict[int, float]:
    if transport_total <= 0 or not days:
        return {}
    transport_days = [
        day.day_index
        for day in days
        if any(_normalize_item_type(item.type) in {"transit", "transport", "rail", "flight", "ferry"} for item in day.items)
    ]
    target_days = list(dict.fromkeys(transport_days or [days[0].day_index, days[-1].day_index]))
    per_day = round(transport_total / len(target_days), 2)
    allocations = {day_index: per_day for day_index in target_days}
    diff = round(transport_total - sum(allocations.values()), 2)
    if diff:
        allocations[target_days[-1]] = round(allocations[target_days[-1]] + diff, 2)
    return allocations


def _transport_ledger(plan: PlanningResult, request: PlanningRequest, override):
    """Use dated legs or priced items; label legacy allocations as provisional."""
    if override is None:
        return {}, []
    intercity, local, _ = override
    lines: list[BudgetLineItem] = []
    days = {day.day_index: 0.0 for day in plan.days}
    summary = plan.transport_booking_summary
    legs = summary.legs if summary else []
    for group, total in (("intercity", intercity), ("local", local)):
        if total <= 0:
            continue
        dated = []
        # Planner items are the actual dated allocation. An aggregate local
        # leg spanning several days must not be charged again on departure day.
        for day in plan.days:
            for item in day.items:
                booking = item.booking_info
                if booking and booking.transport_scope and (booking.transport_scope == "local") == (group == "local") and booking.estimated_price is not None:
                    dated.append((day.day_index, booking.estimated_price, item.name, "按项目费用记账"))
        if not dated or abs(sum(row[1] for row in dated) - total) > 0.02:
            dated = []
            candidates = [leg for leg in legs if (leg.scope == "local") == (group == "local")]
            for leg in candidates:
                index = (leg.departure_date - request.start_date).days + 1
                if index in days and leg.estimated_total is not None:
                    dated.append((index, leg.estimated_total, f"{leg.origin} → {leg.destination}", "按交通段发生日期记账"))
        if not dated or abs(sum(row[1] for row in dated) - total) > 0.02:
            if not plan.days:
                continue
            if group == "intercity":
                indexes = list(dict.fromkeys([plan.days[0].day_index, plan.days[-1].day_index]))
            else:
                indexes = [day.day_index for day in plan.days if any(
                    item.booking_info and item.booking_info.transport_scope == "local" for item in day.items
                )] or [plan.days[0].day_index]
            share = round(total / len(indexes), 2)
            dated = [(index, share, "城际交通" if group == "intercity" else "市内交通",
                      "缺少分段金额：暂按抵离日归集，日期与金额待核实") for index in indexes]
            last = dated[-1]
            dated[-1] = (last[0], round(total - share * (len(indexes) - 1), 2), last[2], last[3])
        for index, amount, title, note in dated:
            amount = round(amount, 2)
            days[index] += amount
            if amount > 0:
                lines.append(BudgetLineItem(key=f"transport_{group}_{len(lines)}", title=title,
                                           category="transport", amount=amount, day_index=index, note=note))
    return days, lines


def _build_day_breakdown(day: PlannedDay, request: PlanningRequest) -> BudgetBreakdown:
    total_cost = round(max(day.total_cost, 0.0), 2)
    if total_cost <= 0:
        return BudgetBreakdown()

    grounded_amounts = _resolve_grounded_category_amounts(day)
    grounded_total = round(sum(grounded_amounts.values()), 2)
    if grounded_total <= 0:
        weights = _build_day_weights(day, request)
        amounts = _allocate_amounts(total_cost, weights)
        return BudgetBreakdown(**amounts, total=round(total_cost, 2))

    bounded_amounts = _scale_amounts_to_total(grounded_amounts, total_cost)
    remaining_total = round(max(total_cost - sum(bounded_amounts.values()), 0.0), 2)
    weights = _build_day_weights(day, request)
    for category, amount in bounded_amounts.items():
        if amount > 0:
            weights[category] = 0.0
    if remaining_total > 0:
        if sum(max(weights.get(category, 0.0), 0.0) for category in _CATEGORY_ORDER) > 0:
            remainder = _allocate_amounts(remaining_total, weights)
        else:
            remainder = {category: 0.0 for category in _CATEGORY_ORDER}
            remainder["other"] = remaining_total
    else:
        remainder = {category: 0.0 for category in _CATEGORY_ORDER}

    combined = {
        category: round(bounded_amounts.get(category, 0.0) + remainder.get(category, 0.0), 2)
        for category in _CATEGORY_ORDER
    }
    diff = round(total_cost - sum(combined.values()), 2)
    if diff:
        dominant_category = max(_CATEGORY_ORDER, key=lambda category: combined[category])
        combined[dominant_category] = round(combined[dominant_category] + diff, 2)
    return BudgetBreakdown(**combined, total=round(total_cost, 2))


def _build_day_weights(day: PlannedDay, request: PlanningRequest) -> dict[str, float]:
    weights = dict(_BASE_WEIGHTS)
    weights["accommodation"] = _resolve_accommodation_weight(request.accommodation_preference)
    weights["transport"] += _resolve_transport_weight(request.transport_mode)

    for item in day.items:
        for category, delta in _ITEM_TYPE_WEIGHTS.get(_normalize_item_type(item.type), {}).items():
            weights[category] += delta

    transition_count = max(len(day.items) - 1, 0)
    if transition_count:
        weights["transport"] += transition_count * 0.28

    return weights


def _resolve_accommodation_weight(preference: str) -> float:
    normalized = (preference or "").strip().lower()
    if any(keyword in normalized for keyword in ("luxury", "resort", "five-star", "5-star")):
        return 1.9
    if any(keyword in normalized for keyword in ("hostel", "budget", "capsule")):
        return 0.85
    if any(keyword in normalized for keyword in ("boutique", "hotel", "ryokan")):
        return 1.5
    return 1.25


def _resolve_transport_weight(transport_mode: str) -> float:
    normalized = (transport_mode or "").strip().lower()
    if normalized in {"car", "drive", "driving"}:
        return 0.55
    if normalized in {"rail", "train", "subway", "bus", "transit"}:
        return 0.35
    if normalized in {"walking", "walk"}:
        return 0.15
    return 0.25


def _normalize_item_type(value: str) -> str:
    return (value or "other").strip().lower()


def _allocate_amounts(total_cost: float, weights: dict[str, float]) -> dict[str, float]:
    normalized_weights = {category: max(weights.get(category, 0.0), 0.0) for category in _CATEGORY_ORDER}
    total_weight = sum(normalized_weights.values())
    if total_weight <= 0:
        equal_share = round(total_cost / len(_CATEGORY_ORDER), 2)
        values = {category: equal_share for category in _CATEGORY_ORDER}
        values[_CATEGORY_ORDER[-1]] = round(total_cost - sum(values[category] for category in _CATEGORY_ORDER[:-1]), 2)
        return values

    raw = {category: total_cost * normalized_weights[category] / total_weight for category in _CATEGORY_ORDER}
    rounded = {category: round(raw[category], 2) for category in _CATEGORY_ORDER}
    diff = round(total_cost - sum(rounded.values()), 2)
    if diff:
        dominant_category = max(_CATEGORY_ORDER, key=lambda category: raw[category])
        rounded[dominant_category] = round(rounded[dominant_category] + diff, 2)
    return rounded


def _resolve_grounded_category_amounts(day: PlannedDay) -> dict[str, float]:
    totals = {category: 0.0 for category in _CATEGORY_ORDER}
    for item in day.items:
        booking_info = getattr(item, "booking_info", None)
        estimated_price = getattr(booking_info, "estimated_price", None)
        try:
            numeric = float(estimated_price)
        except (TypeError, ValueError):
            numeric = 0.0
        if numeric > 0:
            category = _grounded_budget_category_for_item(_normalize_item_type(item.type))
            totals[category] += numeric
    return {category: round(value, 2) for category, value in totals.items()}


def _grounded_budget_category_for_item(item_type: str) -> str:
    if item_type.endswith("_transport") or item_type in {
        "transit", "transport", "transfer", "metro", "subway", "bus", "taxi", "rail", "flight", "ferry",
    }:
        return "transport"
    if item_type in {"hotel", "stay", "accommodation", "lodging"}:
        return "accommodation"
    if item_type in {"meal", "food", "restaurant", "dining"}:
        return "dining"
    if item_type in {"sight", "photo"}:
        return "tickets"
    return "other"


def _scale_amounts_to_total(amounts: dict[str, float], total_cost: float) -> dict[str, float]:
    bounded = {category: round(max(amounts.get(category, 0.0), 0.0), 2) for category in _CATEGORY_ORDER}
    raw_total = round(sum(bounded.values()), 2)
    if raw_total <= 0 or raw_total <= total_cost:
        return bounded

    scaled = {
        category: round((bounded[category] / raw_total) * total_cost, 2)
        for category in _CATEGORY_ORDER
    }
    diff = round(total_cost - sum(scaled.values()), 2)
    if diff:
        dominant_category = max(_CATEGORY_ORDER, key=lambda category: bounded[category])
        scaled[dominant_category] = round(scaled[dominant_category] + diff, 2)
    return scaled


def _resolve_budget_status(requested_budget: float, estimated_total: float) -> str:
    if requested_budget <= 0:
        return "under"
    if estimated_total > requested_budget * 1.02:
        return "over"
    if estimated_total > requested_budget * 0.9:
        return "near"
    return "under"


def _build_budget_line_title(day_index: int, category: str, zh_output: bool) -> str:
    labels = _CATEGORY_LABELS_ZH if zh_output else _CATEGORY_LABELS
    prefix = f"\u7b2c {day_index} \u5929" if zh_output else f"Day {day_index}"
    return f"{prefix} {labels[category]}"


def _build_budget_risk(status: str, requested_budget: float, estimated_total: float, over_budget: float, *, zh_output: bool) -> str | None:
    if requested_budget <= 0:
        return None
    if status == "over":
        if zh_output:
            return f"\u9884\u8ba1\u82b1\u8d39\u8d85\u51fa\u9884\u7b97\u4e0a\u9650 {round(over_budget, 2)}\u3002"
        return f"Estimated spending exceeds the requested budget by {round(over_budget, 2)}."
    if status == "near":
        if zh_output:
            return f"\u9884\u8ba1\u82b1\u8d39\u5df2\u63a5\u8fd1\u9884\u7b97\u4e0a\u9650\uff08{round(estimated_total, 2)} / {round(requested_budget, 2)}\uff09\u3002"
        return f"Estimated spending is using most of the requested budget ({round(estimated_total, 2)} of {round(requested_budget, 2)})."
    return None


def _apply_transport_budget_override(
    breakdown: BudgetBreakdown,
    line_items: list[BudgetLineItem],
    *,
    estimated_total: float,
    plan: PlanningResult,
    zh_output: bool,
) -> tuple[BudgetBreakdown, list[BudgetLineItem], float]:
    override = _extract_transport_budget_override(plan)
    if override is None:
        return breakdown, line_items, estimated_total

    intercity_cost, local_cost, notes = override
    grounded_transport_total = round(intercity_cost + local_cost, 2)
    non_transport_total = round(max(breakdown.total - breakdown.transport, 0.0), 2)
    adjusted_total = round(non_transport_total + grounded_transport_total, 2)

    adjusted_breakdown = BudgetBreakdown(
        tickets=breakdown.tickets,
        dining=breakdown.dining,
        accommodation=breakdown.accommodation,
        transport=grounded_transport_total,
        other=breakdown.other,
        total=adjusted_total,
    )
    adjusted_line_items = [item for item in line_items if item.category != "transport"]
    adjusted_line_items.extend(_build_transport_line_items(intercity_cost, local_cost, notes, zh_output=zh_output))
    return adjusted_breakdown, adjusted_line_items, adjusted_total


def _extract_transport_budget_override(plan: PlanningResult) -> tuple[float, float, list[str]] | None:
    summary = getattr(plan, "transport_booking_summary", None)
    if isinstance(summary, TransportBookingSummary):
        for group, field in (("local", "estimated_local_transport_cost"), ("intercity", "estimated_intercity_cost")):
            legs = [leg for leg in summary.legs if (leg.scope == "local") == (group == "local")]
            if legs and all(leg.estimated_total is not None for leg in legs):
                setattr(summary, field, round(sum(leg.estimated_total for leg in legs), 2))
        intercity_cost = _coerce_positive_float(summary.estimated_intercity_cost)
        local_cost = _coerce_positive_float(summary.estimated_local_transport_cost)
        if intercity_cost > 0 or local_cost > 0:
            notes = [
                *[str(item).strip() for item in summary.pass_or_ticket_notes if str(item).strip()],
                *[str(item).strip() for item in summary.notes if str(item).strip()],
                *[str(item).strip() for item in summary.reminders if str(item).strip()],
            ]
            return intercity_cost, local_cost, notes[:3]

    guidance = getattr(getattr(plan, "trace", None), "transport_guidance", None)
    if not isinstance(guidance, dict):
        return None

    intercity_cost = _coerce_positive_float(guidance.get("estimated_intercity_cost"))
    local_cost = _coerce_positive_float(guidance.get("estimated_local_transport_cost"))
    if intercity_cost <= 0 and local_cost <= 0:
        return None

    raw_notes = guidance.get("budget_notes")
    notes = [str(item).strip() for item in raw_notes if str(item).strip()] if isinstance(raw_notes, list) else []
    return intercity_cost, local_cost, notes[:2]


def _build_transport_line_items(
    intercity_cost: float,
    local_cost: float,
    notes: list[str],
    *,
    zh_output: bool,
) -> list[BudgetLineItem]:
    line_items: list[BudgetLineItem] = []
    shared_note = (
        notes[0]
        if notes
        else ("\u6765\u81ea\u4ea4\u901a\u89c4\u5212 agent \u7684 grounded \u4f30\u7b97\u3002" if zh_output else "Grounded by the transport specialist.")
    )

    if intercity_cost > 0:
        line_items.append(
            BudgetLineItem(
                key="trip_transport_intercity",
                title="\u8de8\u57ce\u4ea4\u901a\u4f30\u7b97" if zh_output else "Intercity transport estimate",
                category="transport",
                amount=round(intercity_cost, 2),
                note=shared_note,
            )
        )
    if local_cost > 0:
        line_items.append(
            BudgetLineItem(
                key="trip_transport_local",
                title="\u672c\u5730\u4ea4\u901a\u4f30\u7b97" if zh_output else "Local transport estimate",
                category="transport",
                amount=round(local_cost, 2),
                note=shared_note,
            )
        )
    return line_items


def _coerce_positive_float(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(max(numeric, 0.0), 2) if isfinite(numeric) else 0.0
