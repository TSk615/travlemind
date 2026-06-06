import type {
  AgentRunTrace,
  BookingInfo,
  GeneratedItinerary,
  ItineraryDay,
  ItineraryItem,
  SearchDocument,
  TransportBookingSummary,
  Trip,
  TripRefineInput,
  VisitRequirements
} from "@travelmind/shared-types"
import { ApiError, apiFetch, handleUnauthorizedStatus } from "@/lib/api"
import { enrichGeneratedItineraryWithBudget } from "@/lib/budgeting"
import type { RuntimeLlmConfig } from "@/stores/llmSettings"

interface BrowserPlanningResult {
  itinerary: GeneratedItinerary
  trace: AgentRunTrace
  rawText: string
}

interface BrowserLlmDay {
  title: string
  summary: string
  total_cost: number
  items: Array<{
    type: string
    name: string
    start_time: string
    end_time: string
    location: string
    score?: number
    note?: string
    booking_info?: BrowserLlmBookingInfo | null
    visit_requirements?: BrowserLlmVisitRequirements | null
  }>
}

interface BrowserLlmBookingInfo {
  price_label?: string | null
  estimated_price?: number | null
  booking_required?: boolean
  reservation_required?: boolean
  official_booking_url?: string | null
  booking_window?: string | null
  reminder?: string | null
  notes?: string[]
  source_urls?: string[]
}

interface BrowserLlmVisitRequirements {
  reservation_policy?: string | null
  timed_entry?: boolean
  identity_required?: boolean
  advance_booking_note?: string | null
  notes?: string[]
}

interface BrowserLlmTransportBookingSummary {
  summary?: string | null
  recommended_option?: string | null
  estimated_intercity_cost?: number
  estimated_local_transport_cost?: number
  booking_required?: boolean
  official_booking_url?: string | null
  booking_window?: string | null
  pass_or_ticket_notes?: string[]
  reminders?: string[]
  notes?: string[]
  source_urls?: string[]
}

interface BrowserLlmPayload {
  summary: string
  total_budget_estimate?: number
  risks?: string[]
  days: BrowserLlmDay[]
  transport_booking_summary?: BrowserLlmTransportBookingSummary | null
}

export async function generateTripInBrowser(
  config: RuntimeLlmConfig,
  trip: Trip,
  groundedDocs: SearchDocument[]
): Promise<BrowserPlanningResult> {
  const messages = buildMessages({ trip, groundedDocs })
  const rawText = await callModel(config, messages)
  const payload = parsePayload(rawText)
  return {
    itinerary: enrichGeneratedItineraryWithBudget(trip, toGeneratedItinerary(payload)),
    trace: createTrace(config, "Generated the itinerary via the backend relay.", groundedDocs),
    rawText
  }
}

export async function refineTripInBrowser(
  config: RuntimeLlmConfig,
  trip: Trip,
  groundedDocs: SearchDocument[],
  refineInput: TripRefineInput
): Promise<BrowserPlanningResult> {
  const messages = buildMessages({ trip, groundedDocs, refineInput })
  const rawText = await callModel(config, messages)
  const payload = parsePayload(rawText)
  return {
    itinerary: enrichGeneratedItineraryWithBudget(trip, toGeneratedItinerary(payload, trip.itinerary ?? undefined)),
    trace: createTrace(config, `Applied refine via backend relay with scope ${refineInput.scope}.`, groundedDocs),
    rawText
  }
}

