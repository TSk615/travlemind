import { appConfig } from "@travelmind/config"
import type {
  AgentRunTrace,
  CommunityPostDetail,
  CommunityPostSummary,
  Envelope,
  ExportJob,
  GeneratedItinerary,
  ImageGenerationRecord,
  ImageGenerationStartResponse,
  ImagePromptComposeInput,
  ImagePromptComposeResult,
  LlmModelsResponse,
  LlmProviderProtocol,
  LlmSettings,
  LlmSettingsInput,
  LlmWireApi,
  PromptTrendResponse,
  SearchDocument,
  Trip,
  TripPreferenceInput,
  TripRefineInput,
  User,
  XhsAccountStatus,
  XhsBindingStatus
} from "@travelmind/shared-types"
import { notifyUnauthorizedSession } from "@/lib/authSession"

interface LoginPayload {
  email: string
  password: string
  name?: string
}

interface RequestOptions extends RequestInit {
  handleUnauthorized?: boolean
  retryUnauthorized?: boolean
}


export interface TripIntakeDraft {
  title: string
  origin: string
  destination: string
  start_date: string
  end_date: string
  budget: number
  travelers: number
  interests: string[]
  accommodation_preference: string
  pace: string
  transport_mode: string
}

export interface TripIntakeChatMessage {
  role: "assistant" | "user"
  text: string
}

export interface TripIntakeChatResponse {
  assistant_message: string
  draft: TripIntakeDraft
  missing_required_fields: string[]
  ready_to_create: boolean
}

export interface SearchPayload {
  query: string
  destination?: string
  manual_links: string[]
  interests?: string[]
}

export interface TripExportPayload {
  trip_id: string
  formats?: string[]
}

export interface JobRecord extends ExportJob {}

export interface LlmConnectionTestResponse {
  provider_protocol: LlmProviderProtocol
  base_url: string
  model: string
  wire_api: LlmWireApi
  ok: boolean
  reply: string
  latency_ms: number
}

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

export function handleUnauthorizedStatus(status: number, enabled = true): void {
  if (enabled && status === 401) {
    notifyUnauthorizedSession()
  }
}

const AUTH_REFRESH_PATH = "/api/v1/auth/refresh"
let refreshSessionPromise: Promise<boolean> | null = null

async function refreshUnauthorizedSession(): Promise<boolean> {
  if (refreshSessionPromise) {
    return refreshSessionPromise
  }

  refreshSessionPromise = (async () => {
    try {
      const response = await fetch(`${appConfig.apiBaseUrl}${AUTH_REFRESH_PATH}`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json"
        }
      })
      return response.ok
    } catch {
      return false
    } finally {
      refreshSessionPromise = null
    }
  })()

  return refreshSessionPromise
}

export async function apiFetch(path: string, init?: RequestInit, options?: { retryUnauthorized?: boolean }): Promise<Response> {
  const requestInit = init ?? {}
  const retryUnauthorized = options?.retryUnauthorized ?? true
  const requestUrl = `${appConfig.apiBaseUrl}${path}`

  const send = () =>
    fetch(requestUrl, {
      credentials: "include",
      ...requestInit
    })

  let response = await send()
  if (response.status !== 401 || !retryUnauthorized || path === AUTH_REFRESH_PATH) {
    return response
  }

  const refreshed = await refreshUnauthorizedSession()
  if (!refreshed) {
    return response
  }

  response = await send()
  return response
}

