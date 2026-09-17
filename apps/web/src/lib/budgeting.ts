import type { BudgetBreakdown, BudgetCategory, BudgetLineItem, BudgetStatus, BudgetSummary, GeneratedItinerary, ItineraryDay, Trip } from "@travelmind/shared-types"

const CATEGORY_ORDER: BudgetCategory[] = ["tickets", "dining", "accommodation", "transport", "other"]
const CATEGORY_LABELS: Record<BudgetCategory, string> = {
  tickets: "Tickets",
  dining: "Dining",
  accommodation: "Accommodation",
  transport: "Transport",
  other: "Other"
}
const BASE_WEIGHTS: Record<BudgetCategory, number> = {
  tickets: 0.7,
  dining: 1.0,
  accommodation: 1.4,
  transport: 0.6,
  other: 0.45
}
const ITEM_TYPE_WEIGHTS: Record<string, Partial<Record<BudgetCategory, number>>> = {
  sight: { tickets: 1.35 },
  photo: { tickets: 0.75 },
  meal: { dining: 1.65 },
  food: { dining: 1.65 },
  hotel: { accommodation: 2.3 },
  stay: { accommodation: 2.3 },
  transit: { transport: 1.55 },
  transport: { transport: 1.55 },
  explore: { other: 1.15 }
}

function roundCurrency(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100
}

function resolveAccommodationWeight(preference: string): number {
  const normalized = preference.trim().toLowerCase()
  if (["luxury", "resort", "five-star", "5-star"].some((item) => normalized.includes(item))) {
    return 1.9
  }
  if (["hostel", "budget", "capsule"].some((item) => normalized.includes(item))) {
    return 0.85
  }
  if (["boutique", "hotel", "ryokan"].some((item) => normalized.includes(item))) {
    return 1.5
  }
  return 1.25
}

function resolveTransportWeight(mode: string): number {
  const normalized = mode.trim().toLowerCase()
  if (["car", "drive", "driving"].includes(normalized)) {
    return 0.55
  }
  if (["rail", "train", "subway", "bus", "transit"].includes(normalized)) {
    return 0.35
  }
  if (["walking", "walk"].includes(normalized)) {
    return 0.15
  }
  return 0.25
}

function buildDayWeights(day: ItineraryDay, trip: Trip): Record<BudgetCategory, number> {
  const weights: Record<BudgetCategory, number> = { ...BASE_WEIGHTS }
  weights.accommodation = resolveAccommodationWeight(trip.accommodation_preference)
  weights.transport += resolveTransportWeight(trip.transport_mode)

  for (const item of day.items) {
    const mapped = ITEM_TYPE_WEIGHTS[item.type.trim().toLowerCase()] ?? {}
    for (const category of CATEGORY_ORDER) {
      weights[category] += mapped[category] ?? 0
    }
  }

  const transitionCount = Math.max(day.items.length - 1, 0)
  if (transitionCount > 0) {
    weights.transport += transitionCount * 0.28
  }

  return weights
}

function allocateAmounts(totalCost: number, weights: Record<BudgetCategory, number>): Record<BudgetCategory, number> {
  const safeWeights = Object.fromEntries(CATEGORY_ORDER.map((category) => [category, Math.max(weights[category], 0)])) as Record<BudgetCategory, number>
  const totalWeight = CATEGORY_ORDER.reduce((sum, category) => sum + safeWeights[category], 0)

  if (totalWeight <= 0) {
    const even = roundCurrency(totalCost / CATEGORY_ORDER.length)
    const equal = Object.fromEntries(CATEGORY_ORDER.map((category) => [category, even])) as Record<BudgetCategory, number>
    equal.other = roundCurrency(totalCost - CATEGORY_ORDER.filter((category) => category !== "other").reduce((sum, category) => sum + equal[category], 0))
    return equal
  }

  const raw = Object.fromEntries(CATEGORY_ORDER.map((category) => [category, (totalCost * safeWeights[category]) / totalWeight])) as Record<BudgetCategory, number>
  const rounded = Object.fromEntries(CATEGORY_ORDER.map((category) => [category, roundCurrency(raw[category])])) as Record<BudgetCategory, number>
  const diff = roundCurrency(totalCost - CATEGORY_ORDER.reduce((sum, category) => sum + rounded[category], 0))
  if (diff !== 0) {
    const dominant = CATEGORY_ORDER.reduce((winner, category) => (raw[category] > raw[winner] ? category : winner), CATEGORY_ORDER[0])
    rounded[dominant] = roundCurrency(rounded[dominant] + diff)
  }
  return rounded
}

