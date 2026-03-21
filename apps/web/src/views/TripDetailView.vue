<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { useRoute } from "vue-router"
import type { JobTimelineEntry, SearchDocument, Trip, TripRefineInput } from "@travelmind/shared-types"
import LlmStatusNotice from "@/components/LlmStatusNotice.vue"
import StatePanel from "@/components/StatePanel.vue"
import StatusPill from "@/components/StatusPill.vue"
import { api, getErrorMessage, type JobRecord } from "@/lib/api"
import { generateTripInBrowser, refineTripInBrowser } from "@/lib/browserPlanner"
import { formatCurrency, formatDateRange, formatDateTime } from "@/lib/format"
import { useI18n } from "@/lib/useI18n"
import { useLlmSettingsStore } from "@/stores/llmSettings"

const route = useRoute()
const settingsStore = useLlmSettingsStore()
void settingsStore.bootstrap()

const trip = ref<Trip | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const activeJob = ref<JobRecord | null>(null)
const generatePending = ref(false)
const generateError = ref<string | null>(null)
const exportPending = ref(false)
const exportError = ref<string | null>(null)
const refinePending = ref(false)
const refineError = ref<string | null>(null)
const searchPending = ref(false)
const searchError = ref<string | null>(null)
const searchResults = ref<SearchDocument[]>([])
const hasSearched = ref(false)
const searchQuery = ref("best quiet morning spots")
const manualLinks = ref("https://kyoto.travel/en")
const customRefineInstruction = ref("")
let timer: number | null = null

const { locale, t } = useI18n()
const enCopy = {
  notAvailable: "N/A",
  currentJob: "Current job",
  noActiveJob: "No active job yet.",
  noActiveJobMessage: "Generation and refinement call the third-party model directly from the browser. PDF export still uses your backend job pipeline.",
  browserGenerateMessage: "Calling the third-party model directly from this browser.",
  browserRefineMessage: "Calling the third-party model directly from this browser with the current itinerary and refine instruction.",
  browserSaved: "Saved back to backend",
  browserSavedMessage: "The generated itinerary has been persisted to your Trip record.",
  directModeTitle: "Browser-direct third-party model mode",
  directModeMessage: "Trip generation no longer depends on your backend model API. The browser now calls the third-party model endpoint directly.",
  quickRefineTitle: "Quick refine",
  quickRefineSubtitle: "Use browser-side refinement against the third-party model.",
  customRefineLabel: "Custom refine instruction",
  customRefinePlaceholder: "Example: make day 2 slower and move the photo-heavy stops earlier.",
  customRefineSubmit: "Submit refine",
  refining: "Refining...",
  refineValidation: "Enter at least 3 characters.",
  searchPanelTitle: "Search grounding",
  searchPanelMessage: "These fixed or structured search results come from your backend and are used as grounding in the prompt.",
  queryLabel: "Query",
  linksLabel: "Manual links",
  runSearch: "Run search",
  searching: "Searching...",
  searchValidation: "Enter at least 2 characters.",
  sourceOpen: "Open source",
  stageLabel: "Stage",
  progressLabel: "Progress",
  updatedLabel: "Updated",
  jobStages: {
    queued: "Queued",
    brief_parsing: "Brief parsing",
    source_search: "Fetch grounding",
    route_planning: "Call third-party model",
    export_ready: "Persist result",
    failed: "Failed"
  } as Record<string, string>,
  jobTypes: {
    "trip.generate": "Browser generation",
    "trip.refine": "Browser refine",
    "export.pdf": "PDF export"
  } as Record<string, string>,
  quickRefineActions: [
    { label: "Cut budget", instruction: "Lower the overall budget while keeping the itinerary practical.", scope: "budget" },
    { label: "Reduce transit", instruction: "Reduce long transfers and make each day easier to move through.", scope: "travel_flow" },
    { label: "Better for photos", instruction: "Prioritize more photogenic stops and better photo timing.", scope: "photo_spots" },
    { label: "Add depth", instruction: "Add more local context and deeper cultural experiences.", scope: "depth" }
  ]
}