async function callModel(config: RuntimeLlmConfig, messages: Array<{ role: string; content: string }>): Promise<string> {
  const responsesPayload = {
    model: config.model,
    stream: false,
    input: messages.map((message) => ({
      role: message.role,
      content: [
        {
          type: "input_text",
          text: message.content
        }
      ]
    }))
  }
  const chatPayload = {
    model: config.model,
    stream: false,
    messages
  }

  const invokeProxy = async (wireApi: RuntimeLlmConfig["wire_api"], payload: Record<string, unknown>) => {
    const response = await apiFetch("/api/v1/llm/proxy", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        provider_protocol: config.provider_protocol,
        wire_api: wireApi,
        payload
      })
    })
    const contentType = response.headers.get("content-type") ?? ""
    const isEventStream = contentType.includes("text/event-stream")
    const rawBody = await response.text()
    if (!response.ok) {
      handleUnauthorizedStatus(response.status)
      throw new ApiError(response.status, null, extractErrorMessage(rawBody, response.status))
    }
    return { isEventStream, rawBody }
  }

  if (config.wire_api === "responses") {
    const { isEventStream, rawBody } = await invokeProxy("responses", responsesPayload)
    try {
      return isEventStream ? extractResponsesTextFromSse(rawBody) : extractResponsesTextFromJson(rawBody)
    } catch {
      const fallback = await invokeProxy("chat_completions", chatPayload)
      return extractChatCompletionsTextFromJson(fallback.rawBody)
    }
  }

  const { rawBody } = await invokeProxy("chat_completions", chatPayload)
  return extractChatCompletionsTextFromJson(rawBody)
}

function extractErrorMessage(rawBody: string, status: number): string {
  try {
    const parsed = JSON.parse(rawBody) as { error?: { message?: string } | string; message?: string }
    if (typeof parsed.error === "string") {
      return parsed.error
    }
    if (typeof parsed.error?.message === "string") {
      return parsed.error.message
    }
    if (typeof parsed.message === "string") {
      return parsed.message
    }
  } catch {
    // Ignore parse failures.
  }

  return rawBody.trim() || `Model request failed with status ${status}`
}

function extractResponsesTextFromJson(rawBody: string): string {
  const body = JSON.parse(rawBody) as {
    output_text?: unknown
    output?: Array<{ content?: Array<{ text?: string }> | string }>
    response?: {
      output_text?: unknown
      output?: Array<{ content?: Array<{ text?: string }> | string }>
    }
    choices?: Array<{ message?: { content?: string | Array<{ text?: string }> } }>
  }

  if (typeof body.output_text === "string" && body.output_text.trim()) {
    return body.output_text
  }

  const textBlocks =
    body.output
      ?.flatMap((entry) => (Array.isArray(entry.content) ? entry.content : []))
      .map((item) => item.text)
      .filter((value): value is string => typeof value === "string" && value.trim().length > 0) ?? []
  if (textBlocks.length > 0) {
    return textBlocks.join("\n")
  }

  if (typeof body.response?.output_text === "string" && body.response.output_text.trim()) {
    return body.response.output_text
  }

  const nestedTextBlocks = body.response?.output
    ?.flatMap((entry) => (Array.isArray(entry.content) ? entry.content : []))
    .map((item) => item.text)
    .filter((value): value is string => typeof value === "string" && value.trim().length > 0)
  if (nestedTextBlocks && nestedTextBlocks.length > 0) {
    return nestedTextBlocks.join("\n")
  }

  const choiceContent = body.choices?.[0]?.message?.content
  if (typeof choiceContent === "string" && choiceContent.trim()) {
    return choiceContent
  }
  if (Array.isArray(choiceContent)) {
    const choiceTextBlocks = choiceContent.map((entry) => entry.text).filter((value): value is string => typeof value === "string" && value.trim().length > 0)
    if (choiceTextBlocks.length > 0) {
      return choiceTextBlocks.join("\n")
    }
  }

  throw new Error("Responses API did not return text output")
}