function buildDayBreakdown(day: ItineraryDay, trip: Trip): BudgetBreakdown {
  const totalCost = roundCurrency(Math.max(day.total_cost, 0))
  if (totalCost <= 0) {
    return { tickets: 0, dining: 0, accommodation: 0, transport: 0, other: 0, total: 0 }
  }
  const groundedAmounts = resolveGroundedCategoryAmounts(day)
  const groundedTotal = roundCurrency(Object.values(groundedAmounts).reduce((sum, value) => sum + value, 0))
  if (groundedTotal <= 0) {
    const amounts = allocateAmounts(totalCost, buildDayWeights(day, trip))
    return {
      tickets: amounts.tickets,
      dining: amounts.dining,
      accommodation: amounts.accommodation,
      transport: amounts.transport,
      other: amounts.other,
      total: totalCost
    }
  }
  const boundedAmounts = scaleAmountsToTotal(groundedAmounts, totalCost)
  const remainingTotal = roundCurrency(Math.max(totalCost - Object.values(boundedAmounts).reduce((sum, value) => sum + value, 0), 0))
  const weights = buildDayWeights(day, trip)
  for (const category of CATEGORY_ORDER) {
    if (boundedAmounts[category] > 0) {
      weights[category] = 0
    }
  }
  const amounts =
    remainingTotal > 0
      ? CATEGORY_ORDER.reduce((sum, category) => sum + Math.max(weights[category], 0), 0) > 0
        ? allocateAmounts(remainingTotal, weights)
        : { tickets: 0, dining: 0, accommodation: 0, transport: 0, other: remainingTotal }
      : { tickets: 0, dining: 0, accommodation: 0, transport: 0, other: 0 }
  const combined = {
    tickets: roundCurrency(boundedAmounts.tickets + amounts.tickets),
    dining: roundCurrency(boundedAmounts.dining + amounts.dining),
    accommodation: roundCurrency(boundedAmounts.accommodation + amounts.accommodation),
    transport: roundCurrency(boundedAmounts.transport + amounts.transport),
    other: roundCurrency(boundedAmounts.other + amounts.other)
  }
  const combinedTotal = roundCurrency(Object.values(combined).reduce((sum, value) => sum + value, 0))
  const diff = roundCurrency(totalCost - combinedTotal)
  if (diff !== 0) {
    const dominant = CATEGORY_ORDER.reduce((winner, category) => (combined[category] > combined[winner] ? category : winner), CATEGORY_ORDER[0])
    combined[dominant] = roundCurrency(combined[dominant] + diff)
  }
  return {
    tickets: combined.tickets,
    dining: combined.dining,
    accommodation: combined.accommodation,
    transport: combined.transport,
    other: combined.other,
    total: totalCost
  }
}

function resolveGroundedCategoryAmounts(day: ItineraryDay): Record<BudgetCategory, number> {
  return day.items.reduce(
    (totals, item) => {
      const price = item.booking_info?.estimated_price
      if (typeof price === "number" && Number.isFinite(price) && price > 0) {
        totals[groundedBudgetCategoryForItem(item.type.trim().toLowerCase())] = roundCurrency(
          totals[groundedBudgetCategoryForItem(item.type.trim().toLowerCase())] + price
        )
      }
      return totals
    },
    { tickets: 0, dining: 0, accommodation: 0, transport: 0, other: 0 } as Record<BudgetCategory, number>
  )
}