const zhCopy = {
  notAvailable: "暂无",
  currentJob: "当前任务",
  noActiveJob: "当前还没有活动任务。",
  noActiveJobMessage: "生成和 refine 会直接由浏览器调用第三方模型。PDF 导出仍然走后端任务链路。",
  browserGenerateMessage: "正在由当前浏览器直接调用第三方模型。",
  browserRefineMessage: "正在由当前浏览器结合当前行程和 refine 指令直接调用第三方模型。",
  browserSaved: "已回写到后端",
  browserSavedMessage: "生成后的行程已经写回当前 Trip 记录。",
  directModeTitle: "浏览器直连第三方模型模式",
  directModeMessage: "Trip 生成已不再依赖后端模型 API。当前浏览器会直接调用第三方模型端点。",
  quickRefineTitle: "快速微调",
  quickRefineSubtitle: "使用浏览器侧 refine 能力，直接调整当前行程。",
  customRefineLabel: "自定义微调指令",
  customRefinePlaceholder: "例如：让第 2 天更轻松，并把更适合拍照的点位提前。",
  customRefineSubmit: "提交微调",
  refining: "微调中...",
  refineValidation: "请输入至少 3 个字符。",
  searchPanelTitle: "搜索 Grounding",
  searchPanelMessage: "这些固定或结构化搜索结果来自你的后端，并会作为 prompt 的 grounding 输入。",
  queryLabel: "查询词",
  linksLabel: "手动链接",
  runSearch: "开始检索",
  searching: "检索中...",
  searchValidation: "请输入至少 2 个字符。",
  sourceOpen: "打开来源",
  stageLabel: "阶段",
  progressLabel: "进度",
  updatedLabel: "更新时间",
  jobStages: {
    queued: "已排队",
    brief_parsing: "解析 Brief",
    source_search: "获取参考来源",
    route_planning: "调用第三方模型",
    export_ready: "回写结果",
    failed: "失败"
  } as Record<string, string>,
  jobTypes: {
    "trip.generate": "浏览器生成",
    "trip.refine": "浏览器微调",
    "export.pdf": "PDF 导出"
  } as Record<string, string>,
  quickRefineActions: [
    { label: "压预算", instruction: "在保证整体可执行的前提下降低总预算。", scope: "budget" },
    { label: "减少赶路", instruction: "减少长距离转场，让每天移动更轻松。", scope: "travel_flow" },
    { label: "更适合拍照", instruction: "优先安排更适合拍照的点位和更好的拍摄时段。", scope: "photo_spots" },
    { label: "增加深度体验", instruction: "增加更有在地感和文化深度的体验。", scope: "depth" }
  ]
}

const copy = computed(() => (locale.value === "zh-CN" ? zhCopy : enCopy))
const tripId = computed(() => String(route.params.id ?? ""))
const hasItinerary = computed(() => Boolean(trip.value?.itinerary))
const isJobRunning = computed(() => activeJob.value?.status === "queued" || activeJob.value?.status === "running")
const actionLocked = computed(() => generatePending.value || refinePending.value || exportPending.value || isJobRunning.value)
const canUseBrowserModel = computed(() => settingsStore.loaded && settingsStore.isConfigured)
const jobTimeline = computed<JobTimelineEntry[]>(() => (Array.isArray(activeJob.value?.timeline_json) ? activeJob.value.timeline_json : []))
const jobProgress = computed(() => clampProgress(activeJob.value?.progress_percent, activeJob.value?.status))

const quickRefineActions = computed(() => copy.value.quickRefineActions)

function createBrowserJob(type: JobRecord["type"], stage: string, stageMessage: string, progressPercent: number): JobRecord {
  const now = new Date().toISOString()
  return {
    job_id: `browser:${type}:${Date.now()}`,
    status: "running",
    type,
    trip_id: tripId.value,
    created_at: now,
    updated_at: now,
    stage,
    stage_message: stageMessage,
    progress_percent: progressPercent,
    timeline_json: [
      {
        recorded_at: now,
        status: "running",
        stage,
        stage_message: stageMessage,
        progress_percent: progressPercent
      }
    ],
    result: null,
    error_message: null
  }
}

