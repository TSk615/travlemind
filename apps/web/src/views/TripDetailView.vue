<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { useRoute } from "vue-router"
import type { JobTimelineEntry, SearchDocument, Trip, TripRefineInput } from "@travelmind/shared-types"
import StatePanel from "@/components/StatePanel.vue"
import StatusPill from "@/components/StatusPill.vue"
import { api, getErrorMessage, type JobRecord } from "@/lib/api"
import { formatCurrency, formatDateRange, formatDateTime } from "@/lib/format"
import { useI18n } from "@/lib/useI18n"

const route = useRoute()
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

const STORAGE_PREFIX = "travelmind.trip-job:"

const enCopy = {
  notAvailable: "N/A",
  workspaceKicker: "Workbench",
  workspaceTitle: "Run, track, and refine this trip",
  workspaceDescription: "Generation, refinement, and export now share the same async job workspace.",
  currentJobKicker: "Current job",
  stageLabel: "Stage",
  stageMessageLabel: "Stage note",
  progressLabel: "Progress",
  timelineTitle: "Timeline",
  jobEmptyTitle: "No active job yet",
  jobEmptyMessage: "Generate an itinerary, refine the plan, or export a PDF to populate the workbench.",
  timelineEmptyTitle: "Timeline waiting for updates",
  timelineEmptyMessage: "The backend will append stage updates here once the job starts reporting progress.",
  refiningTitle: "Applying refinement",
  refiningMessage: "Polling the job endpoint until the refined itinerary is written back to the trip.",
  refineKicker: "Refine",
  refineTitle: "Adjust the trip without leaving the workspace",
  refineDescription: "Quick actions submit common refine requests. Use the text box for a custom instruction.",
  refineInputLabel: "Custom refine instruction",
  refinePlaceholder: "Example: make day 2 slower and move the photo-heavy stops earlier.",
  refineSubmit: "Submit refine request",
  refineValidation: "Add at least 3 characters before sending a refine request.",
  refineActions: {
    budget: "Cut budget",
    transit: "Reduce transit",
    photo: "Better for photos",
    depth: "Add depth"
  },
  refinePresets: {
    budget: "Lower the budget while keeping the trip practical and enjoyable.",
    transit: "Reduce long transfers and keep each day easier to move through.",
    photo: "Prioritize photogenic stops and better light for photos.",
    depth: "Add more local context and deeper cultural experiences."
  },
  searchResultsKicker: "Results",
  searchResultsTitle: "Structured source results",
  searchResultsDescription: "Search documents now expose normalized place, hours, price, address, coordinates, and source type when available.",
  searchValidation: "Enter at least 2 characters before searching.",
  searchFields: {
    placeName: "Place",
    category: "Category",
    openingHours: "Opening hours",
    priceHint: "Price hint",
    address: "Address",
    geo: "Geo",
    sourceType: "Source type"
  },
  jobStages: {
    queued: "Queued",
    brief_parsing: "Brief parsing",
    source_search: "Source search",
    source_scoring: "Source scoring",
    route_planning: "Route planning",
    hotel_matching: "Stay matching",
    export_ready: "Finalizing"
  } as Record<string, string>,
  jobTypes: {
    "trip.generate": "Itinerary generation",
    "trip.refine": "Trip refinement",
    "export.pdf": "PDF export"
  } as Record<string, string>
}

