import { appConfig } from "@travelmind/config"
import type {
  AgentRunTrace,
  Envelope,
  ExportJob,
  GeneratedItinerary,
  LlmSettings,
  LlmSettingsInput,
  SearchDocument,
  Trip,
  TripPreferenceInput,
  TripRefineInput,
  User
} from "@travelmind/shared-types"

interface LoginPayload {
  email: string
  password: string
  name?: string
}

export interface SearchPayload {
  query: string
  destination?: string
  manual_links: string[]
}

export interface JobRecord extends ExportJob {}

interface EnvelopeError {
  code: string
  message: string
  details?: Record<string, unknown> | null
}

export class ApiError extends Error {
  code: string
  status: number
  details: Record<string, unknown> | null

  constructor(status: number, payload?: EnvelopeError | null, fallbackMessage = "Request failed") {
    super(payload?.message ?? fallbackMessage)
    this.name = "ApiError"
    this.code = payload?.code ?? "request_failed"
    this.status = status
    this.details = payload?.details ?? null
  }
}

export function getErrorMessage(error: unknown, fallbackMessage: string): string {
  return error instanceof Error && error.message ? error.message : fallbackMessage
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${appConfig.apiBaseUrl}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...((init?.headers ?? {}) as Record<string, string>)
    },
    ...init
  })

  const contentType = response.headers.get("content-type") ?? ""
  const rawPayload = contentType.includes("application/json") ? await response.json() : null
  const envelope = rawPayload as Envelope<T> | null

  if (!response.ok || envelope?.error) {
    throw new ApiError(response.status, envelope?.error, response.statusText || "Request failed")
  }

  if (!envelope) {
    throw new ApiError(response.status, null, "Invalid API response")
  }

  if (envelope.data === null) {
    throw new ApiError(response.status, null, "Empty response")
  }

  return envelope.data
}

export const api = {
  register(payload: LoginPayload) {
    return request<User>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify(payload)
    })
  },
  login(payload: LoginPayload) {
    return request<User>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(payload)
    })
  },
  logout() {
    return request<{ success: boolean }>("/api/v1/auth/logout", {
      method: "POST"
    })
  },
  me() {
    return request<User>("/api/v1/me")
  },
  listTrips() {
    return request<Trip[]>("/api/v1/trips")
  },
  getTrip(id: string) {
    return request<Trip>(`/api/v1/trips/${id}`)
  },
  createTrip(payload: TripPreferenceInput) {
    return request<Trip>("/api/v1/trips", {
      method: "POST",
      body: JSON.stringify(payload)
    })
  },
  updateTrip(id: string, payload: Partial<TripPreferenceInput>) {
    return request<Trip>(`/api/v1/trips/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    })
  },
  saveTripItinerary(id: string, payload: { itinerary: GeneratedItinerary; latest_agent_trace: AgentRunTrace }) {
    return request<Trip>(`/api/v1/trips/${id}/itinerary`, {
      method: "PUT",
      body: JSON.stringify(payload)
    })
  },
  generateTrip(id: string) {
    return request<JobRecord>(`/api/v1/trips/${id}/generate`, {
      method: "POST"
    })
  },
  refineTrip(id: string, payload: TripRefineInput) {
    return request<JobRecord>(`/api/v1/trips/${id}/refine`, {
      method: "POST",
      body: JSON.stringify(payload)
    })
  },
  getLlmSettings() {
    return request<LlmSettings>("/api/v1/settings/llm")
  },
  updateLlmSettings(payload: LlmSettingsInput) {
    return request<LlmSettings>("/api/v1/settings/llm", {
      method: "PUT",
      body: JSON.stringify(payload)
    })
  },
  search(payload: SearchPayload) {
    return request<SearchDocument[]>("/api/v1/search", {
      method: "POST",
      body: JSON.stringify(payload)
    })
  },
  exportPdf(trip_id: string) {
    return request<JobRecord>("/api/v1/exports/pdf", {
      method: "POST",
      body: JSON.stringify({ trip_id })
    })
  },
  getJob(id: string) {
    return request<JobRecord>(`/api/v1/jobs/${id}`)
  }
}