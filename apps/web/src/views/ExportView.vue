<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue"
import type { ExportArtifact, JobTimelineEntry } from "@travelmind/shared-types"
import { useRoute } from "vue-router"
import StatePanel from "@/components/StatePanel.vue"
import StatusPill from "@/components/StatusPill.vue"
import { api, getErrorMessage, type JobRecord } from "@/lib/api"
import { formatDateTime } from "@/lib/format"
import { useI18n } from "@/lib/useI18n"

const route = useRoute()
const job = ref<JobRecord | null>(null)
const loading = ref(true)
const refreshing = ref(false)
const loadError = ref<string | null>(null)
const pollError = ref<string | null>(null)
let timer: number | null = null

const enCopy = {
  notAvailable: "N/A",
  stageLabel: "Stage",
  progressLabel: "Progress",
  timelineTitle: "Timeline",
  timelineEmptyTitle: "Timeline waiting for updates",
  timelineEmptyMessage: "The backend will append stage updates here while the export job runs.",
  artifactsTitle: "Artifacts",
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
    "export.pdf": "Guide export"
  } as Record<string, string>,
  artifactTypes: {
    md: "Markdown",
    pdf: "PDF",
    json: "JSON"
  } as Record<string, string>
}

const zhCopy = {
  notAvailable: "暂无",
  stageLabel: "阶段",
  progressLabel: "进度",
  timelineTitle: "时间线",
  timelineEmptyTitle: "时间线等待更新",
  timelineEmptyMessage: "导出任务运行时，后端会把阶段更新追加到这里。",
  artifactsTitle: "导出产物",
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
    "export.pdf": "攻略导出"
  } as Record<string, string>,
  artifactTypes: {
    md: "Markdown",
    pdf: "PDF",
    json: "JSON"
  } as Record<string, string>
}

const { locale, t } = useI18n()
const copy = computed(() => (locale.value === "zh-CN" ? zhCopy : enCopy))
const jobId = computed(() => String(route.params.id ?? ""))
const jobTimeline = computed<JobTimelineEntry[]>(() => (Array.isArray(job.value?.timeline_json) ? job.value.timeline_json : []))
const jobProgress = computed(() => clampProgress(job.value?.progress_percent, job.value?.status))
const resultArtifacts = computed<ExportArtifact[]>(() => extractArtifacts(job.value?.result))
const resultMetadataEntries = computed(() => {
  const result = job.value?.result
  if (!isRecord(result)) {
    return []
  }

  return Object.entries(result).filter(([key]) => !["artifacts", "file_name", "file_path", "file_url", "content_type", "size_bytes"].includes(key))
})

function stopPolling() {
  if (timer !== null) {
    window.clearTimeout(timer)
    timer = null
  }
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

function formatResultValue(value: unknown): string {
  if (value === null || value === undefined) {
    return copy.value.notAvailable
  }

  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value)
  }

  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}

function normalizeArtifact(value: unknown): ExportArtifact | null {
  if (!isRecord(value) || typeof value.type !== "string" || typeof value.file_name !== "string" || typeof value.file_url !== "string") {
    return null
  }

  return {
    type: value.type,
    file_name: value.file_name,
    file_url: value.file_url,
    file_path: typeof value.file_path === "string" ? value.file_path : null,
    content_type: typeof value.content_type === "string" ? value.content_type : null,
    size_bytes: typeof value.size_bytes === "number" ? value.size_bytes : null
  }
}

function extractArtifacts(result: unknown): ExportArtifact[] {
  if (!isRecord(result)) {
    return []
  }

  const directArtifacts = Array.isArray(result.artifacts)
    ? result.artifacts
      .map((artifact) => normalizeArtifact(artifact))
      .filter((artifact): artifact is ExportArtifact => artifact !== null)
    : []

  if (directArtifacts.length > 0) {
    return directArtifacts
  }

  const fallbackArtifact = normalizeArtifact({
    type: "pdf",
    file_name: result.file_name,
    file_url: result.file_url,
    file_path: result.file_path,
    content_type: result.content_type,
    size_bytes: result.size_bytes
  })

  return fallbackArtifact ? [fallbackArtifact] : []
}

function formatArtifactType(value: string): string {
  return copy.value.artifactTypes[value] ?? humanizeToken(value)
}

