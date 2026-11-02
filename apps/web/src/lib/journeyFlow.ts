import type { ItineraryItem } from "@travelmind/shared-types"
export interface JourneyPoint { x: number; y: number }
// Reading order only: this connector does not represent geographic distances.
export function buildJourneyPath(points: JourneyPoint[]): string {
  if (points.length < 2 || points.some(p => !Number.isFinite(p.x) || !Number.isFinite(p.y))) return ""
  const n = (v: number) => Math.round(v * 10) / 10
  let path = `M ${n(points[0].x)} ${n(points[0].y)}`
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i], dy = Math.max(0, b.y - a.y)
    const bend = Math.min(18, dy / 5) * (i % 2 ? 1 : -1)
    path += ` C ${n(a.x + bend)} ${n(a.y + dy * .45)}, ${n(b.x - bend)} ${n(b.y - dy * .45)}, ${n(b.x)} ${n(b.y)}`
  }
  return path
}
export function safeJourneySource(value: string): string | null {
  try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) ? url.href : null } catch { return null }
}
export function journeyImages(values: string[] = []): string[] {
  return [...new Set(values.filter(v => safeJourneySource(v) || /^\/(?!\/)/.test(v)))]
}
export function isCompactJourneyStop(item: Pick<ItineraryItem, "type">): boolean {
  return ["transport", "intercity_transport", "local_transport", "flight", "train", "transfer", "meal", "food", "restaurant", "breakfast", "lunch", "dinner", "交通", "餐饮", "用餐"].includes(item.type.toLowerCase())
}
export function journeyDayDate(start: string, offset: number, locale: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(start)) return ""
  const date = new Date(`${start}T00:00:00Z`)
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== start) return ""
  date.setUTCDate(date.getUTCDate() + offset)
  return new Intl.DateTimeFormat(locale, { month: "short", day: "numeric", weekday: "short", timeZone: "UTC" }).format(date)
}
export function journeyDurationMinutes(item: Pick<ItineraryItem, "start_time" | "end_time" | "end_day_offset">): number | null {
  const parse = (value: string) => {
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(value)) return NaN
    const [h, m] = value.split(":").map(Number); return h * 60 + m
  }
  const duration = parse(item.end_time) - parse(item.start_time) + (item.end_day_offset ?? 0) * 1440
  return Number.isFinite(duration) && duration >= 0 ? duration : null
}