function updateBrowserJob(update: {
  status?: JobRecord["status"]
  stage?: string
  stage_message?: string
  progress_percent?: number
  result?: Record<string, unknown> | null
  error_message?: string | null
}) {
  if (!activeJob.value) {
    return
  }

  const now = new Date().toISOString()
  const nextStatus = update.status ?? activeJob.value.status
  const nextStage = update.stage ?? activeJob.value.stage ?? null
  const nextStageMessage = update.stage_message ?? activeJob.value.stage_message ?? null
  const nextProgress = typeof update.progress_percent === "number" ? update.progress_percent : activeJob.value.progress_percent ?? null

  activeJob.value = {
    ...activeJob.value,
    ...update,
    status: nextStatus,
    stage: nextStage,
    stage_message: nextStageMessage,
    progress_percent: nextProgress,
    updated_at: now,
    timeline_json: [
      ...activeJob.value.timeline_json,
      {
        recorded_at: now,
        status: nextStatus,
        stage: nextStage,
        stage_message: nextStageMessage,
        progress_percent: nextProgress
      }
    ]
  }
}

function ensureBrowserLlmConfig() {
  const config = settingsStore.resolvedConfig
  if (!config || !settingsStore.isConfigured) {
    throw new Error(locale.value === "zh-CN" ? "请先配置 base URL、API Key、model 和接口格式。" : "Configure base URL, API key, model, and API format first.")
  }
  return config
}

function clampProgress(value?: number | null, status?: string): number {
  if (typeof value === "number") {
    return Math.max(0, Math.min(100, Math.round(value)))
  }
  if (status === "completed") {
    return 100
  }
  return 0
}

function formatProgress(value?: number | null, status?: string): string {
  if (typeof value === "number" || status === "queued" || status === "running" || status === "completed") {
    return `${clampProgress(value, status)}%`
  }
  return copy.value.notAvailable
}

function fieldValue(value?: string | null): string {
  const normalized = value?.trim()
  return normalized && normalized.length > 0 ? normalized : copy.value.notAvailable
}

function paceLabel(value: string): string {
  const key = `common.pace.${value}`
  const translated = t(key)
  return translated === key ? value : translated
}

function formatStage(value?: string | null): string {
  if (!value) {
    return copy.value.notAvailable
  }
  return copy.value.jobStages[value] ?? value
}

function formatJobType(value?: string | null): string {
  if (!value) {
    return copy.value.notAvailable
  }
  return copy.value.jobTypes[value] ?? value
}

async function loadTrip(initial = false) {
  if (initial) {
    loading.value = true
    error.value = null
  }

  try {
    trip.value = await api.getTrip(tripId.value)
  } catch (value) {
    error.value = getErrorMessage(value, t("tripDetail.unavailableTitle"))
  } finally {
    if (initial) {
      loading.value = false
    }
  }
}

function stopPolling() {
  if (timer !== null) {
    window.clearTimeout(timer)
    timer = null
  }
}

async function pollExportJob(jobId: string) {
  stopPolling()

  try {
    activeJob.value = await api.getJob(jobId)
    if (activeJob.value.status === "completed" || activeJob.value.status === "failed") {
      await loadTrip(false)
      return
    }
    timer = window.setTimeout(() => {
      void pollExportJob(jobId)
    }, 1500)
  } catch (value) {
    exportError.value = getErrorMessage(value, t("tripDetail.exportFailedTitle"))
  }
}

async function collectGroundingDocs(): Promise<SearchDocument[]> {
  if (!trip.value) {
    return []
  }

  const query = searchQuery.value.trim() || `${trip.value.destination} ${trip.value.interests.join(" ")}`.trim()
  if (query.length < 2) {
    return searchResults.value
  }

  try {
    searchPending.value = true
    searchError.value = null
    const docs = await api.search({
      query,
      destination: trip.value.destination,
      manual_links: manualLinks.value
        .split(/\r?\n|,/) 
        .map((value) => value.trim())
        .filter(Boolean)
    })
    searchResults.value = docs
    hasSearched.value = true
    return docs
  } catch (value) {
    searchError.value = getErrorMessage(value, t("tripDetail.searchFailedTitle"))
    return searchResults.value
  } finally {
    searchPending.value = false
  }
}