const zhCopy = {
  notAvailable: "暂无",
  workspaceKicker: "工作台",
  workspaceTitle: "在这里运行、跟踪并微调这次行程",
  workspaceDescription: "生成、refine 和导出现在共用同一套异步任务工作台。",
  currentJobKicker: "当前任务",
  stageLabel: "阶段",
  stageMessageLabel: "阶段说明",
  progressLabel: "进度",
  timelineTitle: "时间线",
  jobEmptyTitle: "还没有活动任务",
  jobEmptyMessage: "先生成行程、发起 refine，或导出 PDF，工作台就会开始记录进度。",
  timelineEmptyTitle: "时间线等待更新",
  timelineEmptyMessage: "任务开始上报后，后端会把阶段更新追加到这里。",
  refiningTitle: "正在应用 refine",
  refiningMessage: "正在轮询任务状态，直到新的行程结果写回 trip 记录。",
  refineKicker: "Refine",
  refineTitle: "不离开工作台就能调整行程",
  refineDescription: "快捷操作会直接提交常见 refine 指令，也可以在文本框里输入自定义要求。",
  refineInputLabel: "自定义 refine 指令",
  refinePlaceholder: "例如：把第 2 天放慢一点，并把更适合拍照的点位提前。",
  refineSubmit: "提交 refine 请求",
  refineValidation: "请至少输入 3 个字符后再提交 refine。",
  refineActions: {
    budget: "压预算",
    transit: "减少赶路",
    photo: "更适合拍照",
    depth: "增加深度体验"
  },
  refinePresets: {
    budget: "请在保证行程可执行和体验不明显下降的前提下，尽量压低整体预算。",
    transit: "请减少长距离转场，让每天的移动更轻松、节奏更顺。",
    photo: "请优先安排更适合拍照的点位和更好的光线时段。",
    depth: "请加入更多在地背景信息和更有深度的文化体验。"
  },
  searchResultsKicker: "结果",
  searchResultsTitle: "结构化搜索结果",
  searchResultsDescription: "搜索结果会尽量展示地点、营业时间、价格提示、地址、坐标和来源类型。",
  searchValidation: "请至少输入 2 个字符后再搜索。",
  searchFields: {
    placeName: "地点",
    category: "分类",
    openingHours: "营业时间",
    priceHint: "价格提示",
    address: "地址",
    geo: "坐标",
    sourceType: "来源类型"
  },
  jobStages: {
    queued: "已排队",
    brief_parsing: "解析需求",
    source_search: "收集来源",
    source_scoring: "来源评分",
    route_planning: "路线规划",
    hotel_matching: "住宿补位",
    export_ready: "整理结果"
  } as Record<string, string>,
  jobTypes: {
    "trip.generate": "生成行程",
    "trip.refine": "微调行程",
    "export.pdf": "导出 PDF"
  } as Record<string, string>
}

const { locale, t } = useI18n()
const copy = computed(() => (locale.value === "zh-CN" ? zhCopy : enCopy))
const tripId = computed(() => String(route.params.id ?? ""))
const isJobRunning = computed(() => activeJob.value?.status === "queued" || activeJob.value?.status === "running")
const actionLocked = computed(() => generatePending.value || exportPending.value || refinePending.value || isJobRunning.value)
const jobTimeline = computed<JobTimelineEntry[]>(() => (Array.isArray(activeJob.value?.timeline_json) ? activeJob.value.timeline_json : []))
const jobProgress = computed(() => clampProgress(activeJob.value?.progress_percent, activeJob.value?.status))

const quickRefineActions = computed(() => [
  { key: "budget", label: copy.value.refineActions.budget, instruction: copy.value.refinePresets.budget, scope: "budget" },
  { key: "transit", label: copy.value.refineActions.transit, instruction: copy.value.refinePresets.transit, scope: "travel_flow" },
  { key: "photo", label: copy.value.refineActions.photo, instruction: copy.value.refinePresets.photo, scope: "photo_spots" },
  { key: "depth", label: copy.value.refineActions.depth, instruction: copy.value.refinePresets.depth, scope: "depth" }
])

function getStorageKey(id: string): string {
  return `${STORAGE_PREFIX}${id}`
}

function rememberJob(job: JobRecord): void {
  if (typeof window === "undefined") {
    return
  }

  try {
    window.localStorage.setItem(getStorageKey(tripId.value), job.job_id)
  } catch {
    // Ignore storage errors and keep the current in-memory state.
  }
}

function clearRememberedJob(): void {
  if (typeof window === "undefined") {
    return
  }

  try {
    window.localStorage.removeItem(getStorageKey(tripId.value))
  } catch {
    // Ignore storage cleanup errors.
  }
}

function stopPolling() {
  if (timer !== null) {
    window.clearTimeout(timer)
    timer = null
  }
}

function paceLabel(value: string): string {
  const key = `common.pace.${value}`
  const translated = t(key)
  return translated === key ? value : translated
}

function humanizeToken(value: string): string {
  return value
    .split(/[_\-.]+/)
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(" ")
}