async function request<T>(path: string, init?: RequestOptions): Promise<T> {
  const { handleUnauthorized = true, retryUnauthorized = true, ...requestInit } = init ?? {}
  const response = await apiFetch(
    path,
    {
      headers: {
        "Content-Type": "application/json",
        ...((requestInit.headers ?? {}) as Record<string, string>)
      },
      ...requestInit
    },
    { retryUnauthorized }
  )

  const contentType = response.headers.get("content-type") ?? ""
  const rawPayload = contentType.includes("application/json") ? await response.json() : null
  const envelope = rawPayload as Envelope<T> | null

  if (!response.ok || envelope?.error) {
    handleUnauthorizedStatus(response.status, handleUnauthorized)
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

async function requestEnvelope<T>(path: string, init?: RequestOptions): Promise<Envelope<T>> {
  const { handleUnauthorized = true, retryUnauthorized = true, ...requestInit } = init ?? {}
  const response = await apiFetch(
    path,
    {
      headers: {
        "Content-Type": "application/json",
        ...((requestInit.headers ?? {}) as Record<string, string>)
      },
      ...requestInit
    },
    { retryUnauthorized }
  )

  const contentType = response.headers.get("content-type") ?? ""
  const rawPayload = contentType.includes("application/json") ? await response.json() : null
  const envelope = rawPayload as Envelope<T> | null

  if (!response.ok || envelope?.error) {
    handleUnauthorizedStatus(response.status, handleUnauthorized)
    throw new ApiError(response.status, envelope?.error, response.statusText || "Request failed")
  }

  if (!envelope) {
    throw new ApiError(response.status, null, "Invalid API response")
  }

  return envelope
}

async function requestFormData<T>(path: string, formData: FormData, init?: RequestOptions): Promise<T> {
  const { handleUnauthorized = true, retryUnauthorized = true, ...requestInit } = init ?? {}
  const response = await apiFetch(
    path,
    {
      ...requestInit,
      body: formData
    },
    { retryUnauthorized }
  )

  const contentType = response.headers.get("content-type") ?? ""
  const rawPayload = contentType.includes("application/json") ? await response.json() : null
  const envelope = rawPayload as Envelope<T> | null

  if (!response.ok || envelope?.error) {
    handleUnauthorizedStatus(response.status, handleUnauthorized)
    throw new ApiError(response.status, envelope?.error, response.statusText || "Request failed")
  }

  if (!envelope || envelope.data === null) {
    throw new ApiError(response.status, null, "Invalid API response")
  }

  return envelope.data
}

export const api = {
  register(payload: LoginPayload) {
    return request<User>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
      handleUnauthorized: false,
      retryUnauthorized: false
    })
  },
  login(payload: LoginPayload) {
    return request<User>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
      handleUnauthorized: false,
      retryUnauthorized: false
    })
  },
  logout() {
    return request<{ success: boolean }>("/api/v1/auth/logout", {
      method: "POST",
      handleUnauthorized: false,
      retryUnauthorized: false
    })
  },
  me() {
    return request<User>("/api/v1/me", { handleUnauthorized: false })
  },
  getXhsStatus() {
    return request<XhsAccountStatus>("/api/v1/account/xhs/status")
  },
  startXhsBind() {
    return request<XhsBindingStatus>("/api/v1/account/xhs/bind", {
      method: "POST"
    })
  },
  getXhsBind(bindId: string) {
    return request<XhsBindingStatus>(`/api/v1/account/xhs/bind/${bindId}`)
  },
  deleteXhsBind() {
    return request<XhsAccountStatus>("/api/v1/account/xhs/bind", {
      method: "DELETE"
    })
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
  tripIntakeChat(payload: { draft: TripIntakeDraft; messages: TripIntakeChatMessage[]; user_message?: string | null }) {
    return request<TripIntakeChatResponse>("/api/v1/trips/intake/chat", {
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
  deleteTrip(id: string) {
    return request<{ success: boolean; trip_id: string }>(`/api/v1/trips/${id}`, {
      method: "DELETE"
    })
  },
  saveTripItinerary(id: string, payload: { itinerary: GeneratedItinerary; latest_agent_trace?: AgentRunTrace | null }) {
    return request<Trip>(`/api/v1/trips/${id}/itinerary`, {
      method: "PUT",
      body: JSON.stringify(payload)
    })
  },
  listCommunityPosts() {
    return request<CommunityPostSummary[]>("/api/v1/community/posts")
  },
  getCommunityPost(id: string) {
    return request<CommunityPostDetail>(`/api/v1/community/posts/${id}`)
  },
  createCommunityPost(payload: { trip_id: string; share_note: string }) {
    return request<CommunityPostDetail>("/api/v1/community/posts", {
      method: "POST",
      body: JSON.stringify(payload)
    })
  },
  updateCommunityPost(id: string, payload: { share_note: string }) {
    return request<CommunityPostDetail>(`/api/v1/community/posts/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    })
  },
  refreshCommunityPost(id: string, payload?: { share_note?: string | null }) {
    return request<CommunityPostDetail>(`/api/v1/community/posts/${id}/refresh-from-trip`, {
      method: "POST",
      body: JSON.stringify(payload ?? {})
    })
  },
  deleteCommunityPost(id: string) {
    return request<{ success: boolean; post_id: string }>(`/api/v1/community/posts/${id}`, {
      method: "DELETE"
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
  enrichTripImages(id: string) {
    return request<JobRecord>(`/api/v1/trips/${id}/images/enrich`, {
      method: "POST"
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
  listLlmModels(payload: { provider_protocol?: string; base_url?: string; api_key?: string; timeout_seconds?: number }) {
    return request<LlmModelsResponse>("/api/v1/llm/models", {
      method: "POST",
      body: JSON.stringify(payload)
    })
  },
  testLlmConnection(payload: { provider_protocol?: string; base_url?: string; api_key?: string; model?: string; wire_api?: string; timeout_seconds?: number }) {
    return request<LlmConnectionTestResponse>("/api/v1/llm/test", {
      method: "POST",
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
  exportTrip(payload: TripExportPayload) {
    return request<JobRecord>("/api/v1/exports", {
      method: "POST",
      body: JSON.stringify(payload)
    })
  },
  getJob(id: string) {
    return request<JobRecord>(`/api/v1/jobs/${id}`)
  },
  composeImagePrompt(payload: ImagePromptComposeInput) {
    return request<ImagePromptComposeResult>("/api/v1/images/prompts/compose", {
      method: "POST",
      body: JSON.stringify(payload)
    })
  },
  generateImage(formData: FormData) {
    return requestFormData<ImageGenerationStartResponse>("/api/v1/images/generate", formData, {
      method: "POST"
    })
  },
  listImages(params?: { mode?: string; status?: string; visibility?: string }) {
    const query = new URLSearchParams()
    if (params?.mode) {
      query.set("mode", params.mode)
    }
    if (params?.status) {
      query.set("status", params.status)
    }
    if (params?.visibility) {
      query.set("visibility", params.visibility)
    }
    const suffix = query.toString() ? `?${query.toString()}` : ""
    return request<ImageGenerationRecord[]>(`/api/v1/images${suffix}`)
  },
  listImageFeed(limit = 24) {
    return request<ImageGenerationRecord[]>(`/api/v1/images/feed?limit=${limit}`)
  },
  getImage(id: string) {
    return request<ImageGenerationRecord>(`/api/v1/images/${id}`)
  },
  updateImage(id: string, payload: { title?: string; destination?: string; style_tags?: string[]; visibility?: string }) {
    return request<ImageGenerationRecord>(`/api/v1/images/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    })
  },
  remixImage(id: string) {
    return request<ImageGenerationRecord>(`/api/v1/images/${id}/remix`, {
      method: "POST"
    })
  },
  getPromptTrends(platform: "douyin" | "xiaohongshu", destination?: string, limit = 12) {
    const query = new URLSearchParams({ platform, limit: String(limit) })
    if (destination?.trim()) {
      query.set("destination", destination.trim())
    }
    return requestEnvelope<[] | PromptTrendResponse["items"]>(`/api/v1/images/prompt-trends?${query.toString()}`).then((envelope) => ({
      items: Array.isArray(envelope.data) ? envelope.data : [],
      implemented: Boolean(envelope.meta.implemented),
      source: String(envelope.meta.source ?? "reserved"),
      platform
    }))
  }
}
