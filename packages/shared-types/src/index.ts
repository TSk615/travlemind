export type JobStatus = "queued" | "running" | "completed" | "failed"
export type LlmWireApi = "chat_completions" | "responses"
export type LlmAgentProvider = "standard" | "helloagents"
export type SearchServiceProvider = "exa" | "groksearch" | "tavily"
export type SearchServiceTransport = "mcp" | "api"
export type ImageProvider = "openai_compatible" | "huggingface" | "gitee_ai" | "modelscope" | "a4f"
export type ImageGenerationMode = "text_to_image" | "image_to_image"
export type ImageVisibility = "private" | "public"
export type ImageGenerationStatus = "draft" | "queued" | "running" | "completed" | "failed"
export type PromptTrendPlatform = "douyin" | "xiaohongshu"
export type BudgetCategory = "tickets" | "dining" | "accommodation" | "transport" | "other"
export type BudgetStatus = "under" | "near" | "over"

export interface Envelope<T> {
  data: T | null
  error: {
    code: string
    message: string
    details?: Record<string, unknown> | null
  } | null
  meta: Record<string, unknown>
}

export interface User {
  id: string
  email: string
  name: string
  avatar?: string | null
  locale: string
  created_at: string
}

export interface XhsBindingStatus {
  bind_id: string
  status: string
  verification_url?: string | null
  verification_code?: string | null
  qr_image_data_url?: string | null
  expires_at?: string | null
  completed_at?: string | null
  message?: string | null
}

export interface XhsAccountStatus {
  xhs_bound: boolean
  xhs_binding_required: boolean
  xhs_session_expired: boolean
  xhs_message?: string | null
  xhs_display_name?: string | null
  xhs_last_bound_at?: string | null
  xhs_last_available_at?: string | null
  active_binding?: XhsBindingStatus | null
}

export interface BudgetBreakdown {
  tickets: number
  dining: number
  accommodation: number
  transport: number
  other: number
  total: number
}

export interface BudgetLineItem {
  key: string
  title: string
  category: BudgetCategory
  amount: number
  day_index?: number | null
  note?: string | null
}

export interface BudgetSummary {
  requested_budget: number
  estimated_total: number
  remaining_budget: number
  over_budget: number
  utilization_ratio: number
  status: BudgetStatus
  breakdown: BudgetBreakdown
  line_items: BudgetLineItem[]
}