function extractResponsesTextFromSse(streamText: string): string {
  const dataLines = streamText
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data: "))
    .map((line) => line.slice(6))

  let combined = ""
  let completedText: string | null = null

  for (const line of dataLines) {
    if (!line || line === "[DONE]") {
      continue
    }

    let parsed: any
    try {
      parsed = JSON.parse(line)
    } catch {
      continue
    }

    if (parsed.type === "response.output_text.delta" && typeof parsed.delta === "string") {
      combined += parsed.delta
    }

    if (parsed.type === "response.output_text.done" && typeof parsed.text === "string") {
      completedText = parsed.text
    }

    if (parsed.type === "response.completed") {
      const outputText = parsed.response?.output?.flatMap((item: any) => item.content ?? []).map((item: any) => item.text).filter((value: unknown): value is string => typeof value === "string" && value.trim().length > 0)
      if (outputText && outputText.length > 0) {
        completedText = outputText.join("\n")
      }
    }
  }

  const finalText = completedText ?? combined
  if (finalText.trim()) {
    return finalText
  }

  throw new Error("Responses API stream did not contain assistant text")
}

function extractChatCompletionsTextFromJson(rawBody: string): string {
  const body = JSON.parse(rawBody) as {
    choices?: Array<{ message?: { content?: string | Array<{ text?: string }> } }>
  }

  const content = body.choices?.[0]?.message?.content
  if (typeof content === "string" && content.trim()) {
    return content
  }
  if (Array.isArray(content)) {
    const textBlocks = content.map((entry) => entry.text).filter((value): value is string => typeof value === "string" && value.trim().length > 0)
    if (textBlocks.length > 0) {
      return textBlocks.join("\n")
    }
  }

  throw new Error("Chat Completions API did not return message content")
}

function buildMessages({
  trip,
  groundedDocs,
  refineInput
}: {
  trip: Trip
  groundedDocs: SearchDocument[]
  refineInput?: TripRefineInput
}): Array<{ role: string; content: string }> {
  const tripPayload = {
    title: trip.title,
    origin: trip.origin,
    destination: trip.destination,
    start_date: trip.start_date,
    end_date: trip.end_date,
    budget: trip.budget,
    travelers: trip.travelers,
    interests: trip.interests,
    accommodation_preference: trip.accommodation_preference,
    pace: trip.pace,
    transport_mode: trip.transport_mode,
    existing_itinerary: trip.itinerary ?? null,
    grounded_sources: groundedDocs.slice(0, 6).map((doc) => ({
      title: doc.title,
      summary: doc.summary,
      platform: doc.platform,
      place_name: doc.place_name,
      category: doc.category,
      opening_hours: doc.opening_hours,
      address: doc.address,
      author: doc.author,
      published_at: doc.published_at,
      engagement_hint: doc.engagement_hint,
      source_tags: doc.source_tags ?? [],
      source_type: doc.source_type,
      url: doc.url
    })),
    refine_instruction: refineInput ?? null,
    output_language: "zh-CN"
  }

  const systemPrompt = refineInput
    ? "You are TravelMind AI, refining an existing itinerary. Return one valid JSON object only. No markdown, no commentary. All user-visible output must be in Simplified Chinese. The current itinerary is authoritative context. Modify only what is required by the refine instruction and preserve all other useful content whenever possible. Keep the number of days exactly equal to the requested trip length. Each day must contain title, summary, total_cost, and items. Each item must contain type, name, start_time, end_time, location, score, and note. When known, include item-level booking_info and visit_requirements plus the itinerary-level transport_booking_summary. Prefer official booking URLs and leave any booking URL blank instead of inventing one. Summary, risks, each day title, each day summary, each item note, and booking or reservation narrative text must be natural Simplified Chinese. Except for proper nouns, route numbers, station names, brand names, or unavoidable technical terms, do not output complete English phrases or sentences in those fields. Use HH:MM 24-hour time and scores between 0 and 1. Always return the full updated itinerary JSON, not a patch. Keep the total budget estimate aligned with the requested budget whenever feasible, and use risks to explain unavoidable budget pressure."
    : "You are TravelMind AI. Return one valid JSON object only. No markdown, no commentary. All user-visible output must be in Simplified Chinese. The object must contain summary, total_budget_estimate, risks, transport_booking_summary, and days. Each day must contain title, summary, total_cost, and items. Each item must contain type, name, start_time, end_time, location, score, and note. When known, include item-level booking_info and visit_requirements. Prefer official booking URLs and leave any booking URL blank instead of inventing one. Summary, risks, each day title, each day summary, each item note, and booking or reservation narrative text must be natural Simplified Chinese. Except for proper nouns, route numbers, station names, brand names, or unavoidable technical terms, do not output complete English phrases or sentences in those fields. Use HH:MM 24-hour time and scores between 0 and 1. Keep the total budget estimate aligned with the requested budget whenever feasible, and use risks to explain unavoidable budget pressure."

  const userPrompt = refineInput
    ? JSON.stringify({
        mode: "refine",
        rules: [
          "Treat existing_itinerary as the source of truth.",
          "Keep unchanged parts of the itinerary as close as possible to the current version.",
          "If day_index is present, focus changes on that day and avoid unnecessary edits to other days.",
          "Return one full updated itinerary JSON object."
        ],
        payload: tripPayload
      })
    : JSON.stringify(tripPayload)

  return [
    {
      role: "system",
      content: systemPrompt
    },
    {
      role: "user",
      content: userPrompt
    }
  ]
}

