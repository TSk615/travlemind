import { describe, expect, it } from "vitest"
import type { Trip } from "@travelmind/shared-types"
import { filterTripCollection, getTripDayCount } from "./tripCollection"
import { getTripCover } from "./portalAssets"

function trip(overrides: Partial<Trip> = {}): Trip {
  return {
    id: "trip-1", user_id: "user-1", title: "京都慢旅行", origin: "上海", destination: "京都",
    start_date: "2026-11-06", end_date: "2026-11-09", budget: 6800, travelers: 2,
    interests: ["咖啡", "Museums"], accommodation_preference: "安静", pace: "slow", transport_mode: "rail",
    created_at: "2026-10-16T00:00:00Z", updated_at: "2026-10-16T00:00:00Z", itinerary: null, ...overrides
  }
}

describe("travel studio collection", () => {
  const planning = trip()
  const ready = trip({ id: "trip-2", title: "湖畔周末", origin: "苏州", destination: "杭州", interests: ["湖泊"], itinerary: { summary: "A lakeside break", days: [], risks: [], total_budget_estimate: 1200 } })
  it("does not mutate or reorder the API collection", () => {
    const trips = [planning, ready]
    expect(filterTripCollection(trips, "", "all")).toEqual(trips)
    expect(trips).toEqual([planning, ready])
  })
  it.each(["京都", "上海 京都", "咖啡", "museums", "  MUSEUMS  "])("searches title, departure, destination and interests: %s", (query) => {
    expect(filterTripCollection([planning, ready], query, "all")).toEqual([planning])
  })
  it("combines the text query and actual itinerary state", () => {
    expect(filterTripCollection([planning, ready], "", "planning")).toEqual([planning])
    expect(filterTripCollection([planning, ready], "杭州", "ready")).toEqual([ready])
    expect(filterTripCollection([planning, ready], "京都", "ready")).toEqual([])
  })
  it("does not invent results for an empty account or an unmatched query", () => {
    expect(filterTripCollection([], "", "all")).toEqual([])
    expect(filterTripCollection([planning], "不存在", "all")).toEqual([])
  })
})

describe("inclusive trip calendar days", () => {
  it.each([
    ["2026-11-06", "2026-11-06", 1],
    ["2026-11-06", "2026-11-09", 4],
    ["2026-03-07", "2026-03-09", 3],
    ["2028-02-28", "2028-03-01", 3],
    ["2026-11-09", "2026-11-06", null],
    ["bad date", "2026-11-09", null],
    ["2026-02-30", "2026-03-03", null],
    ["2026-11-06", "", null]
  ])("counts %s to %s as %s", (start_date, end_date, expected) => {
    expect(getTripDayCount({ start_date, end_date })).toBe(expected)
  })
})

describe("concept cover assignment", () => {
  it("is deterministic across rerenders", () => expect(getTripCover("stable-id")).toBe(getTripCover("stable-id")))
  it("uses multiple covers without randomizing them on load", () => {
    expect(new Set(Array.from({ length: 20 }, (_, i) => getTripCover(`trip-${i}`))).size).toBe(3)
  })
})
