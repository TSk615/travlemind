import { describe, expect, it } from "vitest"
import { buildJourneyPath, isCompactJourneyStop, journeyDayDate, journeyDurationMinutes, journeyImages, safeJourneySource } from "./journeyFlow"
describe("journey reading-order connector", () => {
  it("handles empty and single-point layouts without inventing a line", () => { expect(buildJourneyPath([])).toBe(""); expect(buildJourneyPath([{ x: 4, y: 8 }])).toBe("") })
  it("connects each actual marker with a bounded curve", () => { const p = buildJourneyPath([{ x: 40, y: 0 }, { x: 44, y: 160 }, { x: 40, y: 340 }]); expect(p).toBe("M 40 0 C 58 72, 26 88, 44 160 C 26 241, 58 259, 40 340") })
  it("rejects broken geometry instead of emitting NaN SVG coordinates", () => { expect(buildJourneyPath([{ x: NaN, y: 0 }, { x: 1, y: 2 }])).toBe("") })
})
describe("image provenance and fallbacks", () => {
  it.each(["javascript:alert(1)", "data:text/html,test", "file:///secret", "//example.com", "broken"])("does not expose unsafe source links: %s", value => { expect(safeJourneySource(value)).toBeNull() })
  it("keeps only http(s) sources", () => { expect(safeJourneySource("https://example.test/source")).toBe("https://example.test/source"); expect(safeJourneySource("http://example.test/source")).toBe("http://example.test/source") })
  it("accepts local assets without accepting protocol-relative hosts or data URLs", () => { expect(journeyImages(["/assets/lake.webp", "/assets/lake.webp", "javascript:x", "//host/a.jpg", "https://example.test/a.jpg"])).toEqual(["/assets/lake.webp", "https://example.test/a.jpg"]) })
})
describe("journey dates and times", () => {
  it("uses calendar-day offsets across month boundaries", () => { expect(journeyDayDate("2026-10-31", 1, "en-US")).toContain("Nov 1") })
  it.each(["invalid", "2026-02-30", "2026-1-1"])("does not fabricate a date for %s", date => expect(journeyDayDate(date, 0, "zh-CN")).toBe(""))
  it.each([
    ["09:00", "11:30", 0, 150], ["23:30", "01:00", 1, 90], ["23:30", "01:00", 0, null], ["", "12:00", 0, null], ["25:00", "12:00", 0, null]
  ])("computes %s–%s with explicit overnight offset %s", (start_time, end_time, end_day_offset, expected) => { expect(journeyDurationMinutes({ start_time: String(start_time), end_time: String(end_time), end_day_offset: Number(end_day_offset) })).toBe(expected) })
  it("keeps transfers and meals compact without suppressing sights", () => { expect(isCompactJourneyStop({ type: "meal" })).toBe(true); expect(isCompactJourneyStop({ type: "intercity_transport" })).toBe(true); expect(isCompactJourneyStop({ type: "sight" })).toBe(false) })
})