export interface BookingInfo {
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

export interface VisitRequirements {
  reservation_policy?: string | null
  timed_entry?: boolean
  identity_required?: boolean
  advance_booking_note?: string | null
  notes?: string[]
}

export interface TransportBookingSummary {
  summary?: string | null
  recommended_option?: string | null
  estimated_intercity_cost: number
  estimated_local_transport_cost: number
  booking_required?: boolean
  official_booking_url?: string | null
  booking_window?: string | null
  pass_or_ticket_notes?: string[]
  reminders?: string[]
  notes?: string[]
  source_urls?: string[]
}

export interface ItineraryItem {
  id: string
  type: string
  name: string
  start_time: string
  end_time: string
  location: string
  score: number
  note: string
  booking_info?: BookingInfo | null
  visit_requirements?: VisitRequirements | null
  image_urls?: string[]
  image_source_urls?: string[]
  image_status?: "pending" | "completed" | "failed" | "skipped" | null
  image_priority_tier?: "high" | "medium" | "low" | "skipped" | null
  image_priority_reason?: string | null
  image_failure_reason?: string | null
}

export interface ItineraryDayWeather {
  summary: string
  notes: string[]
  citations: string[]
}

export interface ItineraryDay {
  day_index: number
  title: string
  summary: string
  total_cost: number
  items: ItineraryItem[]
  weather?: ItineraryDayWeather | null
  budget_breakdown?: BudgetBreakdown | null
}

export interface AgentRunStep {
  key: string
  title: string
  description: string
  prompt_focus?: string | null
  output_summary?: string | null
  prompt_version?: string | null
  status: string
  model?: string | null
  notes: string[]
  citations?: string[]
}

export interface AgentRunTrace {
  provider: string
  workflow_id: string
  notes: string[]
  license_notice?: string | null
  agent_runs?: AgentRunStep[]
  grounding_documents?: SearchDocument[]
  transport_guidance?: Record<string, unknown> | null
}

export interface GeneratedItinerary {
  summary: string
  total_budget_estimate: number
  days: ItineraryDay[]
  risks: string[]
  budget_summary?: BudgetSummary | null
  transport_booking_summary?: TransportBookingSummary | null
}

export interface TripPreferenceInput {
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

export interface TripRefineInput {
  instruction: string
  scope: string
  day_index?: number | null
}

export interface CommunityTripPublicationState {
  post_id: string
  published_at: string
  updated_at: string
  source_trip_updated_at: string
  is_stale: boolean
}

export interface Trip extends TripPreferenceInput {
  id: string
  user_id: string
  created_at: string
  updated_at: string
  itinerary?: GeneratedItinerary | null
  latest_agent_trace?: AgentRunTrace | null
  community_post?: CommunityTripPublicationState | null
}

export interface CommunityTripSnapshot extends TripPreferenceInput {
  itinerary: GeneratedItinerary
  latest_agent_trace?: AgentRunTrace | null
}

export interface CommunityPostSummary {
  id: string
  title: string
  destination: string
  share_note: string
  cover_image_url?: string | null
  author_name: string
  published_at: string
  updated_at: string
  start_date: string
  end_date: string
  budget: number
  travelers: number
  interests: string[]
  itinerary_summary: string
  day_count: number
}

export interface CommunityPostDetail {
  id: string
  title: string
  destination: string
  share_note: string
  cover_image_url?: string | null
  author_name: string
  published_at: string
  updated_at: string
  snapshot: CommunityTripSnapshot
}

export interface ScoreBreakdown {
  trust_score: number
  quality_score: number
  freshness_score: number
  ad_score: number
  final_score: number
  reasons: string[]
}

export interface AgentSettings {
  base_url: string | null
  model: string | null
  api_key_masked: string | null
  has_api_key: boolean
  wire_api: LlmWireApi | null
  agent_provider: LlmAgentProvider
  configured: boolean
}

export interface AgentSettingsInput {
  base_url?: string
  model?: string
  wire_api?: LlmWireApi
  agent_provider?: LlmAgentProvider
  api_key?: string
}

export interface SearchSettings {
  provider: SearchServiceProvider
  transport: SearchServiceTransport
  base_url: string | null
  api_key_masked: string | null
  has_api_key: boolean
  timeout_seconds: number
  xhs_source_enabled: boolean
  configured: boolean
}

export interface SearchSettingsInput {
  provider?: SearchServiceProvider
  transport?: SearchServiceTransport
  base_url?: string
  timeout_seconds?: number
  xhs_source_enabled?: boolean
  api_key?: string
}

export interface ImageSettings {
  base_url: string | null
  api_key_masked: string | null
  has_api_key: boolean
  model: string | null
  provider: ImageProvider
  configured: boolean
}

export interface ImageSettingsInput {
  base_url?: string
  model?: string
  provider?: ImageProvider
  api_key?: string
}

export interface RuntimeSettings {
  agent: AgentSettings
  search: SearchSettings
  image: ImageSettings
}

export interface RuntimeSettingsInput {
  agent?: AgentSettingsInput
  search?: SearchSettingsInput
  image?: ImageSettingsInput
}

export type LlmSettings = RuntimeSettings
export type LlmSettingsInput = RuntimeSettingsInput

export interface SearchGeoPoint {
  lat: number
  lng: number
}

export interface SearchDocument {
  id: string
  platform: string
  title: string
  url: string
  summary: string
  destination?: string | null
  place_name?: string | null
  category?: string | null
  opening_hours?: string | null
  price_hint?: string | null
  address?: string | null
  geo?: SearchGeoPoint | null
  author?: string | null
  published_at?: string | null
  engagement_hint?: string | null
  source_tags?: string[]
  image_urls?: string[]
  source_type: string
  scores: ScoreBreakdown
}

export interface JobTimelineEntry {
  recorded_at: string
  status: JobStatus
  stage?: string | null
  stage_message?: string | null
  progress_percent?: number | null
}

export interface ExportArtifact {
  type: string
  file_name: string
  file_url: string
  file_path?: string | null
  content_type?: string | null
  size_bytes?: number | null
}

export interface ExportArtifactManifest {
  manifest_version: number
  artifact_count?: number | null
  primary_artifact?: string | null
  artifacts: ExportArtifact[]
  file_name?: string | null
  file_url?: string | null
  file_path?: string | null
  content_type?: string | null
  size_bytes?: number | null
}

export interface ExportJob {
  job_id: string
  status: JobStatus
  type: string
  trip_id?: string | null
  created_at: string
  updated_at: string
  stage?: string | null
  stage_message?: string | null
  progress_percent?: number | null
  timeline_json: JobTimelineEntry[]
  result?: Record<string, unknown> | null
  error_message?: string | null
}

export interface ImageAsset {
  id: string
  url: string
  path?: string | null
  filename?: string | null
  mime_type?: string | null
}

export interface ImageGenerationRecord {
  id: string
  user_id: string
  title: string
  destination: string
  scene_prompt: string
  mode: ImageGenerationMode
  status: ImageGenerationStatus
  visibility: ImageVisibility
  prompt: string
  optimized_prompt?: string | null
  negative_prompt?: string | null
  style_tags: string[]
  source_images: ImageAsset[]
  reference_images: ImageAsset[]
  result_images: ImageAsset[]
  provider?: string | null
  model?: string | null
  remix_from_id?: string | null
  remix_count: number
  published_at?: string | null
  author_name?: string | null
  created_at: string
  updated_at: string
}

export interface ImagePromptComposeInput {
  title: string
  destination: string
  scene_prompt: string
  prompt: string
  negative_prompt: string
  style_tags: string[]
  reference_urls: string[]
  reference_count: number
}

export interface ImagePromptComposeResult {
  title: string
  optimized_prompt: string
  negative_prompt: string
}

export interface ImageGenerationStartResponse {
  generation: ImageGenerationRecord
  job: ExportJob
}

export interface PromptTrendItem {
  platform: PromptTrendPlatform
  title: string
  prompt: string
  tags: string[]
  source_url?: string | null
}

export interface PromptTrendResponse {
  items: PromptTrendItem[]
  implemented: boolean
  source: string
  platform: PromptTrendPlatform
}
