export type JobStatus = "queued" | "running" | "retrying" | "completed" | "failed" | "cancelled"
export type LlmWireApi = "chat_completions" | "responses"
export type LlmProviderProtocol = "openai" | "newapi" | "gemini" | "claude" | "neiapi"
export type LlmAgentProvider = "standard" | "langgraph"
export type SearchServiceProvider = "groksearch" | "tavily"
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
  is_admin: boolean
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
  incomplete?: boolean
  unpriced_items?: string[]
  transport_budget_ratio?: number | null
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
  price_status?: "unknown" | "estimated" | "verified" | "free"
  transport_scope?: "outbound" | "return" | "intercity" | "local" | null
  duration_minutes_min?: number | null
  passenger_count?: number | null
  unit_price?: number | null
  check_in_date?: string | null
  check_out_date?: string | null
  room_count?: number | null
  nights?: number | null
  early_check_in_confirmed?: boolean
  price_label?: string | null
  estimated_price?: number | null
  booking_required?: boolean
  reservation_required?: boolean
  official_booking_url?: string | null
  booking_window?: string | null
  reminder?: string | null
  notes?: string[]
  source_urls?: string[]
  schedule_verified?: boolean
  schedule_status?: "unknown" | "reference" | "date_specific"
  service_number?: string | null
  schedule_checked_at?: string | null
  schedule_source_url?: string | null
  evidence_status?: EvidenceStatus
  evidence_checked_at?: string | null
  evidence_reason?: string | null
}

export type EvidenceStatus = "verified" | "referenced" | "conflicted" | "unknown"

export interface VisitRequirements {
  reservation_policy?: string | null
  timed_entry?: boolean
  identity_required?: boolean
  advance_booking_note?: string | null
  notes?: string[]
}

export interface TransportLeg {
  scope: "outbound" | "return" | "intercity" | "local"
  origin: string
  destination: string
  departure_date: string
  arrival_date?: string | null
  mode: string
  passenger_count: number
  estimated_total?: number | null
  unit_price?: number | null
  duration_minutes_min?: number | null
  duration_minutes_max?: number | null
  price_status: string
  pricing_note?: string
  source_urls: string[]
}

export interface TransportServiceCandidate {
  scope: "outbound" | "return" | "intercity"
  mode: string
  service_number: string
  origin: string
  destination: string
  departure_date: string
  departure_time: string
  arrival_date?: string | null
  arrival_time: string
  duration_minutes?: number | null
  fare_class?: string | null
  fare_amount?: number | null
  price_status: "unknown" | "estimated" | "verified"
  availability_status: string
  schedule_status: "unknown" | "reference" | "date_specific"
  schedule_checked_at: string
  source_url: string
  evidence_status?: EvidenceStatus
  evidence_checked_at?: string | null
  evidence_reason?: string | null
  notes: string[]
}