function parsePayload(rawText: string): BrowserLlmPayload {
  const trimmed = rawText.trim()
  const unwrapped = trimmed.startsWith("```") ? trimmed.replace(/^```\w*\s*/, "").replace(/```$/, "").trim() : trimmed
  const start = unwrapped.indexOf("{")
  const end = unwrapped.lastIndexOf("}")
  const candidate = start >= 0 && end > start ? unwrapped.slice(start, end + 1) : unwrapped
  const payload = JSON.parse(candidate) as BrowserLlmPayload

  if (!payload.summary || !Array.isArray(payload.days) || payload.days.length === 0) {
    throw new Error("Model response did not contain a valid itinerary payload")
  }

  return payload
}

function toGeneratedItinerary(payload: BrowserLlmPayload, previous?: GeneratedItinerary): GeneratedItinerary {
  const days: ItineraryDay[] = payload.days.map((day, dayIndex) => ({
    day_index: dayIndex + 1,
    title: day.title,
    summary: day.summary,
    total_cost: Number(day.total_cost ?? 0),
    items: day.items.map((item, itemIndex): ItineraryItem => ({
      ...mergePreviousOptionalFields(previous?.days?.[dayIndex]?.items?.[itemIndex], item),
      id: resolveItemId(previous?.days?.[dayIndex]?.items?.[itemIndex], item, dayIndex, itemIndex),
      type: item.type,
      name: item.name,
      start_time: item.start_time,
      end_time: item.end_time,
      location: item.location,
      score: clampScore(item.score),
      note: item.note?.trim() || "Generated via the backend relay.",
      booking_info: normalizeBookingInfo(item.booking_info, previous?.days?.[dayIndex]?.items?.[itemIndex]?.booking_info),
      visit_requirements: normalizeVisitRequirements(item.visit_requirements, previous?.days?.[dayIndex]?.items?.[itemIndex]?.visit_requirements)
    }))
  }))

  return {
    summary: payload.summary,
    total_budget_estimate: Number(payload.total_budget_estimate ?? 0),
    days,
    risks: Array.isArray(payload.risks) ? payload.risks.filter((item): item is string => typeof item === "string") : [],
    transport_booking_summary: normalizeTransportBookingSummary(payload.transport_booking_summary, previous?.transport_booking_summary)
  }
}

function mergePreviousOptionalFields(previous: ItineraryItem | undefined, next: BrowserLlmDay["items"][number]): Partial<ItineraryItem> {
  if (!previous || !shouldReusePreviousItem(previous, next)) {
    return {}
  }
  return {
    image_urls: previous.image_urls,
    image_source_urls: previous.image_source_urls,
    image_status: previous.image_status,
    image_priority_tier: previous.image_priority_tier,
    image_priority_reason: previous.image_priority_reason,
    image_failure_reason: previous.image_failure_reason
  }
}

