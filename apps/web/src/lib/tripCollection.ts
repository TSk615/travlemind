import type { Trip } from "@travelmind/shared-types"

export type TripCollectionFilter = "all" | "planning" | "ready"

export function filterTripCollection(trips: Trip[], query: string, filter: TripCollectionFilter): Trip[] {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean)
  return trips.filter((trip) => {
    if (filter === "planning" && trip.itinerary) return false
    if (filter === "ready" && !trip.itinerary) return false
    const text = [trip.title, trip.origin, trip.destination, ...trip.interests].join(" ").toLocaleLowerCase()
    return terms.every((term) => text.includes(term))
  })
}

export function getTripDayCount(trip: Pick<Trip, "start_date" | "end_date">): number | null {
  // Use UTC calendar days, not local-midnight arithmetic (which is DST-sensitive).
  const parse = (value: string) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return NaN
    const date = new Date(`${value}T00:00:00Z`)
    return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value ? date.getTime() : NaN
  }
  const start = parse(trip.start_date)
  const end = parse(trip.end_date)
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null
  return Math.round((end - start) / 86_400_000) + 1
}