export interface TransportBookingSummary {
  legs?: TransportLeg[]
  service_candidates?: TransportServiceCandidate[]
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

export interface StayHotelCandidate {
  identity_status?: string
  identity_checked_at?: string | null
  verified_source_urls?: string[]
  evidence_notes?: string[]
  name: string
  area?: string | null
  hotel_type?: string | null
  reason?: string | null
  price_hint?: string | null
  price_checked_at?: string | null
  price_valid_for?: string | null
  review_score?: string | null
  review_count?: string | null
  review_summary?: string | null
  preference_match?: string | null
  booking_confidence?: string | null
  caveats?: string[]
  source_urls?: string[]
}

export interface StayRecommendation {
  recommended_areas: string[]
  final_recommended_hotel?: StayHotelCandidate | null
  hotel_candidates: StayHotelCandidate[]
  stay_strategy: string[]
  budget_notes: string[]
  price_timeliness_notes: string[]
  review_notes: string[]
  preference_match_notes: string[]
  hotel_risks: string[]
  source_urls: string[]
}

export interface ItineraryItem {
  id: string
  type: string
  name: string
  start_time: string
  end_day_offset?: number
  end_time: string
  location: string
  score: number
  note: string
  booking_info?: BookingInfo | null
  visit_requirements?: VisitRequirements | null
  nearby_suggestions?: Array<{
    name: string
    area: string
    reason: string
    suggested_time: string
    highlights: string[]
    source_urls: string[]
    confidence: string
    relation_type: "suggested_pair" | "same_area" | string
    relation_note: string
  }>
  image_urls?: string[]
  image_backup_urls?: string[]
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
  forecast_type?: string | null
  condition?: string | null
  temperature_min_c?: string | null
  temperature_max_c?: string | null
  precipitation_probability?: string | null
  wind?: string | null
  forecast_updated_at?: string | null
  checked_at?: string | null
  evidence_status?: EvidenceStatus
  evidence_checked_at?: string | null
  evidence_reason?: string | null
  field_evidence?: Record<string, EvidenceStatus>
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
  stay_recommendation?: StayRecommendation | null
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

export interface TripRefineMessage {
  id: string
  role: "user" | "assistant"
  text: string
  created_at: string
}

export interface TripUploadedGuideSource {
  id: string
  title: string
  content: string
  source_type: string
  original_filename?: string | null
  created_at: string
}

export interface TripCommunityGuideSource {
  id: string
  post_id: string
  title: string
  destination: string
  author_name: string
  share_note: string
  itinerary_summary: string
  snapshot: CommunityTripSnapshot
  created_at: string
}

export interface TripRefineSession {
  id: string
  trip_id: string
  messages: TripRefineMessage[]
  uploaded_guides: TripUploadedGuideSource[]
  community_sources: TripCommunityGuideSource[]
  created_at: string
  updated_at: string
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
  provider_protocol: LlmProviderProtocol
  base_url: string | null
  model: string | null
  api_key_masked: string | null
  has_api_key: boolean
  wire_api: LlmWireApi | null
  agent_provider: LlmAgentProvider
  configured: boolean
  poi_provider_protocol: LlmProviderProtocol
  poi_base_url: string | null
  poi_model: string | null
  weather_model: string | null
  hotel_model: string | null
  transport_model: string | null
  poi_api_key_masked: string | null
  poi_has_api_key: boolean
  poi_wire_api: LlmWireApi | null
  poi_configured: boolean
}

export interface AgentSettingsInput {
  provider_protocol?: LlmProviderProtocol
  base_url?: string
  model?: string
  wire_api?: LlmWireApi
  agent_provider?: LlmAgentProvider
  api_key?: string
  poi_provider_protocol?: LlmProviderProtocol
  poi_base_url?: string
  poi_model?: string
  weather_model?: string
  hotel_model?: string
  transport_model?: string
  poi_wire_api?: LlmWireApi
  poi_api_key?: string
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

export interface LlmModelInfo {
  id: string
  name?: string | null
  description?: string | null
  owned_by?: string | null
  created_at?: string | number | null
  input_token_limit?: number | null
  output_token_limit?: number | null
}

export interface LlmModelsResponse {
  provider_protocol: LlmProviderProtocol
  base_url: string
  models: LlmModelInfo[]
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
  attempt_count?: number
  max_attempts?: number
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
  can_resume?: boolean
  resume_from_job_id?: string | null
  resume_failed_role?: string | null
  resume_reason?: string | null
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

export interface AdminPage<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}

export interface AdminOwnerSummary {
  id: string
  email: string
  name: string
  is_admin: boolean
  disabled_at?: string | null
}

export interface AdminUserSummary {
  id: string
  email: string
  name: string
  avatar?: string | null
  locale: string
  created_at: string
  is_admin: boolean
  disabled_at?: string | null
  disabled_reason?: string | null
  trip_count: number
  community_post_count: number
  job_count: number
}

export interface AdminUserDetail extends AdminUserSummary {
  xhs_source_enabled: boolean
  has_llm_api_key: boolean
  has_search_api_key: boolean
  has_image_api_key: boolean
}

export interface AdminTripSummary {
  id: string
  user_id: string
  owner?: AdminOwnerSummary | null
  title: string
  origin: string
  destination: string
  start_date: string
  end_date: string
  budget: number
  travelers: number
  created_at: string
  updated_at: string
  has_itinerary: boolean
  has_community_post: boolean
}

export interface AdminTripDetail extends AdminTripSummary {
  interests: string[]
  accommodation_preference: string
  pace: string
  transport_mode: string
  itinerary?: Record<string, unknown> | null
  latest_agent_trace?: Record<string, unknown> | null
}

export interface AdminCommunityPostSummary {
  id: string
  trip_id: string
  author_user_id: string
  author?: AdminOwnerSummary | null
  title: string
  destination: string
  share_note: string
  cover_image_url?: string | null
  published_at: string
  updated_at: string
  source_trip_updated_at: string
  is_stale: boolean
}

export interface AdminCommunityPostDetail extends AdminCommunityPostSummary {
  snapshot: Record<string, unknown>
}

export interface AdminJobSummary {
  job_id: string
  owner_user_id?: string | null
  owner?: AdminOwnerSummary | null
  status: JobStatus | string
  type: string
  trip_id?: string | null
  created_at: string
  updated_at: string
  stage?: string | null
  stage_message?: string | null
  progress_percent?: number | null
  error_message?: string | null
}

export interface AdminJobDetail extends AdminJobSummary {
  timeline_json: JobTimelineEntry[]
  result?: Record<string, unknown> | null
  payload?: Record<string, unknown> | null
}
