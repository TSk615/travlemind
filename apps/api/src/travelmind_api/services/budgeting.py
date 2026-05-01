from __future__ import annotations

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
    day_total_sum = round(sum(max(day.total_cost, 0.0) for day in enriched.days), 2)
    estimated_total = day_total_sum if day_total_sum > 0 else round(max(enriched.total_budget_estimate, 0.0), 2)
    enriched.total_budget_estimate = estimated_total

    totals = {category: 0.0 for category in _CATEGORY_ORDER}
    line_items: list[BudgetLineItem] = []

    for day in enriched.days:
        breakdown = _build_day_breakdown(day, request)
        day.budget_breakdown = breakdown
        for category in _CATEGORY_ORDER:
            amount = getattr(breakdown, category)
            totals[category] += amount
            if amount <= 0:
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

    total_breakdown = BudgetBreakdown(
        tickets=round(totals["tickets"], 2),
        dining=round(totals["dining"], 2),
        accommodation=round(totals["accommodation"], 2),
        transport=round(totals["transport"], 2),
        other=round(totals["other"], 2),
        total=round(sum(totals.values()), 2),
    )
    total_breakdown, line_items, estimated_total = _apply_transport_budget_override(
        total_breakdown,
        line_items,
        estimated_total=estimated_total,
        plan=enriched,
        zh_output=zh_output,
    )
    if estimated_total <= 0:
        estimated_total = total_breakdown.total
    enriched.total_budget_estimate = estimated_total

    requested_budget = round(max(request.budget, 0.0), 2)
    remaining_budget = round(max(requested_budget - estimated_total, 0.0), 2)
    over_budget = round(max(estimated_total - requested_budget, 0.0), 2)
    utilization_ratio = round((estimated_total / requested_budget) if requested_budget > 0 else 0.0, 4)
    status = _resolve_budget_status(requested_budget, estimated_total)

    enriched.budget_summary = BudgetSummary(
        requested_budget=requested_budget,
        estimated_total=estimated_total,
        remaining_budget=remaining_budget,
        over_budget=over_budget,
        utilization_ratio=utilization_ratio,
        status=status,
        breakdown=total_breakdown,
        line_items=line_items,
    )

    budget_risk = _build_budget_risk(status, requested_budget, estimated_total, over_budget, zh_output=zh_output)
    if budget_risk and budget_risk not in enriched.risks:
        enriched.risks.append(budget_risk)

    return enriched


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
    if item_type in {"transit", "transport"}:
        return "transport"
    if item_type in {"hotel", "stay"}:
        return "accommodation"
    if item_type in {"meal", "food"}:
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
    return round(max(numeric, 0.0), 2)