function resolveItemId(previous: ItineraryItem | undefined, next: BrowserLlmDay["items"][number], dayIndex: number, itemIndex: number): string {
  if (previous && shouldReusePreviousItem(previous, next)) {
    return previous.id
  }
  return createLocalId("item", dayIndex, itemIndex)
}

function shouldReusePreviousItem(previous: ItineraryItem, next: BrowserLlmDay["items"][number]): boolean {
  const previousName = normalizeText(previous.name)
  const nextName = normalizeText(next.name)
  if (previousName && nextName && previousName === nextName) {
    return true
  }
  return (
    normalizeText(previous.type) === normalizeText(next.type) &&
    normalizeText(previous.start_time) === normalizeText(next.start_time) &&
    normalizeText(previous.end_time) === normalizeText(next.end_time)
  )
}

function normalizeBookingInfo(payload?: BrowserLlmBookingInfo | null, previous?: BookingInfo | null): BookingInfo | null {
  if (!payload && !previous) {
    return null
  }
  const normalized: BookingInfo = {
    price_label: normalizeOptionalText(payload?.price_label ?? previous?.price_label),
    estimated_price: normalizeOptionalNumber(payload?.estimated_price, previous?.estimated_price),
    booking_required: normalizeOptionalBoolean(payload?.booking_required, previous?.booking_required ?? false),
    reservation_required: normalizeOptionalBoolean(payload?.reservation_required, previous?.reservation_required ?? false),
    official_booking_url: normalizeOptionalUrl(payload?.official_booking_url ?? previous?.official_booking_url),
    booking_window: normalizeOptionalText(payload?.booking_window ?? previous?.booking_window),
    reminder: normalizeOptionalText(payload?.reminder ?? previous?.reminder),
    notes: normalizeStringArray(payload?.notes, previous?.notes),
    source_urls: normalizeUrlArray(payload?.source_urls, previous?.source_urls)
  }
  return hasBookingInfoContent(normalized) ? normalized : null
}

function normalizeVisitRequirements(payload?: BrowserLlmVisitRequirements | null, previous?: VisitRequirements | null): VisitRequirements | null {
  if (!payload && !previous) {
    return null
  }
  const normalized: VisitRequirements = {
    reservation_policy: normalizeOptionalText(payload?.reservation_policy ?? previous?.reservation_policy),
    timed_entry: normalizeOptionalBoolean(payload?.timed_entry, previous?.timed_entry ?? false),
    identity_required: normalizeOptionalBoolean(payload?.identity_required, previous?.identity_required ?? false),
    advance_booking_note: normalizeOptionalText(payload?.advance_booking_note ?? previous?.advance_booking_note),
    notes: normalizeStringArray(payload?.notes, previous?.notes)
  }
  return hasVisitRequirementsContent(normalized) ? normalized : null
}

function normalizeTransportBookingSummary(
  payload?: BrowserLlmTransportBookingSummary | null,
  previous?: TransportBookingSummary | null
): TransportBookingSummary | null {
  if (!payload && !previous) {
    return null
  }
  const normalized: TransportBookingSummary = {
    summary: normalizeOptionalText(payload?.summary ?? previous?.summary),
    recommended_option: normalizeOptionalText(payload?.recommended_option ?? previous?.recommended_option),
    estimated_intercity_cost: normalizeOptionalNumber(payload?.estimated_intercity_cost, previous?.estimated_intercity_cost) ?? 0,
    estimated_local_transport_cost: normalizeOptionalNumber(payload?.estimated_local_transport_cost, previous?.estimated_local_transport_cost) ?? 0,
    booking_required: normalizeOptionalBoolean(payload?.booking_required, previous?.booking_required ?? false),
    official_booking_url: normalizeOptionalUrl(payload?.official_booking_url ?? previous?.official_booking_url),
    booking_window: normalizeOptionalText(payload?.booking_window ?? previous?.booking_window),
    pass_or_ticket_notes: normalizeStringArray(payload?.pass_or_ticket_notes, previous?.pass_or_ticket_notes),
    reminders: normalizeStringArray(payload?.reminders, previous?.reminders),
    notes: normalizeStringArray(payload?.notes, previous?.notes),
    source_urls: normalizeUrlArray(payload?.source_urls, previous?.source_urls)
  }
  return hasTransportBookingSummaryContent(normalized) ? normalized : null
}