function groundedBudgetCategoryForItem(itemType: string): BudgetCategory {
  if (["transit", "transport"].includes(itemType)) {
    return "transport"
  }
  if (["hotel", "stay", "accommodation", "lodging"].includes(itemType)) {
    return "accommodation"
  }
  if (["meal", "food"].includes(itemType)) {
    return "dining"
  }
  if (["sight", "photo"].includes(itemType)) {
    return "tickets"
  }
  return "other"
}

function scaleAmountsToTotal(amounts: Record<BudgetCategory, number>, totalCost: number): Record<BudgetCategory, number> {
  const bounded = {
    tickets: roundCurrency(Math.max(amounts.tickets, 0)),
    dining: roundCurrency(Math.max(amounts.dining, 0)),
    accommodation: roundCurrency(Math.max(amounts.accommodation, 0)),
    transport: roundCurrency(Math.max(amounts.transport, 0)),
    other: roundCurrency(Math.max(amounts.other, 0))
  }
  const rawTotal = roundCurrency(Object.values(bounded).reduce((sum, value) => sum + value, 0))
  if (rawTotal <= 0 || rawTotal <= totalCost) {
    return bounded
  }
  const scaled = {
    tickets: roundCurrency((bounded.tickets / rawTotal) * totalCost),
    dining: roundCurrency((bounded.dining / rawTotal) * totalCost),
    accommodation: roundCurrency((bounded.accommodation / rawTotal) * totalCost),
    transport: roundCurrency((bounded.transport / rawTotal) * totalCost),
    other: roundCurrency((bounded.other / rawTotal) * totalCost)
  }
  const scaledTotal = roundCurrency(Object.values(scaled).reduce((sum, value) => sum + value, 0))
  const diff = roundCurrency(totalCost - scaledTotal)
  if (diff !== 0) {
    const dominant = CATEGORY_ORDER.reduce((winner, category) => (bounded[category] > bounded[winner] ? category : winner), CATEGORY_ORDER[0])
    scaled[dominant] = roundCurrency(scaled[dominant] + diff)
  }
  return scaled
}

function resolveBudgetStatus(requestedBudget: number, estimatedTotal: number): BudgetStatus {
  if (requestedBudget <= 0) {
    return "under"
  }
  if (estimatedTotal > requestedBudget * 1.02) {
    return "over"
  }
  if (estimatedTotal > requestedBudget * 0.9) {
    return "near"
  }
  return "under"
}

