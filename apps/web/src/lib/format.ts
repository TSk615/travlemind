import { getActiveLocale } from "@/lib/i18n"

function getFormattingLocale(): string {
  return getActiveLocale()
}

function toDate(value: string): Date | null {
  // Backend payloads stay string-based, so the formatter layer is the single
  // place that tolerates partially invalid or not-yet-normalized date values.
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatDate(value: string): string {
  const date = toDate(value)
  if (!date) {
    return value
  }

  return new Intl.DateTimeFormat(getFormattingLocale(), {
    month: "short",
    day: "numeric",
    year: "numeric"
  }).format(date)
}

export function formatDateTime(value: string): string {
  const date = toDate(value)
  if (!date) {
    return value
  }

  return new Intl.DateTimeFormat(getFormattingLocale(), {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(date)
}

export function formatDateRange(start: string, end: string): string {
  return `${formatDate(start)} - ${formatDate(end)}`
}

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat(getFormattingLocale(), {
    style: "currency",
    currency: getFormattingLocale().startsWith("zh") ? "CNY" : "USD",
    maximumFractionDigits: 0
  }).format(value)
}