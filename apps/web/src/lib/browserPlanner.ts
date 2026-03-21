import type {
  AgentRunTrace,
  GeneratedItinerary,
  ItineraryDay,
  ItineraryItem,
  SearchDocument,
  Trip,
  TripRefineInput
} from "@travelmind/shared-types"
import { ApiError } from "@/lib/api"
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
  }>
}

interface BrowserLlmPayload {
  summary: string
  total_budget_estimate?: number
  risks?: string[]
  days: BrowserLlmDay[]
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
    itinerary: toGeneratedItinerary(payload),
    trace: createTrace(config, "Generated the itinerary via the backend relay."),
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
    itinerary: toGeneratedItinerary(payload),
    trace: createTrace(config, `Applied refine via backend relay with scope ${refineInput.scope}.`),
    rawText
  }
}

async function callModel(config: RuntimeLlmConfig, messages: Array<{ role: string; content: string }>): Promise<string> {
  const payload =
    config.wire_api === "responses"
      ? {
          model: config.model,
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
      : {
          model: config.model,
          messages
        }

  const response = await fetch("/api/v1/llm/proxy", {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      base_url: config.base_url,
      api_key: config.api_key,
      wire_api: config.wire_api,
      payload
    })
  })

  const contentType = response.headers.get("content-type") ?? ""
  const isEventStream = contentType.includes("text/event-stream")
  const rawBody = await response.text()

  if (!response.ok) {
    throw new ApiError(response.status, null, extractErrorMessage(rawBody, response.status))
  }

  if (config.wire_api === "responses") {
    return isEventStream ? extractResponsesTextFromSse(rawBody) : extractResponsesTextFromJson(rawBody)
  }

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
    output?: Array<{ content?: Array<{ text?: string }> }>
  }

  if (typeof body.output_text === "string" && body.output_text.trim()) {
    return body.output_text
  }

  const textBlocks = body.output?.flatMap((entry) => entry.content ?? []).map((item) => item.text).filter((value): value is string => typeof value === "string" && value.trim().length > 0)
  if (textBlocks && textBlocks.length > 0) {
    return textBlocks.join("\n")
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
      place_name: doc.place_name,
      category: doc.category,
      opening_hours: doc.opening_hours,
      address: doc.address,
      source_type: doc.source_type,
      url: doc.url
    })),
    refine_instruction: refineInput ?? null,
    output_language: "zh-CN"
  }

  return [
    {
      role: "system",
      content:
        "You are TravelMind AI. Return one valid JSON object only. No markdown, no commentary. All user-visible output must be in Simplified Chinese. The object must contain summary, total_budget_estimate, risks, and days. Each day must contain title, summary, total_cost, and items. Each item must contain type, name, start_time, end_time, location, score, and note. Use HH:MM 24-hour time and scores between 0 and 1."
    },
    {
      role: "user",
      content: JSON.stringify(tripPayload)
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

function toGeneratedItinerary(payload: BrowserLlmPayload): GeneratedItinerary {
  const days: ItineraryDay[] = payload.days.map((day, dayIndex) => ({
    day_index: dayIndex + 1,
    title: day.title,
    summary: day.summary,
    total_cost: Number(day.total_cost ?? 0),
    items: day.items.map((item, itemIndex): ItineraryItem => ({
      id: createLocalId("item", dayIndex, itemIndex),
      type: item.type,
      name: item.name,
      start_time: item.start_time,
      end_time: item.end_time,
      location: item.location,
      score: clampScore(item.score),
      note: item.note?.trim() || "Generated via the backend relay."
    }))
  }))

  return {
    summary: payload.summary,
    total_budget_estimate: Number(payload.total_budget_estimate ?? 0),
    days,
    risks: Array.isArray(payload.risks) ? payload.risks.filter((item): item is string => typeof item === "string") : []
  }
}

function createTrace(config: RuntimeLlmConfig, note: string): AgentRunTrace {
  return {
    provider: "openai-compatible-relay",
    workflow_id: createWorkflowId(),
    notes: [
      `Browser routed ${config.wire_api} through /api/v1/llm/proxy for ${config.base_url}.`,
      `Model: ${config.model}.`,
      note
    ]
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