export function enrichGeneratedItineraryWithBudget(trip: Trip, itinerary: GeneratedItinerary): GeneratedItinerary {
  // Preserve the dated, reconciled server ledger and its missing-cost warnings.
  if (itinerary.budget_summary) return itinerary
  const enrichedDays = itinerary.days.map((day) => ({
    ...day,
    budget_breakdown: buildDayBreakdown(day, trip)
  }))

  const breakdownTotals = enrichedDays.reduce(
    (acc, day) => {
      const breakdown = day.budget_breakdown ?? buildDayBreakdown(day, trip)
      acc.tickets += breakdown.tickets
      acc.dining += breakdown.dining
      acc.accommodation += breakdown.accommodation
      acc.transport += breakdown.transport
      acc.other += breakdown.other
      return acc
    },
    { tickets: 0, dining: 0, accommodation: 0, transport: 0, other: 0 }
  )

  let estimatedTotal = roundCurrency(
    enrichedDays.reduce((sum, day) => sum + Math.max(day.total_cost, 0), 0) || Math.max(itinerary.total_budget_estimate, 0)
  )
  const requestedBudget = roundCurrency(Math.max(trip.budget, 0))
  const breakdown: BudgetBreakdown = {
    tickets: roundCurrency(breakdownTotals.tickets),
    dining: roundCurrency(breakdownTotals.dining),
    accommodation: roundCurrency(breakdownTotals.accommodation),
    transport: roundCurrency(breakdownTotals.transport),
    other: roundCurrency(breakdownTotals.other),
    total: roundCurrency(Object.values(breakdownTotals).reduce((sum, value) => sum + value, 0))
  }
  let lineItems: BudgetLineItem[] = enrichedDays.flatMap((day) => {
    const items: BudgetLineItem[] = []
    const breakdown = day.budget_breakdown ?? buildDayBreakdown(day, trip)
    for (const category of CATEGORY_ORDER) {
      const amount = breakdown[category]
      if (amount <= 0) {
        continue
      }
      items.push({
        key: `day_${day.day_index}_${category}`,
        title: `Day ${day.day_index} ${CATEGORY_LABELS[category]}`,
        category,
        amount,
        day_index: day.day_index,
        note: day.title
      })
    }
    return items
  })
  const transportSummary = itinerary.transport_booking_summary
  if (transportSummary && (transportSummary.estimated_intercity_cost > 0 || transportSummary.estimated_local_transport_cost > 0)) {
    const groundedTransportTotal = roundCurrency(
      Math.max(transportSummary.estimated_intercity_cost, 0) + Math.max(transportSummary.estimated_local_transport_cost, 0)
    )
    const nonTransportTotal = roundCurrency(Math.max(breakdown.total - breakdown.transport, 0))
    breakdown.transport = groundedTransportTotal
    breakdown.total = roundCurrency(nonTransportTotal + groundedTransportTotal)
    estimatedTotal = breakdown.total > 0 ? breakdown.total : estimatedTotal
    lineItems = lineItems.filter((item) => item.category !== "transport")
    const transportNote =
      transportSummary.pass_or_ticket_notes?.[0] ??
      transportSummary.notes?.[0] ??
      transportSummary.reminders?.[0] ??
      transportSummary.summary ??
      null
    if (transportSummary.estimated_intercity_cost > 0) {
      lineItems.push({
        key: "trip_transport_intercity",
        title: "Intercity transport estimate",
        category: "transport",
        amount: roundCurrency(transportSummary.estimated_intercity_cost),
        note: transportNote
      })
    }
    if (transportSummary.estimated_local_transport_cost > 0) {
      lineItems.push({
        key: "trip_transport_local",
        title: "Local transport estimate",
        category: "transport",
        amount: roundCurrency(transportSummary.estimated_local_transport_cost),
        note: transportNote
      })
    }
  }
  const remainingBudget = roundCurrency(Math.max(requestedBudget - estimatedTotal, 0))
  const overBudget = roundCurrency(Math.max(estimatedTotal - requestedBudget, 0))
  const utilizationRatio = requestedBudget > 0 ? roundCurrency(estimatedTotal / requestedBudget) : 0
  const status = resolveBudgetStatus(requestedBudget, estimatedTotal)

  const risks = [...itinerary.risks]
  const riskMessage =
    status === "over"
      ? `预计花费超出预算 ${overBudget.toFixed(2)}。`
      : status === "near"
        ? `预计花费已接近预算上限（${estimatedTotal.toFixed(2)} / ${requestedBudget.toFixed(2)}）。`
        : null
  if (riskMessage && !risks.includes(riskMessage)) {
    risks.push(riskMessage)
  }

  return {
    ...itinerary,
    total_budget_estimate: estimatedTotal,
    days: enrichedDays,
    risks,
    budget_summary: {
      requested_budget: requestedBudget,
      estimated_total: estimatedTotal,
      remaining_budget: remainingBudget,
      over_budget: overBudget,
      utilization_ratio: utilizationRatio,
      status,
      breakdown,
      line_items: lineItems
    }
  }
}