async function generate() {
  if (!trip.value) {
    return
  }

  generatePending.value = true
  generateError.value = null

  try {
    await settingsStore.fetch(true)
    const config = ensureBrowserLlmConfig()
    activeJob.value = createBrowserJob("trip.generate", "brief_parsing", copy.value.browserGenerateMessage, 12)
    const groundedDocs = await collectGroundingDocs()
    updateBrowserJob({ stage: "source_search", stage_message: copy.value.searchPanelMessage, progress_percent: 32 })
    updateBrowserJob({ stage: "route_planning", stage_message: copy.value.browserGenerateMessage, progress_percent: 76 })
    const result = await generateTripInBrowser(config, trip.value, groundedDocs)
    updateBrowserJob({ stage: "export_ready", stage_message: copy.value.browserSavedMessage, progress_percent: 92 })
    trip.value = await api.saveTripItinerary(tripId.value, {
      itinerary: result.itinerary,
      latest_agent_trace: result.trace
    })
    updateBrowserJob({ status: "completed", stage: "export_ready", stage_message: copy.value.browserSaved, progress_percent: 100, result: { summary: result.itinerary.summary } })
  } catch (value) {
    const message = getErrorMessage(value, t("tripDetail.generationFailedTitle"))
    generateError.value = message
    if (activeJob.value?.type === "trip.generate") {
      updateBrowserJob({ status: "failed", error_message: message, stage_message: message })
    }
  } finally {
    generatePending.value = false
  }
}

async function submitRefine(payload: TripRefineInput) {
  if (!trip.value || !trip.value.itinerary) {
    refineError.value = t("tripDetail.itineraryEmptyMessage")
    return
  }

  refinePending.value = true
  refineError.value = null

  try {
    await settingsStore.fetch(true)
    const config = ensureBrowserLlmConfig()
    activeJob.value = createBrowserJob("trip.refine", "brief_parsing", copy.value.browserRefineMessage, 12)
    const groundedDocs = hasSearched ? searchResults.value : await collectGroundingDocs()
    updateBrowserJob({ stage: "source_search", stage_message: copy.value.searchPanelMessage, progress_percent: 32 })
    updateBrowserJob({ stage: "route_planning", stage_message: copy.value.browserRefineMessage, progress_percent: 76 })
    const result = await refineTripInBrowser(config, trip.value, groundedDocs, payload)
    updateBrowserJob({ stage: "export_ready", stage_message: copy.value.browserSavedMessage, progress_percent: 92 })
    trip.value = await api.saveTripItinerary(tripId.value, {
      itinerary: result.itinerary,
      latest_agent_trace: result.trace
    })
    updateBrowserJob({ status: "completed", stage: "export_ready", stage_message: copy.value.browserSaved, progress_percent: 100, result: { summary: result.itinerary.summary } })
  } catch (value) {
    const message = getErrorMessage(value, t("tripDetail.asyncFailedTitle"))
    refineError.value = message
    if (activeJob.value?.type === "trip.refine") {
      updateBrowserJob({ status: "failed", error_message: message, stage_message: message })
    }
  } finally {
    refinePending.value = false
  }
}

async function submitCustomRefine() {
  const instruction = customRefineInstruction.value.trim()
  if (instruction.length < 3) {
    refineError.value = copy.value.refineValidation
    return
  }

  await submitRefine({
    instruction,
    scope: "trip_plan"
  })
}

async function runPresetRefine(action: { instruction: string; scope: string }) {
  customRefineInstruction.value = action.instruction
  await submitRefine({
    instruction: action.instruction,
    scope: action.scope
  })
}

async function exportPdf() {
  exportPending.value = true
  exportError.value = null

  try {
    const job = await api.exportPdf(tripId.value)
    activeJob.value = job
    await pollExportJob(job.job_id)
  } catch (value) {
    exportError.value = getErrorMessage(value, t("tripDetail.exportFailedTitle"))
  } finally {
    exportPending.value = false
  }
}

async function runSearch() {
  const query = searchQuery.value.trim()
  if (query.length < 2) {
    hasSearched.value = true
    searchResults.value = []
    searchError.value = copy.value.searchValidation
    return
  }

  await collectGroundingDocs()
}

