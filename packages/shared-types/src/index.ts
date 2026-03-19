export type JobStatus = "queued" | "running" | "completed" | "failed"

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

export interface ItineraryItem {
  id: string
  type: string
  name: string
  start_time: string
  end_time: string
  location: string
  score: number
  note: string
}

export interface ItineraryDay {
  day_index: number
  title: string
  summary: string
  total_cost: number
  items: ItineraryItem[]
}

export interface AgentRunTrace {
  provider: string
  workflow_id: string
  notes: string[]
  license_notice?: string | null
}

export interface GeneratedItinerary {
  summary: string
  total_budget_estimate: number
  days: ItineraryDay[]
  risks: string[]
}

export interface TripPreferenceInput {
  title: string
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

export interface Trip extends TripPreferenceInput {
  id: string
  user_id: string
  created_at: string
  updated_at: string
  itinerary?: GeneratedItinerary | null
  latest_agent_trace?: AgentRunTrace | null
}

export interface ScoreBreakdown {
  trust_score: number
  quality_score: number
  freshness_score: number
  ad_score: number
  final_score: number
  reasons: string[]
}

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