function formatBytes(value?: number | null): string {
  if (typeof value !== "number" || Number.isNaN(value) || value < 0) {
    return copy.value.notAvailable
  }

  if (value < 1024) {
    return `${value} B`
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

async function load(initial = false) {
  if (initial) {
    loading.value = true
    loadError.value = null
    pollError.value = null
  } else {
    refreshing.value = true
  }

  try {
    job.value = await api.getJob(jobId.value)

    if (job.value.status === "queued" || job.value.status === "running") {
      stopPolling()
      timer = window.setTimeout(() => {
        void load()
      }, 1500)
    } else {
      stopPolling()
    }
  } catch (value) {
    stopPolling()
    const message = getErrorMessage(value, t("exportView.unavailableTitle"))
    if (initial || !job.value) {
      job.value = null
      loadError.value = message
    } else {
      pollError.value = message
    }
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

function retry() {
  void load(true)
}

watch(
  jobId,
  () => {
    stopPolling()
    void load(true)
  },
  { immediate: true }
)

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<template>
  <section class="page-grid" style="max-width: 880px; margin: 0 auto;">
    <StatePanel
      v-if="loading"
      kind="loading"
      :title="t('exportView.loadingTitle')"
      :message="t('exportView.loadingMessage')"
    />

    <StatePanel
      v-else-if="loadError"
      kind="error"
      :title="t('exportView.unavailableTitle')"
      :message="loadError"
      :action-label="t('common.retry')"
      @action="retry"
    />

    <article v-else-if="job" class="panel panel-stack">
      <div>
        <p class="kicker">{{ t('exportView.kicker') }}</p>
        <h1>{{ formatJobType(job.type) }}</h1>
        <p class="muted">{{ job.job_id }}</p>
      </div>

      <div class="inline-actions" style="align-items: center;">
        <StatusPill :status="job.status" />
        <span class="muted">{{ t('common.updatedAt', { value: formatDateTime(job.updated_at) }) }}</span>
      </div>

      <div class="metric-grid">
        <article class="metric-card">
          <p class="kicker">{{ copy.stageLabel }}</p>
          <strong>{{ formatStage(job.stage) }}</strong>
        </article>
        <article class="metric-card">
          <p class="kicker">{{ copy.progressLabel }}</p>
          <strong>{{ formatProgress(job.progress_percent, job.status) }}</strong>
        </article>
        <article class="metric-card">
          <p class="kicker">{{ t('exportView.resultKicker') }}</p>
          <p>{{ job.result ? t('status.completed') : copy.notAvailable }}</p>
        </article>
      </div>

      <div class="progress-block">
        <div class="progress-inline">
          <span>{{ copy.progressLabel }}</span>
          <strong>{{ formatProgress(job.progress_percent, job.status) }}</strong>
        </div>
        <div class="progress-track" aria-hidden="true">
          <div class="progress-fill" :style="{ width: `${jobProgress}%` }"></div>
        </div>
      </div>

      <StatePanel
        v-if="pollError"
        kind="error"
        :title="t('exportView.refreshFailedTitle')"
        :message="pollError"
        compact
      />

      <StatePanel
        v-if="job.status === 'queued' || job.status === 'running'"
        kind="loading"
        :title="t('exportView.runningTitle')"
        :message="refreshing ? t('exportView.runningPolling') : t('exportView.runningWaiting')"
        compact
      />

      <StatePanel
        v-else-if="job.status === 'failed'"
        kind="error"
        :title="t('exportView.failedTitle')"
        :message="job.error_message ?? t('exportView.failedTitle')"
        compact
      />

      <div class="panel-subsection">
        <div class="inline-actions" style="justify-content: space-between; align-items: center;">
          <h2>{{ copy.timelineTitle }}</h2>
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
            <p>{{ entry.stage_message || copy.notAvailable }}</p>
            <div class="progress-inline">
              <span>{{ copy.progressLabel }}</span>
              <strong>{{ formatProgress(entry.progress_percent, entry.status) }}</strong>
            </div>
          </li>
        </ol>
      </div>

      <div v-if="job.result" class="panel" style="margin: 0; padding: 18px;">
        <p class="kicker">{{ t('exportView.resultKicker') }}</p>
        <div v-if="resultArtifacts.length" class="panel-subsection" style="padding-top: 0;">
          <div class="inline-actions" style="justify-content: space-between; align-items: center;">
            <h2>{{ copy.artifactsTitle }}</h2>
            <span class="muted">{{ resultArtifacts.length }}</span>
          </div>
          <ul class="result-list">
            <li v-for="artifact in resultArtifacts" :key="`${artifact.type}-${artifact.file_name}`">
              {{ formatArtifactType(artifact.type) }}: {{ artifact.file_name }} <span class="muted">· {{ formatBytes(artifact.size_bytes) }}</span>
            </li>
          </ul>
          <div class="inline-actions" style="margin-top: 18px; flex-wrap: wrap;">
            <a
              v-for="artifact in resultArtifacts"
              :key="artifact.file_url"
              class="button-link primary"
              :href="artifact.file_url"
              target="_blank"
              rel="noreferrer"
            >
              {{ t('common.openGeneratedFile') }} · {{ formatArtifactType(artifact.type) }}
            </a>
          </div>
        </div>
        <ul v-if="resultMetadataEntries.length" class="result-list">
          <li v-for="[key, value] in resultMetadataEntries" :key="key">{{ key }}: {{ formatResultValue(value) }}</li>
        </ul>
        <div class="inline-actions" style="margin-top: 18px;">
          <RouterLink v-if="job.trip_id" class="button-link" :to="`/trips/${job.trip_id}`">{{ t('common.backToTrip') }}</RouterLink>
        </div>
      </div>

      <StatePanel
        v-else-if="job.status !== 'queued' && job.status !== 'running' && job.status !== 'failed'"
        kind="empty"
        :title="t('exportView.emptyTitle')"
        :message="t('exportView.emptyMessage')"
        compact
      />
    </article>
  </section>
</template>