watch(
  tripId,
  () => {
    stopPolling()
    activeJob.value = null
    generateError.value = null
    exportError.value = null
    refineError.value = null
    searchError.value = null
    searchResults.value = []
    hasSearched.value = false
    customRefineInstruction.value = ""
    void loadTrip(true)
  },
  { immediate: true }
)

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<template>
  <section class="page-grid">
    <StatePanel v-if="loading" kind="loading" :title="t('tripDetail.loadingTitle')" :message="t('tripDetail.loadingMessage')" />

    <StatePanel v-else-if="error" kind="error" :title="t('tripDetail.unavailableTitle')" :message="error" :action-label="t('common.retry')" @action="loadTrip(true)" />

    <template v-else-if="trip">
      <article class="panel panel-stack">
        <div class="inline-actions" style="justify-content: space-between; align-items: flex-start;">
          <div>
            <p class="kicker">{{ trip.destination }}</p>
            <h1>{{ trip.title }}</h1>
            <div class="detail-meta">
              <span>{{ formatDateRange(trip.start_date, trip.end_date) }}</span>
              <span>{{ t('common.budgetValue', { value: formatCurrency(trip.budget) }) }}</span>
              <span>{{ t('common.travelersCount', { count: trip.travelers }) }}</span>
              <span>{{ t('common.paceValue', { value: paceLabel(trip.pace) }) }}</span>
            </div>
          </div>
          <div class="stack-actions">
            <button class="primary" type="button" :disabled="actionLocked || !settingsStore.loaded" @click="generate">
              {{ generatePending ? t('common.generating') : t('common.generateItinerary') }}
            </button>
            <button type="button" :disabled="!hasItinerary || actionLocked" @click="exportPdf">
              {{ exportPending ? t('common.exporting') : t('common.exportPdf') }}
            </button>
          </div>
        </div>
      </article>

      <LlmStatusNotice compact />
      <StatePanel kind="info" :title="copy.directModeTitle" :message="copy.directModeMessage" compact />
      <StatePanel v-if="generateError" kind="error" :title="t('tripDetail.generationFailedTitle')" :message="generateError" compact />
      <StatePanel v-if="refineError" kind="error" :title="copy.quickRefineTitle" :message="refineError" compact />
      <StatePanel v-if="exportError" kind="error" :title="t('tripDetail.exportFailedTitle')" :message="exportError" compact />

      <div class="workspace-layout">
        <div class="workspace-column">
          <article class="panel panel-stack">
            <div>
              <p class="kicker">{{ copy.currentJob }}</p>
              <h2>{{ activeJob ? formatJobType(activeJob.type) : copy.noActiveJob }}</h2>
              <p class="muted">{{ activeJob ? activeJob.job_id : copy.noActiveJobMessage }}</p>
            </div>

            <StatePanel v-if="!activeJob" kind="info" :title="copy.noActiveJob" :message="copy.noActiveJobMessage" compact />

            <template v-else>
              <div class="metric-grid">
                <article class="metric-card">
                  <p class="kicker">{{ copy.stageLabel }}</p>
                  <strong>{{ formatStage(activeJob.stage) }}</strong>
                </article>
                <article class="metric-card">
                  <p class="kicker">{{ copy.progressLabel }}</p>
                  <strong>{{ formatProgress(activeJob.progress_percent, activeJob.status) }}</strong>
                </article>
                <article class="metric-card">
                  <p class="kicker">{{ copy.updatedLabel }}</p>
                  <p>{{ formatDateTime(activeJob.updated_at) }}</p>
                </article>
              </div>

              <div class="progress-track" aria-hidden="true">
                <div class="progress-fill" :style="{ width: `${jobProgress}%` }"></div>
              </div>

              <p class="muted">{{ fieldValue(activeJob.stage_message) }}</p>

              <ol v-if="jobTimeline.length" class="timeline-list">
                <li v-for="entry in jobTimeline" :key="`${entry.recorded_at}-${entry.status}-${entry.stage ?? 'none'}`" class="timeline-item">
                  <div class="timeline-meta">
                    <StatusPill :status="entry.status" />
                    <span class="muted">{{ formatStage(entry.stage) }}</span>
                    <span class="muted">{{ formatDateTime(entry.recorded_at) }}</span>
                  </div>
                  <p>{{ fieldValue(entry.stage_message) }}</p>
                </li>
              </ol>
            </template>
          </article>

          <article class="panel panel-stack">
            <div>
              <p class="kicker">{{ t('tripDetail.itineraryKicker') }}</p>
              <h2>{{ trip.itinerary?.summary ?? t('tripDetail.itineraryEmptyTitle') }}</h2>
              <p v-if="trip.itinerary" class="muted">{{ t('common.estimatedTotal', { value: formatCurrency(trip.itinerary.total_budget_estimate) }) }}</p>
            </div>

            <ul v-if="trip.itinerary?.risks?.length" class="risk-list">
              <li v-for="risk in trip.itinerary.risks" :key="risk">{{ risk }}</li>
            </ul>

            <div v-if="trip.itinerary" class="page-grid">
              <article v-for="day in trip.itinerary.days" :key="day.day_index" class="day-card">
                <h3>{{ t('common.daysLabel', { day: day.day_index, title: day.title }) }}</h3>
                <p>{{ day.summary }}</p>
                <p>{{ t('common.estimatedDailyCost', { value: formatCurrency(day.total_cost) }) }}</p>
                <ul class="detail-list">
                  <li v-for="item in day.items" :key="item.id">
                    {{ item.start_time }} - {{ item.end_time }} · {{ item.name }} · {{ item.location }}
                  </li>
                </ul>
              </article>
            </div>

            <StatePanel
              v-else
              kind="empty"
              :title="t('tripDetail.itineraryEmptyTitle')"
              :message="t('tripDetail.itineraryEmptyMessage')"
              compact
            >
              <template #actions>
                <button class="primary" type="button" :disabled="actionLocked || !settingsStore.loaded" @click="generate">{{ t('common.generateItinerary') }}</button>
              </template>
            </StatePanel>
          </article>
        </div>

        <div class="workspace-column">
          <article class="panel panel-stack">
            <div>
              <p class="kicker">{{ copy.quickRefineTitle }}</p>
              <h2>{{ copy.quickRefineTitle }}</h2>
              <p class="muted">{{ copy.quickRefineSubtitle }}</p>
            </div>

            <div class="quick-actions-grid">
              <button v-for="action in quickRefineActions" :key="action.label" type="button" :disabled="actionLocked || !canUseBrowserModel" @click="runPresetRefine(action)">
                {{ action.label }}
              </button>
            </div>

            <div class="field">
              <label for="custom-refine">{{ copy.customRefineLabel }}</label>
              <textarea id="custom-refine" v-model="customRefineInstruction" :placeholder="copy.customRefinePlaceholder"></textarea>
            </div>

            <div class="inline-actions">
              <button class="primary" type="button" :disabled="actionLocked || !canUseBrowserModel" @click="submitCustomRefine">
                {{ refinePending ? copy.refining : copy.customRefineSubmit }}
              </button>
            </div>
          </article>

          <article class="panel panel-stack">
            <div>
              <p class="kicker">{{ copy.searchPanelTitle }}</p>
              <h2>{{ copy.searchPanelTitle }}</h2>
              <p class="muted">{{ copy.searchPanelMessage }}</p>
            </div>

            <div class="field">
              <label for="query">{{ copy.queryLabel }}</label>
              <input id="query" v-model="searchQuery" />
            </div>

            <div class="field">
              <label for="links">{{ copy.linksLabel }}</label>
              <textarea id="links" v-model="manualLinks"></textarea>
            </div>

            <div class="inline-actions">
              <button class="primary" type="button" :disabled="searchPending" @click="runSearch">
                {{ searchPending ? copy.searching : copy.runSearch }}
              </button>
            </div>

            <StatePanel v-if="searchError" kind="error" :title="t('tripDetail.searchFailedTitle')" :message="searchError" compact />

            <div v-if="searchResults.length" class="page-grid">
              <article v-for="doc in searchResults" :key="doc.id" class="search-card panel-stack">
                <p class="kicker">{{ doc.platform }}</p>
                <h3>{{ doc.place_name || doc.title }}</h3>
                <p>{{ doc.summary }}</p>
                <p class="muted">{{ t('common.finalScore', { value: doc.scores.final_score }) }}</p>
                <a class="button-link" :href="doc.url" target="_blank" rel="noreferrer">{{ copy.sourceOpen }}</a>
              </article>
            </div>
          </article>
        </div>
      </div>
    </template>
  </section>
</template>