function hasBookingInfoContent(value: BookingInfo): boolean {
  return Boolean(
    value.price_label ||
      typeof value.estimated_price === "number" ||
      value.booking_required ||
      value.reservation_required ||
      value.official_booking_url ||
      value.booking_window ||
      value.reminder ||
      value.notes?.length ||
      value.source_urls?.length
  )
}

function hasVisitRequirementsContent(value: VisitRequirements): boolean {
  return Boolean(
    value.reservation_policy ||
      value.timed_entry ||
      value.identity_required ||
      value.advance_booking_note ||
      value.notes?.length
  )
}

function hasTransportBookingSummaryContent(value: TransportBookingSummary): boolean {
  return Boolean(
    value.summary ||
      value.recommended_option ||
      value.estimated_intercity_cost > 0 ||
      value.estimated_local_transport_cost > 0 ||
      value.booking_required ||
      value.official_booking_url ||
      value.booking_window ||
      value.pass_or_ticket_notes?.length ||
      value.reminders?.length ||
      value.notes?.length ||
      value.source_urls?.length
  )
}

function normalizeOptionalNumber(primary: number | null | undefined, fallback?: number | null): number | null {
  const candidate = typeof primary === "number" && Number.isFinite(primary) ? primary : fallback
  return typeof candidate === "number" && Number.isFinite(candidate) ? candidate : null
}

function normalizeOptionalBoolean(primary: boolean | null | undefined, fallback = false): boolean {
  return typeof primary === "boolean" ? primary : fallback
}

function normalizeOptionalText(value: string | null | undefined): string | null {
  const normalized = typeof value === "string" ? value.trim() : ""
  return normalized.length > 0 ? normalized : null
}

function normalizeOptionalUrl(value: string | null | undefined): string | null {
  const normalized = normalizeOptionalText(value)
  return normalized && /^https?:\/\//i.test(normalized) ? normalized : null
}

function normalizeStringArray(primary?: string[] | null, fallback?: string[] | null): string[] {
  const source = Array.isArray(primary) && primary.length > 0 ? primary : fallback
  if (!Array.isArray(source)) {
    return []
  }
  return source
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter((item, index, values) => item.length > 0 && values.indexOf(item) === index)
}

function normalizeUrlArray(primary?: string[] | null, fallback?: string[] | null): string[] {
  return normalizeStringArray(primary, fallback).filter((item) => /^https?:\/\//i.test(item))
}

function normalizeText(value: string | null | undefined): string {
  return typeof value === "string" ? value.trim().toLowerCase() : ""
}

function createTrace(config: RuntimeLlmConfig, note: string, groundedDocs: SearchDocument[]): AgentRunTrace {
  return {
    provider: `${config.provider_protocol}-relay`,
    workflow_id: createWorkflowId(),
    notes: [
      `Browser routed ${config.provider_protocol}/${config.wire_api} through /api/v1/llm/proxy for ${config.base_url}.`,
      `Model: ${config.model}.`,
      note
    ],
    grounding_documents: groundedDocs
  }
}

function createWorkflowId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `browser_${crypto.randomUUID()}`
  }
  return `browser_${Date.now()}`
}

function createLocalId(prefix: string, dayIndex: number, itemIndex: number): string {
  return `${prefix}_${dayIndex + 1}_${itemIndex + 1}_${Date.now()}`
}

function clampScore(value: number | undefined): number {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return 0.8
  }
  return Math.max(0, Math.min(1, value))
}