function formatStage(value?: string | null): string {
  if (!value) {
    return copy.value.notAvailable
  }

  return copy.value.jobStages[value] ?? humanizeToken(value)
}

function formatJobType(value?: string | null): string {
  if (!value) {
    return copy.value.notAvailable
  }

  return copy.value.jobTypes[value] ?? humanizeToken(value)
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

function formatGeo(doc: SearchDocument): string {
  if (!doc.geo || !Number.isFinite(doc.geo.lat) || !Number.isFinite(doc.geo.lng)) {
    return copy.value.notAvailable
  }

  return `${doc.geo.lat.toFixed(4)}, ${doc.geo.lng.toFixed(4)}`
}

function setJobError(jobType: string | undefined, message: string): void {
  if (jobType === "export.pdf") {
    exportError.value = message
    return
  }

  if (jobType === "trip.refine") {
    refineError.value = message
    return
  }

  generateError.value = message
}

async function loadTrip(options: { initial?: boolean } = {}) {
  const initial = options.initial ?? false

  if (initial) {
    loading.value = true
    error.value = null
  }

  try {
    trip.value = await api.getTrip(tripId.value)
  } catch (value) {
    if (initial || !trip.value) {
      trip.value = null
      error.value = getErrorMessage(value, t("tripDetail.unavailableTitle"))
    }
  } finally {
    if (initial) {
      loading.value = false
    }
  }
}

async function restoreRememberedJob() {
  if (typeof window === "undefined") {
    return
  }

  const rememberedId = window.localStorage.getItem(getStorageKey(tripId.value))
  if (!rememberedId) {
    return
  }

  try {
    activeJob.value = await api.getJob(rememberedId)
    rememberJob(activeJob.value)

    if (activeJob.value.status === "queued" || activeJob.value.status === "running") {
      timer = window.setTimeout(() => {
        void pollJob(rememberedId)
      }, 1500)
    }
  } catch {
    activeJob.value = null
    clearRememberedJob()
  }
}

async function pollJob(jobId: string) {
  stopPolling()

  try {
    activeJob.value = await api.getJob(jobId)
    rememberJob(activeJob.value)

    if (activeJob.value.status === "completed" || activeJob.value.status === "failed") {
      await loadTrip()
      return
    }

    timer = window.setTimeout(() => {
      void pollJob(jobId)
    }, 1500)
  } catch (value) {
    const message = getErrorMessage(value, t("tripDetail.asyncFailedTitle"))
    setJobError(activeJob.value?.type, message)
  }
}

async function generate() {
  generatePending.value = true
  generateError.value = null

  try {
    const job = await api.generateTrip(tripId.value)
    activeJob.value = job
    rememberJob(job)
    await pollJob(job.job_id)
  } catch (value) {
    generateError.value = getErrorMessage(value, t("tripDetail.generationFailedTitle"))
  } finally {
    generatePending.value = false
  }
}

async function exportPdf() {
  exportPending.value = true
  exportError.value = null

  try {
    const job = await api.exportPdf(tripId.value)
    activeJob.value = job
    rememberJob(job)
    await pollJob(job.job_id)
  } catch (value) {
    exportError.value = getErrorMessage(value, t("tripDetail.exportFailedTitle"))
  } finally {
    exportPending.value = false
  }
}

async function submitRefine(payload: TripRefineInput) {
  refinePending.value = true
  refineError.value = null

  try {
    const job = await api.refineTrip(tripId.value, payload)
    activeJob.value = job
    rememberJob(job)
    await pollJob(job.job_id)
  } catch (value) {
    refineError.value = getErrorMessage(value, t("tripDetail.asyncFailedTitle"))
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

async function runSearch() {
  const query = searchQuery.value.trim()
  if (query.length < 2) {
    hasSearched.value = true
    searchResults.value = []
    searchError.value = copy.value.searchValidation
    return
  }

  hasSearched.value = true
  searchPending.value = true
  searchError.value = null

  try {
    searchResults.value = await api.search({
      query,
      destination: trip.value?.destination,
      manual_links: manualLinks.value
        .split(/\r?\n|,/) 
        .map((value) => value.trim())
        .filter(Boolean)
    })
  } catch (value) {
    searchResults.value = []
    searchError.value = getErrorMessage(value, t("tripDetail.searchFailedTitle"))
  } finally {
    searchPending.value = false
  }
}

async function initializeView() {
  await loadTrip({ initial: true })
  await restoreRememberedJob()
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
    searchQuery.value = "best quiet morning spots"
    manualLinks.value = "https://kyoto.travel/en"
    customRefineInstruction.value = ""
    void initializeView()
  },
  { immediate: true }
)

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<template>
  <section class="page-grid">
    <StatePanel
      v-if="loading"
      kind="loading"
      :title="t('tripDetail.loadingTitle')"
      :message="t('tripDetail.loadingMessage')"
    />

    <StatePanel
      v-else-if="error"
      kind="error"
      :title="t('tripDetail.unavailableTitle')"
      :message="error"
      :action-label="t('common.retry')"
      @action="initializeView"
    />

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
            <p v-if="trip.interests.length" class="muted">{{ trip.interests.join(' · ') }}</p>
          </div>
          <div class="stack-actions">
            <button class="primary" type="button" :disabled="actionLocked" @click="generate">
              {{ generatePending ? t('common.generating') : t('common.generateItinerary') }}
            </button>
            <button type="button" :disabled="actionLocked" @click="exportPdf">
              {{ exportPending ? t('common.exporting') : t('common.exportPdf') }}
            </button>
          </div>
        </div>
      </article>

      <div class="workspace-layout">
        <div class="workspace-column">
          <article class="panel panel-stack">
            <div>
              <p class="kicker">{{ copy.workspaceKicker }}</p>
              <h2>{{ copy.workspaceTitle }}</h2>
              <p class="muted">{{ copy.workspaceDescription }}</p>
            </div>

            <StatePanel
              v-if="!activeJob"
              kind="info"
              :title="copy.jobEmptyTitle"
              :message="copy.jobEmptyMessage"
              compact
            />

            <template v-else>
              <div class="inline-actions" style="justify-content: space-between; align-items: flex-start;">
                <div>
                  <p class="kicker">{{ copy.currentJobKicker }}</p>
                  <h3>{{ formatJobType(activeJob.type) }}</h3>
                  <p class="muted">{{ activeJob.job_id }}</p>
                </div>
                <div class="stack-actions">
                  <StatusPill :status="activeJob.status" />
                  <span class="muted">{{ t('common.updatedAt', { value: formatDateTime(activeJob.updated_at) }) }}</span>
                </div>
              </div>

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
                  <p class="kicker">{{ copy.stageMessageLabel }}</p>
                  <p>{{ fieldValue(activeJob.stage_message) }}</p>
                </article>
              </div>

              <div class="progress-block">
                <div class="progress-inline">
                  <span>{{ copy.progressLabel }}</span>
                  <strong>{{ formatProgress(activeJob.progress_percent, activeJob.status) }}</strong>
                </div>
                <div class="progress-track" aria-hidden="true">
                  <div class="progress-fill" :style="{ width: `${jobProgress}%` }"></div>
                </div>
              </div>

              <div v-if="activeJob" class="inline-actions" style="align-items: center;">
                <RouterLink v-if="activeJob.type === 'export.pdf'" class="button-link" :to="`/exports/${activeJob.job_id}`">{{ t('common.openExport') }}</RouterLink>
                <a
                  v-if="activeJob.type === 'export.pdf' && typeof activeJob.result?.file_url === 'string'"
                  class="button-link primary"
                  :href="activeJob.result.file_url"
                  target="_blank"
                  rel="noreferrer"
                >
                  {{ t('common.downloadPdf') }}
                </a>
              </div>

              <StatePanel v-if="generateError" kind="error" :title="t('tripDetail.generationFailedTitle')" :message="generateError" compact />
              <StatePanel v-if="exportError" kind="error" :title="t('tripDetail.exportFailedTitle')" :message="exportError" compact />
              <StatePanel v-if="refineError" kind="error" :title="copy.refineTitle" :message="refineError" compact />

              <StatePanel
                v-if="activeJob.status === 'queued' || activeJob.status === 'running'"
                kind="loading"
                :title="activeJob.type === 'trip.refine' ? copy.refiningTitle : activeJob.type === 'export.pdf' ? t('tripDetail.exportingTitle') : t('tripDetail.generatingTitle')"
                :message="activeJob.type === 'trip.refine' ? copy.refiningMessage : t('tripDetail.generatingMessage')"
                compact
              />

              <StatePanel
                v-if="activeJob.status === 'failed' && activeJob.error_message"
                kind="error"
                :title="t('tripDetail.asyncFailedTitle')"
                :message="activeJob.error_message"
                compact
              />

              <div class="panel-subsection">
                <div class="inline-actions" style="justify-content: space-between; align-items: center;">
                  <h3>{{ copy.timelineTitle }}</h3>
                  <span class="muted">{{ jobTimeline.length }}</span>
                </div>

                <StatePanel
                  v-if="jobTimeline.length === 0"
                  kind="info"
                  :title="copy.timelineEmptyTitle"
                  :message="copy.timelineEmptyMessage"
                  compact
                />

                <ol v-else class="timeline-list">
                  <li v-for="entry in jobTimeline" :key="`${entry.recorded_at}-${entry.status}-${entry.stage ?? 'none'}`" class="timeline-item">
                    <div class="timeline-meta">
                      <StatusPill :status="entry.status" />
                      <span class="muted">{{ formatStage(entry.stage) }}</span>
                      <span class="muted">{{ formatDateTime(entry.recorded_at) }}</span>
                    </div>
                    <p>{{ fieldValue(entry.stage_message) }}</p>
                    <div class="progress-inline">
                      <span>{{ copy.progressLabel }}</span>
                      <strong>{{ formatProgress(entry.progress_percent, entry.status) }}</strong>
                    </div>
                  </li>
                </ol>
              </div>
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
              v-else-if="generatePending || refinePending || (activeJob && (activeJob.type === 'trip.generate' || activeJob.type === 'trip.refine') && activeJob.status !== 'failed')"
              kind="loading"
              :title="t('tripDetail.itineraryPendingTitle')"
              :message="t('tripDetail.itineraryPendingMessage')"
              compact
            />

            <StatePanel
              v-else
              kind="empty"
              :title="t('tripDetail.itineraryEmptyTitle')"
              :message="t('tripDetail.itineraryEmptyMessage')"
              compact
            >
              <template #actions>
                <button class="primary" type="button" :disabled="actionLocked" @click="generate">{{ t('common.generateItinerary') }}</button>
              </template>
            </StatePanel>
          </article>

          <article class="panel panel-stack">
            <div>
              <p class="kicker">{{ copy.searchResultsKicker }}</p>
              <h2>{{ copy.searchResultsTitle }}</h2>
              <p class="muted">{{ copy.searchResultsDescription }}</p>
            </div>

            <StatePanel
              v-if="searchPending"
              kind="loading"
              :title="t('tripDetail.searchLoadingTitle')"
              :message="t('tripDetail.searchLoadingMessage')"
              compact
            />

            <StatePanel
              v-else-if="searchError"
              kind="error"
              :title="t('tripDetail.searchFailedTitle')"
              :message="searchError"
              compact
            />

            <StatePanel
              v-else-if="!hasSearched"
              kind="info"
              :title="t('tripDetail.searchEmptyBeforeTitle')"
              :message="t('tripDetail.searchEmptyBeforeMessage')"
              compact
            />

            <StatePanel
              v-else-if="searchResults.length === 0"
              kind="empty"
              :title="t('tripDetail.searchEmptyTitle')"
              :message="t('tripDetail.searchEmptyMessage')"
              compact
            />

            <div v-else class="page-grid">
              <article v-for="doc in searchResults" :key="doc.id" class="search-card panel-stack">
                <div class="inline-actions" style="justify-content: space-between; align-items: flex-start;">
                  <div>
                    <p class="kicker">{{ doc.platform }}</p>
                    <h3>{{ doc.place_name || doc.title }}</h3>
                  </div>
                  <p class="muted">{{ t('common.finalScore', { value: doc.scores.final_score }) }}</p>
                </div>
                <p>{{ doc.summary }}</p>
                <dl class="data-grid">
                  <div class="data-pair">
                    <dt>{{ copy.searchFields.placeName }}</dt>
                    <dd>{{ fieldValue(doc.place_name) }}</dd>
                  </div>
                  <div class="data-pair">
                    <dt>{{ copy.searchFields.category }}</dt>
                    <dd>{{ fieldValue(doc.category) }}</dd>
                  </div>
                  <div class="data-pair">
                    <dt>{{ copy.searchFields.openingHours }}</dt>
                    <dd>{{ fieldValue(doc.opening_hours) }}</dd>
                  </div>
                  <div class="data-pair">
                    <dt>{{ copy.searchFields.priceHint }}</dt>
                    <dd>{{ fieldValue(doc.price_hint) }}</dd>
                  </div>
                  <div class="data-pair">
                    <dt>{{ copy.searchFields.address }}</dt>
                    <dd>{{ fieldValue(doc.address) }}</dd>
                  </div>
                  <div class="data-pair">
                    <dt>{{ copy.searchFields.geo }}</dt>
                    <dd>{{ formatGeo(doc) }}</dd>
                  </div>
                  <div class="data-pair">
                    <dt>{{ copy.searchFields.sourceType }}</dt>
                    <dd>{{ fieldValue(doc.source_type) }}</dd>
                  </div>
                </dl>
                <ul v-if="doc.scores.reasons.length" class="summary-list">
                  <li v-for="reason in doc.scores.reasons" :key="reason">{{ reason }}</li>
                </ul>
                <div class="inline-actions" style="justify-content: space-between; align-items: center;">
                  <span class="muted">{{ doc.title }}</span>
                  <a class="button-link" :href="doc.url" target="_blank" rel="noreferrer">{{ t('common.openSource') }}</a>
                </div>
              </article>
            </div>
          </article>
        </div>

        <div class="workspace-column">
          <article class="panel panel-stack">
            <div>
              <p class="kicker">{{ copy.refineKicker }}</p>
              <h2>{{ copy.refineTitle }}</h2>
              <p class="muted">{{ copy.refineDescription }}</p>
            </div>

            <div class="quick-actions-grid">
              <button
                v-for="action in quickRefineActions"
                :key="action.key"
                type="button"
                :disabled="actionLocked"
                @click="runPresetRefine(action)"
              >
                {{ action.label }}
              </button>
            </div>

            <div class="field">
              <label for="custom-refine">{{ copy.refineInputLabel }}</label>
              <textarea id="custom-refine" v-model="customRefineInstruction" :placeholder="copy.refinePlaceholder"></textarea>
            </div>

            <div class="inline-actions">
              <button class="primary" type="button" :disabled="actionLocked" @click="submitCustomRefine">
                {{ refinePending ? copy.refiningTitle : copy.refineSubmit }}
              </button>
            </div>
          </article>

          <article class="panel panel-stack">
            <div>
              <p class="kicker">{{ t('tripDetail.searchKicker') }}</p>
              <h2>{{ t('tripDetail.searchTitle') }}</h2>
              <p class="muted">{{ t('tripDetail.searchDescription') }}</p>
            </div>

            <div class="field">
              <label for="query">{{ t('tripDetail.queryLabel') }}</label>
              <input id="query" v-model="searchQuery" />
            </div>

            <div class="field">
              <label for="links">{{ t('tripDetail.linksLabel') }}</label>
              <textarea id="links" v-model="manualLinks"></textarea>
            </div>

            <div class="inline-actions">
              <button class="primary" type="button" :disabled="searchPending" @click="runSearch">
                {{ searchPending ? t('common.searching') : t('common.runSearch') }}
              </button>
            </div>
          </article>

          <article v-if="trip.latest_agent_trace" class="panel panel-stack">
            <div>
              <p class="kicker">{{ t('tripDetail.agentTrace') }}</p>
              <h2>{{ trip.latest_agent_trace.provider }}</h2>
              <p class="muted">{{ trip.latest_agent_trace.workflow_id }}</p>
            </div>
            <ul class="detail-list">
              <li v-for="note in trip.latest_agent_trace.notes" :key="note">{{ note }}</li>
            </ul>
            <p v-if="trip.latest_agent_trace.license_notice" class="muted">{{ trip.latest_agent_trace.license_notice }}</p>
          </article>
        </div>
      </div>
    </template>
  </section>
</template>

