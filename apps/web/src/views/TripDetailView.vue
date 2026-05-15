<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { useRouter } from "vue-router"
import type { AgentRunStep, ItineraryItem, JobTimelineEntry, SearchDocument, TransportBookingSummary, Trip, TripRefineInput } from "@travelmind/shared-types"
import LlmStatusNotice from "@/components/LlmStatusNotice.vue"
import StatePanel from "@/components/StatePanel.vue"
import StatusPill from "@/components/StatusPill.vue"
import { api, getErrorMessage, type JobRecord } from "@/lib/api"
import { enrichGeneratedItineraryWithBudget } from "@/lib/budgeting"
import { generateTripInBrowser, refineTripInBrowser } from "@/lib/browserPlanner"
import { formatCurrency, formatDateRange, formatDateTime } from "@/lib/format"
import { useI18n } from "@/lib/useI18n"
import { useJobGuardStore } from "@/stores/jobGuard"
import { useLlmSettingsStore } from "@/stores/llmSettings"

interface ImageEnrichmentDebugRow {
  item_id: string
  name: string
  status: string
  priority_tier?: string | null
  failure_reason?: string | null
  image_count?: number
  source_count?: number
}

const props = withDefaults(
  defineProps<{
    id: string
    jobId?: string
  }>(),
  {
    jobId: ""
  }
)
const router = useRouter()
const settingsStore = useLlmSettingsStore()
const jobGuard = useJobGuardStore()
void settingsStore.bootstrap()

const trip = ref<Trip | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const activeJob = ref<JobRecord | null>(null)
const generatePending = ref(false)
const generateError = ref<string | null>(null)
const exportPending = ref(false)
const exportError = ref<string | null>(null)
const imageEnrichPending = ref(false)
const imageEnrichError = ref<string | null>(null)
const deletePending = ref(false)
const deleteError = ref<string | null>(null)
const refinePending = ref(false)
const refineError = ref<string | null>(null)
const searchPending = ref(false)
const searchError = ref<string | null>(null)
const searchResults = ref<SearchDocument[]>([])
const hasSearched = ref(false)
const searchQuery = ref("best quiet morning spots")
const manualLinks = ref("https://kyoto.travel/en")
const customRefineInstruction = ref("")
const communityPending = ref(false)
const communityError = ref<string | null>(null)
const communityNotice = ref<string | null>(null)
const communityNoteDraft = ref("")
const communityEditorOpen = ref(false)
const communityEditorMode = ref<"create" | "edit">("create")
let timer: number | null = null
const JOB_POLL_INTERVAL_MS = 3000

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
  exportActionLabel: "Export guide pack",
  exportActionRunningLabel: "Exporting pack...",
  enrichImagesActionLabel: "Retry image enrichment",
  enrichImagesActionRunningLabel: "Retrying image enrichment...",
  refineValidation: "Enter at least 3 characters.",
  searchPanelTitle: "Search grounding",
  searchPanelMessage: "These fixed or structured search results come from your backend and are used as grounding in the prompt.",
  queryLabel: "Query",
  linksLabel: "Manual links",
  runSearch: "Run search",
  searching: "Searching...",
  searchValidation: "Enter at least 2 characters.",
  sourceOpen: "Open source",
  structuredFieldsTitle: "Structured fields",
  searchEmptyTitle: "No search results yet",
  searchEmptyMessage: "Run search to inspect places, opening hours, pricing hints, and coordinates.",
  placeNameLabel: "Place name",
  categoryLabel: "Category",
  openingHoursLabel: "Opening hours",
  priceHintLabel: "Price hint",
  addressLabel: "Address",
  geoLabel: "Geo",
  sourceTypeLabel: "Source type",
  platformLabel: "Platform",
  latitudeLabel: "Lat",
  longitudeLabel: "Lng",
  itemTypes: {
    sight: "Sight",
    meal: "Meal",
    explore: "Explore",
    transit: "Transit",
    hotel: "Stay",
    photo: "Photo"
  } as Record<string, string>,
  stageLabel: "Stage",
  progressLabel: "Progress",
  updatedLabel: "Updated",
  timelineTitle: "Timeline",
  timelineEmptyTitle: "Timeline waiting for updates",
  timelineEmptyMessage: "New stage updates will appear here as the current job progresses.",
  briefKicker: "Planning brief",
  briefTitle: "Trip input snapshot",
  briefDescription: "Review the structured brief the planner is working from before you refine again.",
  originLabel: "Departure",
  destinationLabel: "Destination",
  datesLabel: "Dates",
  budgetLabel: "Budget",
  travelersLabel: "Travelers",
  paceLabel: "Pace",
  transportLabel: "Transport",
  accommodationLabel: "Stay preference",
  interestsLabel: "Interests",
  noInterests: "No interests added yet.",
  overviewKicker: "Itinerary overview",
  totalDaysLabel: "Total days",
  totalStopsLabel: "Planned stops",
  averageDailyLabel: "Avg / day",
  riskCountLabel: "Risks",
  itineraryPanelTitle: "Generated plan",
  itineraryPanelDescription: "Daily cards are grouped by time, place, and activity type so the plan is easier to scan.",
  locationLabel: "Location",
  imagePendingLabel: "Images pending",
  imageFailedLabel: "Images unavailable",
  imageSkippedLabel: "No image needed",
  imageSourcesLabel: "Source",
  imagePriorityLabels: {
    high: "Hero stop",
    medium: "Visual stop",
    low: "Light visual",
    skipped: "Skipped"
  } as Record<string, string>,
  agentPipelineTitle: "Agent pipeline",
  agentPipelineDescription: "Review which agents actually ran, which third-party endpoint and model each role used, and what each role produced.",
  agentPromptLabel: "Prompt focus",
  agentOutputLabel: "Output",
  agentModelLabel: "Model",
  agentPromptVersionLabel: "Prompt version",
  agentCitationsLabel: "Citations",
  agentNotesLabel: "Trace notes",
  agentCompletedLabel: "Completed",
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
    "trip.image_enrich": "Image enrichment",
    "export.pdf": "Guide export"
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
  noActiveJobMessage: "生成与 refine 会直接由浏览器调用第三方模型，PDF 导出仍然走后端任务链路。",
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
  enrichImagesActionLabel: "重新补图",
  enrichImagesActionRunningLabel: "重新补图中...",
  refineValidation: "请输入至少 3 个字符。",
  searchPanelTitle: "搜索 Grounding",
  searchPanelMessage: "这些固定或结构化搜索结果来自你的后端，并会作为 prompt 的 grounding 输入。",
  queryLabel: "查询词",
  linksLabel: "手动链接",
  runSearch: "开始搜索",
  searching: "搜索中...",
  searchValidation: "请输入至少 2 个字符。",
  sourceOpen: "打开来源",
  structuredFieldsTitle: "结构化字段",
  searchEmptyTitle: "还没有搜索结果",
  searchEmptyMessage: "先执行一次搜索，再查看地点、营业时间、价格提示和坐标。",
  placeNameLabel: "地点名称",
  categoryLabel: "类别",
  openingHoursLabel: "营业时间",
  priceHintLabel: "价格提示",
  addressLabel: "地址",
  geoLabel: "坐标",
  sourceTypeLabel: "来源类型",
  platformLabel: "平台",
  latitudeLabel: "纬度",
  longitudeLabel: "经度",
  itemTypes: {
    sight: "景点",
    meal: "餐食",
    explore: "探索",
    transit: "交通",
    hotel: "住宿",
    photo: "拍照"
  } as Record<string, string>,
  stageLabel: "阶段",
  progressLabel: "进度",
  updatedLabel: "更新时间",
  timelineTitle: "时间线",
  timelineEmptyTitle: "时间线等待更新",
  timelineEmptyMessage: "当前任务推进时，新的阶段更新会显示在这里。",
  briefKicker: "规划 Brief",
  briefTitle: "行程输入快照",
  briefDescription: "在再次 refine 之前，先复核当前规划器使用的结构化输入。",
  destinationLabel: "目的地",
  datesLabel: "日期",
  budgetLabel: "预算",
  travelersLabel: "出行人数",
  paceLabel: "节奏",
  transportLabel: "交通方式",
  accommodationLabel: "住宿偏好",
  interestsLabel: "兴趣偏好",
  noInterests: "还没有填写兴趣偏好。",
  overviewKicker: "行程概览",
  totalDaysLabel: "总天数",
  totalStopsLabel: "计划点位",
  averageDailyLabel: "日均预算",
  riskCountLabel: "风险提示",
  itineraryPanelTitle: "已生成计划",
  itineraryPanelDescription: "按时间、地点和活动类型分组显示每日卡片，便于快速扫读。",
  locationLabel: "地点",
  agentPipelineTitle: "Agent pipeline",
  agentPipelineDescription: "查看最近一次实际运行的 agent、每个角色使用的第三方 endpoint 与 model，以及各自的输出。",
  agentPromptLabel: "提示词焦点",
  agentOutputLabel: "输出摘要",
  agentModelLabel: "模型",
  agentPromptVersionLabel: "提示词版本",
  agentCitationsLabel: "引用来源",
  agentNotesLabel: "Trace 备注",
  agentCompletedLabel: "已完成",
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
    "trip.image_enrich": "景点补图",
    "export.pdf": "PDF 导出"
  } as Record<string, string>,
  quickRefineActions: [
    { label: "压预算", instruction: "在保证整体可执行的前提下降低总预算。", scope: "budget" },
    { label: "减少路程", instruction: "减少长距离转场，让每天移动更轻松。", scope: "travel_flow" },
    { label: "更适合拍照", instruction: "优先安排更适合拍照的点位和更好的拍摄时段。", scope: "photo_spots" },
    { label: "增加深度体验", instruction: "增加更有在地感和文化深度的体验。", scope: "depth" }
  ]
}

const copy = computed<typeof enCopy>(() => (locale.value === "zh-CN" ? (zhCopy as typeof enCopy) : enCopy))
const exportActionLabel = computed(() => (locale.value === "zh-CN" ? "导出攻略包" : copy.value.exportActionLabel))
const exportActionRunningLabel = computed(() => (locale.value === "zh-CN" ? "导出攻略包中..." : copy.value.exportActionRunningLabel))
const tripId = computed(() => String(props.id ?? ""))
const routeJobId = computed(() => String(props.jobId ?? ""))
const hasItinerary = computed(() => Boolean(trip.value?.itinerary))
const isJobRunning = computed(() => activeJob.value?.status === "queued" || activeJob.value?.status === "running")
const actionLocked = computed(() => generatePending.value || refinePending.value || exportPending.value || deletePending.value || isJobRunning.value)
const imageEnrichInProgress = computed(() => activeJob.value?.type === "trip.image_enrich" && isJobRunning.value)
const canRetryImageEnrichment = computed(() => Boolean(hasItinerary.value && !imageEnrichPending.value && !imageEnrichInProgress.value))
const canUseBrowserModel = computed(() => settingsStore.loaded && settingsStore.isConfigured)
const canGenerate = computed(() => settingsStore.loaded && settingsStore.isConfigured)
const usesHelloAgents = computed(() => settingsStore.usesHelloAgents)
const communityPublication = computed(() => trip.value?.community_post ?? null)
const communityActionLocked = computed(() => actionLocked.value || communityPending.value)
const communityPreviewImage = computed(() => {
  if (!trip.value?.itinerary) {
    return null
  }
  for (const day of trip.value.itinerary.days) {
    for (const item of day.items) {
      const firstImage = item.image_urls?.find((url) => String(url || "").trim().length > 0)
      if (firstImage) {
        return firstImage
      }
    }
  }
  return null
})
const communityPreviewInterestTags = computed(() => (trip.value?.interests ?? []).slice(0, 4))
const communityPreviewDays = computed(() => trip.value?.itinerary?.days.length ?? 0)
const shouldLockNavigation = computed(() => {
  if (generatePending.value || refinePending.value) {
    return true
  }
  if (!activeJob.value) {
    return false
  }
  if (!["trip.generate", "trip.refine"].includes(activeJob.value.type)) {
    return false
  }
  return activeJob.value.status === "queued" || activeJob.value.status === "running"
})
const deleteTripLabel = computed(() => (locale.value === "zh-CN" ? "删除行程" : "Delete trip"))
const deletingTripLabel = computed(() => (locale.value === "zh-CN" ? "删除中..." : "Deleting..."))
const deleteTripConfirmMessage = computed(() =>
  locale.value === "zh-CN"
    ? "确认删除这条行程吗？该操作会同时移除关联任务记录。"
    : "Delete this trip? Related job records will be removed as well."
)
const deleteTripFailedTitle = computed(() => (locale.value === "zh-CN" ? "删除行程失败" : "Failed to delete trip"))
const communityCopy = computed(() =>
  locale.value === "zh-CN"
    ? {
        kicker: "攻略分享",
        title: "分享到社区",
        description: "把当前攻略发布到站内社区，供其他用户参考。",
        unpublishedTitle: "当前还没有社区帖子",
        unpublishedMessage: "这会发布当前攻略快照，后续你可以手动更新社区版本。",
        needsItineraryMessage: "请先生成攻略，再发布到社区。",
        publishedTitle: "当前攻略已发布到社区",
        publishedMessage: "社区里展示的是发布时的快照版本。",
        staleTitle: "社区版本待更新",
        staleMessage: "当前 Trip 已有新变化，社区帖子仍停留在旧快照。",
        publishAction: "分享到社区",
        publishingAction: "发布中...",
        viewAction: "查看帖子",
        refreshAction: "更新已发布内容",
        refreshingAction: "更新中...",
        editAction: "编辑心得",
        removeAction: "下架帖子",
        removingAction: "下架中...",
        noteLabel: "分享心得",
        notePlaceholder: "补充一句这份攻略适合谁、你最推荐哪段路线，或有哪些避坑提醒。",
        noteHint: "最多 280 字，其余标题、摘要、预算、行程会直接取自当前 Trip。",
        modalCreateTitle: "发布攻略到社区",
        modalEditTitle: "编辑社区心得",
        submitCreate: "确认发布",
        submitEdit: "保存心得",
        savingAction: "保存中...",
        cancelAction: "取消",
        publishSuccess: "攻略已发布到社区。",
        updateSuccess: "社区心得已更新。",
        refreshSuccess: "社区攻略已同步到最新 Trip 快照。",
        removeSuccess: "社区帖子已下架。",
        removeConfirm: "确认下架这篇社区帖子吗？",
        previewTitle: "发布预览",
        previewDays: "天数",
        previewBudget: "预算"
      }
    : {
        kicker: "Share",
        title: "Publish to community",
        description: "Publish the current guide to the in-product community so other users can reference it.",
        unpublishedTitle: "No community post yet",
        unpublishedMessage: "Publishing creates a snapshot of this guide. You can manually refresh the community version later.",
        needsItineraryMessage: "Generate the guide before publishing it to the community.",
        publishedTitle: "This guide is already published",
        publishedMessage: "The community page shows the snapshot version from the last publish or refresh.",
        staleTitle: "Community version needs refresh",
        staleMessage: "This Trip has changed since the last published snapshot.",
        publishAction: "Publish to community",
        publishingAction: "Publishing...",
        viewAction: "View post",
        refreshAction: "Refresh published version",
        refreshingAction: "Refreshing...",
        editAction: "Edit note",
        removeAction: "Remove post",
        removingAction: "Removing...",
        noteLabel: "Share note",
        notePlaceholder: "Add a short note about who this guide is for, what makes the route useful, or any watch-outs.",
        noteHint: "Up to 280 characters. The title, summary, budget, and itinerary come directly from this Trip.",
        modalCreateTitle: "Publish this guide",
        modalEditTitle: "Edit community note",
        submitCreate: "Publish guide",
        submitEdit: "Save note",
        savingAction: "Saving...",
        cancelAction: "Cancel",
        publishSuccess: "The guide is now live in the community feed.",
        updateSuccess: "The community note has been updated.",
        refreshSuccess: "The published guide now matches the latest Trip snapshot.",
        removeSuccess: "The community post has been removed.",
        removeConfirm: "Remove this post from the community feed?",
        previewTitle: "Publish preview",
        previewDays: "Days",
        previewBudget: "Budget"
      }
)
const jobTimeline = computed<JobTimelineEntry[]>(() => (Array.isArray(activeJob.value?.timeline_json) ? activeJob.value.timeline_json : []))
const jobProgress = computed(() => clampProgress(activeJob.value?.progress_percent, activeJob.value?.status))
const tripInterests = computed(() => trip.value?.interests ?? [])
const latestTrace = computed(() => trip.value?.latest_agent_trace ?? null)
const agentRuns = computed<AgentRunStep[]>(() => (Array.isArray(latestTrace.value?.agent_runs) ? latestTrace.value?.agent_runs ?? [] : []))
const groundingDocuments = computed<SearchDocument[]>(() => {
  const raw = latestTrace.value?.grounding_documents
  return Array.isArray(raw) ? raw : []
})
const citedGroundingDocumentKeys = computed(() => {
  const keys = new Set<string>()
  for (const agent of agentRuns.value) {
    for (const citation of agentCitationUrls(agent)) {
      const key = normalizeCitationKey(citation)
      if (key) {
        keys.add(key)
      }
    }
  }
  return keys
})
const groundingDocumentsByCitationKey = computed(() => {
  const entries: Array<[string, SearchDocument]> = []
  for (const doc of groundingDocuments.value) {
    const key = normalizeCitationKey(doc.url)
    if (key) {
      entries.push([key, doc])
    }
  }
  return new Map(entries)
})
const citedXhsVisualDocs = computed<SearchDocument[]>(() => {
  return groundingDocuments.value.filter((doc) => {
    const key = normalizeCitationKey(doc.url)
    return (
      doc.platform === "xiaohongshu" &&
      Array.isArray(doc.image_urls) &&
      doc.image_urls.length > 0 &&
      Boolean(key && citedGroundingDocumentKeys.value.has(key))
    )
  })
})
const groundingReferenceDocs = computed<SearchDocument[]>(() => {
  const docs = (citedGroundingDocumentKeys.value.size > 0
    ? groundingDocuments.value.filter((doc) => {
        const key = normalizeCitationKey(doc.url)
        return Boolean(key && citedGroundingDocumentKeys.value.has(key))
      })
    : groundingDocuments.value
  ).slice()
  docs.sort((left, right) => {
    const leftKey = normalizeCitationKey(left.url)
    const rightKey = normalizeCitationKey(right.url)
    const leftCited = Boolean(leftKey && citedGroundingDocumentKeys.value.has(leftKey))
    const rightCited = Boolean(rightKey && citedGroundingDocumentKeys.value.has(rightKey))
    if (leftCited !== rightCited) {
      return leftCited ? -1 : 1
    }
    if (left.platform !== right.platform) {
      return left.platform.localeCompare(right.platform)
    }
    return left.title.localeCompare(right.title)
  })
  return docs
})
const hasPendingItemImages = computed(() =>
  Boolean(
    trip.value?.itinerary?.days?.some((day) =>
      day.items.some((item) => item.image_status === "pending")
    )
  )
)
const imageEnrichmentCounts = computed(() => {
  const counts = { pending: 0, completed: 0, failed: 0, skipped: 0 }
  for (const day of trip.value?.itinerary?.days ?? []) {
    for (const item of day.items) {
      switch (item.image_status) {
        case "pending":
          counts.pending += 1
          break
        case "completed":
          counts.completed += 1
          break
        case "failed":
          counts.failed += 1
          break
        case "skipped":
          counts.skipped += 1
          break
        default:
          break
      }
    }
  }
  return counts
})
const imageJobBackendHint = computed(() => {
  if (activeJob.value?.type !== "trip.image_enrich") {
    return null
  }
  return locale.value === "zh-CN"
    ? "景点补图在后端任务里执行，浏览器 Network 通常只会看到 /api/v1/jobs 和 /api/v1/trips 轮询，不会直接看到 Tavily 出站请求。"
    : "Image enrichment runs inside a backend job. In the browser Network tab you will usually only see /api/v1/jobs and /api/v1/trips polling, not the outbound Tavily request itself."
})
const imageEnrichmentStatusSummary = computed(() => {
  if (activeJob.value?.type !== "trip.image_enrich") {
    return null
  }
  const raw = activeJob.value.result?.image_enrichment_summary
  const counts = typeof raw === "object" && raw !== null
    ? {
        completed: Number((raw as Record<string, unknown>).completed ?? 0),
        pending: Number((raw as Record<string, unknown>).pending ?? 0),
        failed: Number((raw as Record<string, unknown>).failed ?? 0),
        skipped: Number((raw as Record<string, unknown>).skipped ?? 0)
      }
    : imageEnrichmentCounts.value
  return locale.value === "zh-CN"
    ? `补图状态：完成 ${counts.completed}，进行中 ${counts.pending}，失败 ${counts.failed}，跳过 ${counts.skipped}。`
    : `Image status: ${counts.completed} completed, ${counts.pending} pending, ${counts.failed} failed, ${counts.skipped} skipped.`
})
const imageEnrichmentDebugRows = computed<ImageEnrichmentDebugRow[]>(() => {
  if (activeJob.value?.type !== "trip.image_enrich") {
    return []
  }
  const raw = activeJob.value.result?.image_enrichment_debug
  if (!Array.isArray(raw)) {
    return []
  }
  return raw
    .filter((entry): entry is Record<string, unknown> => typeof entry === "object" && entry !== null)
    .map((entry) => ({
      item_id: String(entry.item_id ?? ""),
      name: String(entry.name ?? ""),
      status: String(entry.status ?? ""),
      priority_tier: entry.priority_tier == null ? null : String(entry.priority_tier),
      failure_reason: entry.failure_reason == null ? null : String(entry.failure_reason),
      image_count: typeof entry.image_count === "number" ? entry.image_count : Number(entry.image_count ?? 0),
      source_count: typeof entry.source_count === "number" ? entry.source_count : Number(entry.source_count ?? 0)
    }))
})
const imageSpecialistRun = computed<AgentRunStep | null>(() => agentRuns.value.find((run) => run.key === "attraction_image_specialist") ?? null)
const imageReviewerRun = computed<AgentRunStep | null>(() => agentRuns.value.find((run) => run.key === "image_reviewer") ?? null)
const imageQueryNotes = computed(() => (imageSpecialistRun.value?.notes ?? []).filter((note) => note.startsWith("Image query [")))
const imageCandidateDebugNotes = computed(() => (imageSpecialistRun.value?.notes ?? []).filter((note) => note.startsWith("Image debug [")))
const imageReviewerDebugNotes = computed(() =>
  (imageReviewerRun.value?.notes ?? []).filter((note) => note.startsWith("Review modes:") || note.startsWith("Rejected ") || note.includes(": "))
)
const imageDebugTitle = computed(() => (locale.value === "zh-CN" ? "补图调试" : "Image debug"))
const imageDebugSummaryTitle = computed(() => (locale.value === "zh-CN" ? "补图结果摘要" : "Image result summary"))
const imageDebugQueriesTitle = computed(() => (locale.value === "zh-CN" ? "实际检索词" : "Search queries"))
const imageDebugCandidatesTitle = computed(() => (locale.value === "zh-CN" ? "候选图摘要" : "Candidate debug"))
const imageDebugReviewerTitle = computed(() => (locale.value === "zh-CN" ? "审图结论" : "Reviewer decisions"))
const imageDebugEmptyMessage = computed(() => (locale.value === "zh-CN" ? "当前补图任务还没有可展示的调试信息。" : "No image-enrichment debug details are available yet."))
const actualExecutionKind = computed<"info" | "error">(() => (activeJob.value?.status === "failed" ? "error" : "info"))
const currentModeTitle = computed(() => {
  if (activeJob.value?.status === "failed") {
    return locale.value === "zh-CN" ? "最近一次执行失败" : "Latest execution failed"
  }

  switch (latestTrace.value?.provider) {
    case "helloagents-poc":
      return locale.value === "zh-CN" ? "最近一次实际执行：HelloAgents 多 Agent 工作流" : "Latest execution: HelloAgents multi-agent workflow"
    case "openai-compatible-relay":
      return locale.value === "zh-CN" ? "最近一次实际执行：浏览器 relay" : "Latest execution: Browser relay"
    case "openai-compatible":
      return locale.value === "zh-CN" ? "最近一次实际执行：后端单模型编排" : "Latest execution: Backend single-model orchestration"
    case "stub":
      return locale.value === "zh-CN" ? "最近一次实际执行：本地 stub" : "Latest execution: Local stub"
    default:
      return locale.value === "zh-CN" ? "尚无实际执行记录" : "No execution trace yet"
  }
})
const currentModeMessage = computed(() => {
  if (activeJob.value?.status === "failed") {
    return activeJob.value.error_message?.trim() || activeJob.value.stage_message?.trim() || (locale.value === "zh-CN" ? "最近一次任务执行失败。" : "The latest job failed.")
  }

  if (!latestTrace.value) {
    return usesHelloAgents.value
      ? locale.value === "zh-CN"
        ? "当前配置为 HelloAgents，但这条行程还没有成功执行记录。完成一次生成后，这里会显示每个 agent 实际调用的 endpoint、model 和状态。"
        : "HelloAgents is configured, but this trip does not have a successful execution trace yet. After the next generation run, this panel will show the real endpoint, model, and status used by each agent."
      : locale.value === "zh-CN"
        ? "这条行程还没有成功执行记录。完成一次生成或 refine 后，这里会显示最近一次实际执行结果。"
        : "This trip does not have a successful execution trace yet. After the next generation or refine run, this panel will show the latest actual execution result."
  }

  if (latestTrace.value.provider === "helloagents-poc") {
    return agentRuns.value.length > 0
      ? locale.value === "zh-CN"
        ? `最近一次成功执行来自后端 HelloAgents 工作流，已记录 ${agentRuns.value.length} 个 agent 的实际 endpoint、model 与状态。`
        : `The latest successful run came from the backend HelloAgents workflow, with ${agentRuns.value.length} recorded agents including their real endpoints, models, and statuses.`
      : locale.value === "zh-CN"
        ? "最近一次成功执行来自后端 HelloAgents 工作流，但当前 trace 没有逐 agent 明细。"
        : "The latest successful run came from the backend HelloAgents workflow, but this trace did not persist per-agent details."
  }

  if (latestTrace.value.provider === "openai-compatible-relay") {
    return locale.value === "zh-CN"
      ? "最近一次成功执行来自浏览器侧 relay，通过后端 /api/v1/llm/proxy 调用第三方模型。"
      : "The latest successful run used the browser-side relay, calling the third-party model through /api/v1/llm/proxy."
  }

  if (latestTrace.value.provider === "stub") {
    return locale.value === "zh-CN"
      ? "最近一次成功结果来自本地 stub，不是第三方真实执行。"
      : "The latest successful result came from the local stub, not from a real third-party execution."
  }

  return locale.value === "zh-CN"
    ? `最近一次成功执行记录的 provider 为 ${formatTraceProvider(latestTrace.value.provider)}。`
    : `The latest successful run recorded provider ${formatTraceProvider(latestTrace.value.provider)}.`
})
const noActiveJobMessage = computed(() => {
  if (usesHelloAgents.value) {
    return locale.value === "zh-CN"
      ? "当前没有进行中的任务。完成一次生成后，下方会显示最近一次实际 HelloAgents agent 执行明细。"
      : "No active job is running. After the next generation run, the latest real HelloAgents agent execution details will appear below."
  }
  return locale.value === "zh-CN"
    ? "当前没有进行中的任务。完成一次生成或 refine 后，下方会显示最近一次实际执行结果。"
    : "No active job is running. After the next generation or refine run, the latest actual execution result will appear below."
})
const executionMetrics = computed(() => {
  if (!latestTrace.value) {
    return []
  }

  return [
    { label: locale.value === "zh-CN" ? "实际 Provider" : "Actual provider", value: formatTraceProvider(latestTrace.value.provider) },
    { label: locale.value === "zh-CN" ? "工作流 ID" : "Workflow ID", value: latestTrace.value.workflow_id },
    { label: locale.value === "zh-CN" ? "记录的 Agent" : "Recorded agents", value: String(agentRuns.value.length) },
    { label: locale.value === "zh-CN" ? "最近结果" : "Latest outcome", value: locale.value === "zh-CN" ? "已完成" : "Completed" }
  ]
})
const latestSuccessfulExecutionKicker = computed(() => (locale.value === "zh-CN" ? "最近一次成功执行" : "Latest successful execution"))
const latestSuccessfulExecutionDescription = computed(() =>
  agentRuns.value.length > 0
    ? locale.value === "zh-CN"
      ? "以下卡片展示最近一次成功执行中，每个 agent 实际使用的 endpoint、model 和状态。"
      : "The cards below show the actual endpoint, model, and status used by each agent in the latest successful run."
    : locale.value === "zh-CN"
      ? "这里只展示最近一次成功执行回写的 trace 记录。"
      : "This section shows the trace persisted from the latest successful execution."
)
const quickRefineActions = computed(() => copy.value.quickRefineActions)
const budgetPanelTitle = computed(() => (locale.value === "zh-CN" ? "精准预算明细面板" : "Precise budget panel"))
const budgetPanelDescription = computed(() =>
  locale.value === "zh-CN"
    ? "汇总门票、餐饮、住宿、交通与其他成本，让你更直观看清预算占用与剩余空间。"
    : "Summarize tickets, dining, accommodation, transport, and other costs so the trip budget stays visible and controllable."
)
const budgetLineItemsTitle = computed(() => (locale.value === "zh-CN" ? "预算明细" : "Budget line items"))
const budgetStatusLabels = computed(() =>
  locale.value === "zh-CN"
    ? { under: "预算健康", near: "接近上限", over: "超出预算" }
    : { under: "On track", near: "Near limit", over: "Over budget" }
)
const budgetCategoryLabels = computed(() =>
  locale.value === "zh-CN"
    ? { tickets: "门票", dining: "餐饮", accommodation: "住宿", transport: "交通", other: "其他" }
    : { tickets: "Tickets", dining: "Dining", accommodation: "Accommodation", transport: "Transport", other: "Other" }
)
const budgetSummary = computed(() => {
  if (!trip.value?.itinerary) {
    return null
  }
  return enrichGeneratedItineraryWithBudget(trip.value, trip.value.itinerary).budget_summary ?? trip.value.itinerary.budget_summary ?? null
})
const budgetMetrics = computed(() => {
  if (!budgetSummary.value) {
    return []
  }

  return [
    { label: locale.value === "zh-CN" ? "预算上限" : "Budget cap", value: formatCurrency(budgetSummary.value.requested_budget) },
    { label: locale.value === "zh-CN" ? "预计总花费" : "Estimated total", value: formatCurrency(budgetSummary.value.estimated_total) },
    {
      label: budgetSummary.value.over_budget > 0 ? (locale.value === "zh-CN" ? "超支" : "Over budget") : (locale.value === "zh-CN" ? "剩余预算" : "Remaining"),
      value: formatCurrency(budgetSummary.value.over_budget > 0 ? budgetSummary.value.over_budget : budgetSummary.value.remaining_budget)
    },
    { label: locale.value === "zh-CN" ? "预算状态" : "Budget status", value: budgetStatusLabels.value[budgetSummary.value.status] ?? budgetSummary.value.status }
  ]
})
const budgetBreakdownCards = computed(() => {
  if (!budgetSummary.value) {
    return []
  }

  return [
    { key: "tickets", label: budgetCategoryLabels.value.tickets, value: formatCurrency(budgetSummary.value.breakdown.tickets) },
    { key: "dining", label: budgetCategoryLabels.value.dining, value: formatCurrency(budgetSummary.value.breakdown.dining) },
    { key: "accommodation", label: budgetCategoryLabels.value.accommodation, value: formatCurrency(budgetSummary.value.breakdown.accommodation) },
    { key: "transport", label: budgetCategoryLabels.value.transport, value: formatCurrency(budgetSummary.value.breakdown.transport) },
    { key: "other", label: budgetCategoryLabels.value.other, value: formatCurrency(budgetSummary.value.breakdown.other) }
  ]
})
const budgetLineItems = computed(() => budgetSummary.value?.line_items ?? [])
const bookingPanelTitle = computed(() => (locale.value === "zh-CN" ? "预订与预约" : "Booking and reservations"))
const bookingPanelDescription = computed(() =>
  locale.value === "zh-CN"
    ? "把交通预订、景点门票、预约要求和提醒整理成可执行清单，避免临近出发时再补信息。"
    : "Turn transport booking, attraction tickets, reservation rules, and reminders into a practical checklist."
)
const transportBookingTitle = computed(() => (locale.value === "zh-CN" ? "交通预订摘要" : "Transport booking summary"))
const reservationChecklistTitle = computed(() => (locale.value === "zh-CN" ? "景点预约清单" : "Attraction booking checklist"))
const transportBookingSummary = computed<TransportBookingSummary | null>(() => {
  if (trip.value?.itinerary?.transport_booking_summary) {
    return trip.value.itinerary.transport_booking_summary
  }
  return coerceTransportBookingSummary((latestTrace.value?.transport_guidance as Record<string, unknown> | null | undefined) ?? null)
})
const transportBookingFields = computed(() => {
  const summary = transportBookingSummary.value
  if (!summary) {
    return []
  }
  return [
    { label: locale.value === "zh-CN" ? "推荐方案" : "Recommended option", value: fieldValue(summary.recommended_option) },
    { label: locale.value === "zh-CN" ? "跨城交通估算" : "Intercity estimate", value: formatCurrency(summary.estimated_intercity_cost) },
    { label: locale.value === "zh-CN" ? "本地交通估算" : "Local transport estimate", value: formatCurrency(summary.estimated_local_transport_cost) },
    { label: locale.value === "zh-CN" ? "预订窗口" : "Booking window", value: fieldValue(summary.booking_window) },
    {
      label: locale.value === "zh-CN" ? "提前预订" : "Advance booking",
      value: summary.booking_required ? (locale.value === "zh-CN" ? "建议提前预订" : "Recommended") : (locale.value === "zh-CN" ? "按需" : "As needed")
    }
  ]
})
const transportBookingHighlights = computed(() => {
  const summary = transportBookingSummary.value
  if (!summary) {
    return []
  }
  const prioritized = [
    ...(summary.reminders ?? []).slice(0, 2),
    ...(summary.pass_or_ticket_notes ?? []).slice(0, 1),
    ...(summary.notes ?? []).slice(0, 1)
  ]
  const seen = new Set<string>()
  return prioritized.filter((note) => {
    const normalized = note.trim()
    if (!normalized || seen.has(normalized)) {
      return false
    }
    seen.add(normalized)
    return true
  })
})
const reservationEntries = computed(() => {
  if (!trip.value?.itinerary) {
    return []
  }
  return trip.value.itinerary.days.flatMap((day) =>
    day.items
      .map((item) => {
        if (!shouldShowReservationEntry(item)) {
          return null
        }
        const lines = itemBookingLines(item)
        if (lines.length === 0) {
          return null
        }
        return {
          key: `${day.day_index}-${item.id}`,
          title: `${locale.value === "zh-CN" ? `第 ${day.day_index} 天` : `Day ${day.day_index}`} · ${item.name}`,
          lines,
          officialUrl: item.booking_info?.official_booking_url ?? null
        }
      })
      .filter((entry): entry is { key: string; title: string; lines: string[]; officialUrl: string | null } => entry !== null)
  )
})
const itineraryMetrics = computed(() => {
  const itinerary = trip.value?.itinerary
  const totalDays = itinerary?.days.length ?? estimateTripDays(trip.value?.start_date, trip.value?.end_date)
  const totalStops = itinerary?.days.reduce((sum, day) => sum + day.items.length, 0) ?? 0
  const averageDailyBudget = totalDays > 0 ? (trip.value?.budget ?? 0) / totalDays : 0
  const riskCount = itinerary?.risks.length ?? 0

  return [
    { label: copy.value.totalDaysLabel, value: String(totalDays) },
    { label: copy.value.totalStopsLabel, value: String(totalStops) },
    { label: copy.value.averageDailyLabel, value: formatCurrency(averageDailyBudget) },
    { label: copy.value.riskCountLabel, value: String(riskCount) }
  ]
})
const planningBriefFields = computed(() => {
  if (!trip.value) {
    return []
  }

  return [
    { label: copy.value.originLabel, value: trip.value.origin },
    { label: copy.value.destinationLabel, value: trip.value.destination },
    { label: copy.value.datesLabel, value: formatDateRange(trip.value.start_date, trip.value.end_date) },
    { label: copy.value.budgetLabel, value: formatCurrency(trip.value.budget) },
    { label: copy.value.travelersLabel, value: t("common.travelersCount", { count: trip.value.travelers }) },
    { label: copy.value.paceLabel, value: paceLabel(trip.value.pace) },
    { label: copy.value.transportLabel, value: transportLabel(trip.value.transport_mode) },
    { label: copy.value.accommodationLabel, value: fieldValue(trip.value.accommodation_preference) }
  ]
})

function estimateTripDays(start?: string, end?: string): number {
  if (!start || !end) {
    return 0
  }

  const startDate = new Date(start)
  const endDate = new Date(end)
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) {
    return 0
  }

  return Math.max(1, Math.round((endDate.getTime() - startDate.getTime()) / 86400000) + 1)
}

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

function coerceTransportBookingSummary(raw: Record<string, unknown> | null | undefined): TransportBookingSummary | null {
  if (!raw || typeof raw !== "object") {
    return null
  }
  const estimatedIntercityCost = Number(raw.estimated_intercity_cost ?? 0)
  const estimatedLocalTransportCost = Number(raw.estimated_local_transport_cost ?? 0)
  const summary: TransportBookingSummary = {
    summary: typeof raw.summary === "string" ? raw.summary : null,
    recommended_option: typeof raw.recommended_option === "string" ? raw.recommended_option : null,
    estimated_intercity_cost: Number.isFinite(estimatedIntercityCost) ? estimatedIntercityCost : 0,
    estimated_local_transport_cost: Number.isFinite(estimatedLocalTransportCost) ? estimatedLocalTransportCost : 0,
    booking_required: Boolean(raw.booking_required),
    official_booking_url: typeof raw.official_booking_url === "string" ? raw.official_booking_url : null,
    booking_window: typeof raw.booking_window === "string" ? raw.booking_window : null,
    pass_or_ticket_notes: Array.isArray(raw.pass_or_ticket_notes) ? raw.pass_or_ticket_notes.filter((item): item is string => typeof item === "string") : [],
    reminders: Array.isArray(raw.reminders) ? raw.reminders.filter((item): item is string => typeof item === "string") : [],
    notes: Array.isArray(raw.notes) ? raw.notes.filter((item): item is string => typeof item === "string") : [],
    source_urls: Array.isArray(raw.source_urls) ? raw.source_urls.filter((item): item is string => typeof item === "string") : []
  }
  const hasAnyTransportBookingSignal =
    Boolean(summary.summary) ||
    Boolean(summary.recommended_option) ||
    summary.estimated_intercity_cost > 0 ||
    summary.estimated_local_transport_cost > 0 ||
    Boolean(summary.booking_required) ||
    Boolean(summary.official_booking_url) ||
    Boolean(summary.booking_window) ||
    (summary.pass_or_ticket_notes?.length ?? 0) > 0 ||
    (summary.reminders?.length ?? 0) > 0 ||
    (summary.notes?.length ?? 0) > 0 ||
    (summary.source_urls?.length ?? 0) > 0
  return hasAnyTransportBookingSignal ? summary : null
}

function paceLabel(value: string): string {
  const key = `common.pace.${value}`
  const translated = t(key)
  return translated === key ? value : translated
}

function transportLabel(value: string): string {
  const key = `common.transport.${value}`
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
  if (value === "trip.generate") {
    return locale.value === "zh-CN" ? "生成行程" : "Itinerary generation"
  }
  return copy.value.jobTypes[value] ?? value
}

function formatItemType(value?: string | null): string {
  if (!value) {
    return copy.value.notAvailable
  }
  return copy.value.itemTypes[value] ?? value
}

function formatScore(value?: number | null): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return copy.value.notAvailable
  }

  if (value <= 1) {
    return `${Math.round(value * 100)}%`
  }

  return `${Math.round(value)}`
}

function formatAgentRunStatus(value?: string | null): string {
  if ((value ?? "completed") === "completed") {
    return copy.value.agentCompletedLabel
  }
  return value?.trim() || copy.value.notAvailable
}

function formatImagePriorityTier(value?: string | null): string | null {
  if (!value) {
    return null
  }
  return copy.value.imagePriorityLabels?.[value] ?? value
}

function formatImageStatus(value?: string | null): string | null {
  switch ((value ?? "").trim()) {
    case "pending":
      return copy.value.imagePendingLabel ?? "Images pending"
    case "failed":
      return copy.value.imageFailedLabel ?? "Images unavailable"
    case "skipped":
      return copy.value.imageSkippedLabel ?? "No image needed"
    default:
      return null
  }
}

function extractAgentNote(agent: AgentRunStep, prefix: string): string | null {
  const note = agent.notes?.find((entry) => entry.startsWith(prefix))
  if (!note) {
    return null
  }
  return note.slice(prefix.length).trim().replace(/\.$/, "")
}

function agentEndpoint(agent: AgentRunStep): string | null {
  return extractAgentNote(agent, "Third-party endpoint:")
}

function agentWireApi(agent: AgentRunStep): string | null {
  return extractAgentNote(agent, "Wire API:")
}

function extractCitationUrl(value: string): string | null {
  const match = value.trim().match(/https?:\/\/[^\s<>'"\]\[)]+/i)
  if (!match) {
    return null
  }
  return match[0].replace(/[),.;]+$/, "")
}

function normalizeCitationKey(value: string): string | null {
  const extracted = extractCitationUrl(value)
  if (!extracted) {
    return null
  }
  try {
    const parsed = new URL(extracted)
    const pathname = parsed.pathname.replace(/\/+$/, "") || "/"
    return `${parsed.protocol}//${parsed.host}${pathname}${parsed.search}${parsed.hash}`
  } catch {
    return extracted.replace(/\/+$/, "")
  }
}

function formatCitationLabel(url: string, doc?: SearchDocument): string {
  if (doc) {
    return doc.place_name || doc.title
  }
  try {
    const parsed = new URL(url)
    const path = parsed.pathname.replace(/\/+$/, "")
    const compactPath = path && path !== "/" ? path : ""
    return `${parsed.host}${compactPath}`
  } catch {
    return url
  }
}

function agentCitationUrls(agent: AgentRunStep): string[] {
  const direct = Array.isArray(agent.citations) ? agent.citations : []
  const legacy = (agent.notes ?? [])
    .filter((entry) => entry.startsWith("Weather citation:") || entry.startsWith("天气引用:"))
    .map((entry) => entry.split(":").slice(1).join(":").trim())

  const normalized: string[] = []
  const seen = new Set<string>()
  for (const entry of [...direct, ...legacy]) {
    const url = extractCitationUrl(entry)
    const key = normalizeCitationKey(entry)
    if (!url || !key || seen.has(key)) {
      continue
    }
    seen.add(key)
    normalized.push(url)
  }
  return normalized
}

function agentDisplayCitations(agent: AgentRunStep): Array<{ href: string; label: string }> {
  const grounded: Array<{ href: string; label: string }> = []
  const fallback: Array<{ href: string; label: string }> = []
  for (const url of agentCitationUrls(agent)) {
    const key = normalizeCitationKey(url)
    const doc = key ? groundingDocumentsByCitationKey.value.get(key) : undefined
    const item = {
      href: url,
      label: formatCitationLabel(url, doc),
    }
    if (doc) {
      grounded.push(item)
      continue
    }
    fallback.push(item)
  }
  if (grounded.length >= 3) {
    return grounded.slice(0, 3)
  }
  return [...grounded, ...fallback.slice(0, Math.max(0, 3 - grounded.length))]
}

function agentVisibleNotes(agent: AgentRunStep): string[] {
  return (agent.notes ?? []).filter((entry) => !(entry.startsWith("Weather citation:") || entry.startsWith("天气引用:")))
}

function formatTraceProvider(value?: string | null): string {
  switch ((value ?? "").trim()) {
    case "helloagents-poc":
      return locale.value === "zh-CN" ? "HelloAgents 后端工作流" : "HelloAgents backend workflow"
    case "openai-compatible-relay":
      return locale.value === "zh-CN" ? "浏览器 relay（经由后端代理）" : "Browser relay via backend proxy"
    case "openai-compatible":
      return locale.value === "zh-CN" ? "后端单模型编排" : "Backend single-model orchestration"
    case "stub":
      return locale.value === "zh-CN" ? "本地 stub" : "Local stub"
    default:
      return fieldValue(value)
  }
}

function formatBudgetLineItemTitle(title: string, note?: string | null): string {
  if (!note?.trim()) {
    return title
  }
  return `${title} 路 ${note}`
}

function itemBookingLines(item: ItineraryItem): string[] {
  if (!shouldShowReservationEntry(item)) {
    return []
  }
  const lines: string[] = []
  if (item.booking_info?.price_label) {
    lines.push(`${locale.value === "zh-CN" ? "票价" : "Ticket"}: ${item.booking_info.price_label}`)
  }
  if (typeof item.booking_info?.estimated_price === "number" && item.booking_info.estimated_price > 0) {
    lines.push(`${locale.value === "zh-CN" ? "预算计入" : "Budgeted"}: ${formatCurrency(item.booking_info.estimated_price)}`)
  }
  if (item.booking_info?.booking_window) {
    lines.push(`${locale.value === "zh-CN" ? "预订窗口" : "Booking window"}: ${item.booking_info.booking_window}`)
  }
  if (item.visit_requirements?.reservation_policy && item.visit_requirements.reservation_policy !== "not_needed") {
    lines.push(`${locale.value === "zh-CN" ? "预约要求" : "Reservation policy"}: ${item.visit_requirements.reservation_policy}`)
  }
  if (item.visit_requirements?.advance_booking_note) {
    lines.push(`${locale.value === "zh-CN" ? "预约提醒" : "Advance booking"}: ${item.visit_requirements.advance_booking_note}`)
  }
  if (item.visit_requirements?.timed_entry) {
    lines.push(locale.value === "zh-CN" ? "包含分时入场要求" : "Timed entry applies")
  }
  if (item.visit_requirements?.identity_required) {
    lines.push(locale.value === "zh-CN" ? "可能需要实名或证件校验" : "Identity or name check may apply")
  }
  const reminder = item.booking_info?.reminder?.trim()
  if (reminder) {
    lines.push(reminder)
  }
  return Array.from(new Set(lines))
}

function shouldShowReservationEntry(item: ItineraryItem): boolean {
  const itemType = (item.type ?? "").trim().toLowerCase()
  if (!["sight", "photo", "explore"].includes(itemType)) {
    return false
  }
  const bookingInfo = item.booking_info
  const requirements = item.visit_requirements
  return Boolean(
    bookingInfo?.official_booking_url ||
      bookingInfo?.booking_required ||
      bookingInfo?.reservation_required ||
      bookingInfo?.booking_window ||
      bookingInfo?.reminder ||
      (typeof bookingInfo?.estimated_price === "number" && bookingInfo.estimated_price > 0) ||
      (requirements?.reservation_policy && requirements.reservation_policy !== "not_needed") ||
      requirements?.advance_booking_note ||
      requirements?.timed_entry ||
      requirements?.identity_required
  )
}

function formatGeo(doc: SearchDocument): string {
  if (!doc.geo) {
    return copy.value.notAvailable
  }
  return `${copy.value.latitudeLabel} ${doc.geo.lat}, ${copy.value.longitudeLabel} ${doc.geo.lng}`
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

function schedulePendingImageRefresh() {
  if (timer !== null || activeJob.value || !hasPendingItemImages.value) {
    return
  }
  timer = window.setTimeout(() => {
    timer = null
    void (async () => {
      await loadTrip(false)
      schedulePendingImageRefresh()
    })()
  }, JOB_POLL_INTERVAL_MS)
}

function stopPolling() {
  if (timer !== null) {
    window.clearTimeout(timer)
    timer = null
  }
}

function handleBeforeUnload(event: BeforeUnloadEvent) {
  if (!shouldLockNavigation.value) {
    return
  }
  event.preventDefault()
  event.returnValue = ""
}

async function pollJob(jobId: string, kind: "generate" | "export" | "image_enrich") {
  stopPolling()

  try {
    activeJob.value = await api.getJob(jobId)
    if (activeJob.value.status === "completed" || activeJob.value.status === "failed") {
      await loadTrip(false)
      if (kind === "generate" && activeJob.value.status === "completed") {
        const followupJobId = String(activeJob.value.result?.followup_job_id ?? "").trim()
        if (followupJobId) {
          await pollJob(followupJobId, "image_enrich")
          return
        }
      }
      if (activeJob.value.status === "failed") {
        const message =
          activeJob.value.error_message?.trim()
          || (kind === "generate"
            ? t("tripDetail.generationFailedTitle")
            : kind === "image_enrich"
              ? (locale.value === "zh-CN" ? "景点补图失败" : "Image enrichment failed")
              : t("tripDetail.exportFailedTitle"))
        if (kind === "generate") {
          generateError.value = message
        } else if (kind === "image_enrich") {
          imageEnrichError.value = message
        } else if (kind === "export") {
          exportError.value = message
        }
      }
      if (kind !== "export") {
        schedulePendingImageRefresh()
      }
      return
    }
    timer = window.setTimeout(() => {
      void pollJob(jobId, kind)
    }, JOB_POLL_INTERVAL_MS)
  } catch (value) {
    const message = getErrorMessage(
      value,
      kind === "generate"
        ? t("tripDetail.generationFailedTitle")
        : kind === "image_enrich"
          ? (locale.value === "zh-CN" ? "无法执行景点补图" : "Unable to run image enrichment")
          : t("tripDetail.exportFailedTitle")
    )
    if (kind === "generate") {
      generateError.value = message
    } else if (kind === "image_enrich") {
      imageEnrichError.value = message
    } else {
      exportError.value = message
    }
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

    if (usesHelloAgents.value) {
      const job = await api.generateTrip(tripId.value)
      activeJob.value = job
      await pollJob(job.job_id, "generate")
      return
    }

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
    if (activeJob.value?.type === "trip.generate" && activeJob.value.job_id.startsWith("browser:")) {
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
    const job = await api.exportTrip({ trip_id: tripId.value, formats: ["md", "pdf", "json"] })
    activeJob.value = job
    await router.push({ name: "export-detail", params: { id: job.job_id } })
  } catch (value) {
    exportError.value = getErrorMessage(value, t("tripDetail.exportFailedTitle"))
  } finally {
    exportPending.value = false
  }
}

async function retryImageEnrichment() {
  if (!trip.value?.itinerary) {
    imageEnrichError.value = locale.value === "zh-CN" ? "请先生成行程，再执行景点补图。" : "Generate the itinerary before retrying image enrichment."
    return
  }

  imageEnrichPending.value = true
  imageEnrichError.value = null
  try {
    const job = await api.enrichTripImages(tripId.value)
    activeJob.value = job
    await pollJob(job.job_id, "image_enrich")
  } catch (value) {
    imageEnrichError.value = getErrorMessage(value, locale.value === "zh-CN" ? "无法重新执行景点补图" : "Unable to retry image enrichment")
  } finally {
    imageEnrichPending.value = false
  }
}

async function removeTrip() {
  if (!trip.value || deletePending.value || !window.confirm(deleteTripConfirmMessage.value)) {
    return
  }

  deletePending.value = true
  deleteError.value = null
  try {
    await api.deleteTrip(tripId.value)
    stopPolling()
    await router.push({ name: "trips" })
  } catch (value) {
    deleteError.value = getErrorMessage(value, deleteTripFailedTitle.value)
  } finally {
    deletePending.value = false
  }
}

async function openCommunityEditor(mode: "create" | "edit") {
  if (!trip.value) {
    return
  }

  communityEditorMode.value = mode
  communityError.value = null
  communityNotice.value = null

  if (mode === "create") {
    communityNoteDraft.value = ""
    communityEditorOpen.value = true
    return
  }

  const postId = communityPublication.value?.post_id
  if (!postId) {
    return
  }

  communityPending.value = true
  try {
    const detail = await api.getCommunityPost(postId)
    communityNoteDraft.value = detail.share_note ?? ""
    communityEditorOpen.value = true
  } catch (value) {
    communityError.value = getErrorMessage(value, communityCopy.value.modalEditTitle)
  } finally {
    communityPending.value = false
  }
}

function closeCommunityEditor() {
  if (communityPending.value) {
    return
  }
  communityEditorOpen.value = false
}

async function submitCommunityEditor() {
  if (!trip.value) {
    return
  }

  communityPending.value = true
  communityError.value = null
  communityNotice.value = null

  try {
    if (communityEditorMode.value === "create") {
      await api.createCommunityPost({
        trip_id: tripId.value,
        share_note: communityNoteDraft.value
      })
      communityNotice.value = communityCopy.value.publishSuccess
    } else if (communityPublication.value?.post_id) {
      await api.updateCommunityPost(communityPublication.value.post_id, {
        share_note: communityNoteDraft.value
      })
      communityNotice.value = communityCopy.value.updateSuccess
    }
    communityEditorOpen.value = false
    await loadTrip(false)
  } catch (value) {
    communityError.value = getErrorMessage(value, communityCopy.value.title)
  } finally {
    communityPending.value = false
  }
}

async function refreshCommunityPost() {
  const postId = communityPublication.value?.post_id
  if (!postId) {
    return
  }

  communityPending.value = true
  communityError.value = null
  communityNotice.value = null
  try {
    await api.refreshCommunityPost(postId)
    communityNotice.value = communityCopy.value.refreshSuccess
    await loadTrip(false)
  } catch (value) {
    communityError.value = getErrorMessage(value, communityCopy.value.refreshAction)
  } finally {
    communityPending.value = false
  }
}

async function removeCommunityPost() {
  const postId = communityPublication.value?.post_id
  if (!postId || communityPending.value || !window.confirm(communityCopy.value.removeConfirm)) {
    return
  }

  communityPending.value = true
  communityError.value = null
  communityNotice.value = null
  try {
    await api.deleteCommunityPost(postId)
    communityNotice.value = communityCopy.value.removeSuccess
    await loadTrip(false)
  } catch (value) {
    communityError.value = getErrorMessage(value, communityCopy.value.removeAction)
  } finally {
    communityPending.value = false
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
  [tripId, routeJobId],
  ([nextTripId, nextJobId]) => {
    stopPolling()
    activeJob.value = null
    generateError.value = null
    exportError.value = null
    imageEnrichError.value = null
    refineError.value = null
    searchError.value = null
    communityError.value = null
    communityNotice.value = null
    searchResults.value = []
    hasSearched.value = false
    customRefineInstruction.value = ""
    communityNoteDraft.value = ""
    communityEditorOpen.value = false
    communityEditorMode.value = "create"
    void (async () => {
      await loadTrip(true)
      schedulePendingImageRefresh()
      if (String(nextTripId || "").trim() && String(nextJobId || "").trim()) {
        await pollJob(String(nextJobId), "generate")
      }
    })()
  },
  { immediate: true }
)

watch(
  [shouldLockNavigation, tripId, activeJob],
  ([locked, currentTripId, currentJob]) => {
    if (!locked || !currentJob) {
      jobGuard.clearActiveJob()
      return
    }
    jobGuard.setActiveJob({
      tripId: String(currentTripId || ""),
      jobId: currentJob.job_id,
      type: currentJob.type,
      status: currentJob.status,
      stageMessage: currentJob.stage_message ?? null
    })
  },
  { immediate: true }
)

watch(
  shouldLockNavigation,
  (locked) => {
    if (locked) {
      window.addEventListener("beforeunload", handleBeforeUnload)
      return
    }
    window.removeEventListener("beforeunload", handleBeforeUnload)
  },
  { immediate: true }
)

onBeforeUnmount(() => {
  stopPolling()
  window.removeEventListener("beforeunload", handleBeforeUnload)
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
            <p class="kicker">{{ `${trip.origin} → ${trip.destination}` }}</p>
            <h1>{{ trip.title }}</h1>
            <div class="detail-meta">
              <span>{{ formatDateRange(trip.start_date, trip.end_date) }}</span>
              <span>{{ t('common.budgetValue', { value: formatCurrency(trip.budget) }) }}</span>
              <span>{{ t('common.travelersCount', { count: trip.travelers }) }}</span>
              <span>{{ t('common.paceValue', { value: paceLabel(trip.pace) }) }}</span>
            </div>
          </div>
          <div class="stack-actions">
            <button class="primary" type="button" :disabled="actionLocked || !canGenerate" @click="generate">
              {{ generatePending ? t('common.generating') : t('common.generateItinerary') }}
            </button>
            <button type="button" :disabled="!hasItinerary || actionLocked" @click="exportPdf">
              {{ exportPending ? exportActionRunningLabel : exportActionLabel }}
            </button>
            <button class="button-danger" type="button" :disabled="actionLocked || deletePending" @click="removeTrip">
              {{ deletePending ? deletingTripLabel : deleteTripLabel }}
            </button>
          </div>
        </div>

        <div v-if="trip.itinerary" class="panel-subsection">
          <div>
            <p class="kicker">{{ copy.overviewKicker }}</p>
            <h2>{{ trip.itinerary.summary }}</h2>
          </div>
          <div class="metric-grid">
            <article v-for="metric in itineraryMetrics" :key="metric.label" class="metric-card">
              <p class="kicker">{{ metric.label }}</p>
              <strong>{{ metric.value }}</strong>
            </article>
          </div>
        </div>
      </article>

      <LlmStatusNotice compact />
      <StatePanel :kind="actualExecutionKind" :title="currentModeTitle" :message="currentModeMessage" compact />
      <StatePanel v-if="generateError" kind="error" :title="t('tripDetail.generationFailedTitle')" :message="generateError" compact />
      <StatePanel v-if="refineError" kind="error" :title="copy.quickRefineTitle" :message="refineError" compact />
      <StatePanel v-if="exportError" kind="error" :title="t('tripDetail.exportFailedTitle')" :message="exportError" compact />
      <StatePanel v-if="imageEnrichError" kind="error" :title="copy.enrichImagesActionLabel" :message="imageEnrichError" compact />
      <StatePanel v-if="deleteError" kind="error" :title="deleteTripFailedTitle" :message="deleteError" compact />
      <StatePanel v-if="communityError" kind="error" :title="communityCopy.title" :message="communityError" compact />
      <StatePanel v-if="communityNotice" kind="info" :title="communityCopy.title" :message="communityNotice" compact />

      <div class="workspace-layout">
        <div class="workspace-column">
          <article class="panel panel-stack">
            <div>
              <p class="kicker">{{ copy.currentJob }}</p>
              <h2>{{ activeJob ? formatJobType(activeJob.type) : copy.noActiveJob }}</h2>
              <p class="muted">{{ activeJob ? activeJob.job_id : noActiveJobMessage }}</p>
            </div>
            <div class="inline-actions">
              <button
                type="button"
                :disabled="!canRetryImageEnrichment"
                @click="retryImageEnrichment"
              >
                {{ imageEnrichPending ? copy.enrichImagesActionRunningLabel : copy.enrichImagesActionLabel }}
              </button>
            </div>

            <StatePanel v-if="!activeJob" kind="info" :title="copy.noActiveJob" :message="noActiveJobMessage" compact />

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

              <div class="progress-block">
                <div class="progress-inline">
                  <span>{{ copy.progressLabel }}</span>
                  <strong>{{ formatProgress(activeJob.progress_percent, activeJob.status) }}</strong>
                </div>
                <div class="progress-track" aria-hidden="true">
                  <div class="progress-fill" :style="{ width: `${jobProgress}%` }"></div>
                </div>
              </div>

              <p class="muted">{{ fieldValue(activeJob.stage_message) }}</p>
              <p v-if="imageJobBackendHint" class="muted">{{ imageJobBackendHint }}</p>
              <p v-if="imageEnrichmentStatusSummary" class="muted">{{ imageEnrichmentStatusSummary }}</p>

              <div
                v-if="activeJob.type === 'trip.image_enrich' && (imageEnrichmentDebugRows.length || imageQueryNotes.length || imageCandidateDebugNotes.length || imageReviewerDebugNotes.length)"
                class="panel-subsection"
              >
                <div class="inline-actions" style="justify-content: space-between; align-items: center;">
                  <h3>{{ imageDebugTitle }}</h3>
                  <span class="muted">{{ imageEnrichmentDebugRows.length }}</span>
                </div>

                <div v-if="imageEnrichmentDebugRows.length" class="page-grid">
                  <article v-for="row in imageEnrichmentDebugRows" :key="row.item_id" class="panel-subsection">
                    <div class="inline-actions" style="justify-content: space-between; align-items: center;">
                      <strong>{{ row.name || row.item_id }}</strong>
                      <span class="score-chip">{{ row.status }}</span>
                    </div>
                    <p class="muted">{{ imageDebugSummaryTitle }}: {{ row.priority_tier || copy.notAvailable }}</p>
                    <p class="muted">{{ locale === 'zh-CN' ? `图片 ${row.image_count ?? 0} 张，来源 ${row.source_count ?? 0} 条。` : `${row.image_count ?? 0} images, ${row.source_count ?? 0} sources.` }}</p>
                    <p v-if="row.failure_reason" class="muted">{{ row.failure_reason }}</p>
                  </article>
                </div>

                <div v-if="imageQueryNotes.length" class="panel-subsection">
                  <p class="kicker">{{ imageDebugQueriesTitle }}</p>
                  <ul class="summary-list">
                    <li v-for="note in imageQueryNotes" :key="note">{{ note }}</li>
                  </ul>
                </div>

                <div v-if="imageCandidateDebugNotes.length" class="panel-subsection">
                  <p class="kicker">{{ imageDebugCandidatesTitle }}</p>
                  <ul class="summary-list">
                    <li v-for="note in imageCandidateDebugNotes" :key="note">{{ note }}</li>
                  </ul>
                </div>

                <div v-if="imageReviewerDebugNotes.length" class="panel-subsection">
                  <p class="kicker">{{ imageDebugReviewerTitle }}</p>
                  <ul class="summary-list">
                    <li v-for="note in imageReviewerDebugNotes" :key="note">{{ note }}</li>
                  </ul>
                </div>

                <p v-if="!imageEnrichmentDebugRows.length && !imageQueryNotes.length && !imageCandidateDebugNotes.length && !imageReviewerDebugNotes.length" class="muted">
                  {{ imageDebugEmptyMessage }}
                </p>
              </div>

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
              <p class="kicker">{{ copy.briefKicker }}</p>
              <h2>{{ copy.briefTitle }}</h2>
              <p class="muted">{{ copy.briefDescription }}</p>
            </div>

            <dl class="data-grid">
              <div v-for="field in planningBriefFields" :key="field.label" class="data-pair">
                <dt>{{ field.label }}</dt>
                <dd>{{ field.value }}</dd>
              </div>
            </dl>

            <div class="panel-subsection">
              <p class="kicker">{{ copy.interestsLabel }}</p>
              <div class="chip-list">
                <span v-if="tripInterests.length === 0" class="detail-chip detail-chip--soft">{{ copy.noInterests }}</span>
                <span v-for="interest in tripInterests" :key="interest" class="detail-chip detail-chip--soft">{{ interest }}</span>
              </div>
            </div>
          </article>

          <article v-if="budgetSummary" class="panel panel-stack">
            <div>
              <p class="kicker">{{ budgetPanelTitle }}</p>
              <h2>{{ budgetPanelTitle }}</h2>
              <p class="muted">{{ budgetPanelDescription }}</p>
            </div>

            <div class="metric-grid">
              <article v-for="metric in budgetMetrics" :key="metric.label" class="metric-card">
                <p class="kicker">{{ metric.label }}</p>
                <strong>{{ metric.value }}</strong>
              </article>
            </div>

            <div class="metric-grid">
              <article v-for="category in budgetBreakdownCards" :key="category.key" class="metric-card">
                <p class="kicker">{{ category.label }}</p>
                <strong>{{ category.value }}</strong>
              </article>
            </div>

            <div class="panel-subsection">
              <h3>{{ budgetLineItemsTitle }}</h3>
              <ul class="detail-list">
                <li v-for="item in budgetLineItems" :key="item.key">
                  {{ formatBudgetLineItemTitle(item.title, item.note) }} 路 {{ formatCurrency(item.amount) }}
                </li>
              </ul>
            </div>
          </article>

          <article v-if="transportBookingSummary || reservationEntries.length" class="panel panel-stack">
            <div>
              <p class="kicker">{{ bookingPanelTitle }}</p>
              <h2>{{ bookingPanelTitle }}</h2>
              <p class="muted">{{ bookingPanelDescription }}</p>
            </div>

            <div v-if="transportBookingSummary" class="panel-subsection">
              <h3>{{ transportBookingTitle }}</h3>
              <dl class="data-grid">
                <div v-for="field in transportBookingFields" :key="field.label" class="data-pair">
                  <dt>{{ field.label }}</dt>
                  <dd>{{ field.value }}</dd>
                </div>
              </dl>
              <div v-if="transportBookingHighlights.length" class="chip-list">
                <span
                  v-for="note in transportBookingHighlights"
                  :key="note"
                  class="detail-chip detail-chip--soft"
                >
                  {{ note }}
                </span>
              </div>
              <a
                v-if="transportBookingSummary.official_booking_url"
                class="button-link"
                :href="transportBookingSummary.official_booking_url"
                target="_blank"
                rel="noreferrer"
              >
                {{ copy.sourceOpen }}
              </a>
            </div>

            <div v-if="reservationEntries.length" class="panel-subsection">
              <h3>{{ reservationChecklistTitle }}</h3>
              <ul class="detail-list">
                <li v-for="entry in reservationEntries" :key="entry.key">
                  <strong>{{ entry.title }}</strong>
                  <ul class="summary-list">
                    <li v-for="line in entry.lines" :key="`${entry.key}-${line}`">{{ line }}</li>
                  </ul>
                  <a v-if="entry.officialUrl" class="button-link" :href="entry.officialUrl" target="_blank" rel="noreferrer">{{ copy.sourceOpen }}</a>
                </li>
              </ul>
            </div>
          </article>


          <article class="panel panel-stack">
            <div>
              <p class="kicker">{{ t('tripDetail.itineraryKicker') }}</p>
              <h2>{{ copy.itineraryPanelTitle }}</h2>
              <p class="muted">{{ copy.itineraryPanelDescription }}</p>
            </div>

            <ul v-if="trip.itinerary?.risks?.length" class="risk-list">
              <li v-for="risk in trip.itinerary.risks" :key="risk">{{ risk }}</li>
            </ul>

            <section v-if="citedXhsVisualDocs.length" class="day-weather itinerary-visuals">
              <div class="day-weather__header">
                <span class="item-badge">{{ locale === "zh-CN" ? "参考风景图" : "Referenced visuals" }}</span>
              </div>
              <div class="visual-doc-grid">
                <article v-for="doc in citedXhsVisualDocs" :key="doc.id" class="visual-doc-card">
                  <div class="visual-doc-card__header">
                    <strong>{{ doc.place_name || doc.title }}</strong>
                    <a class="button-link" :href="doc.url" target="_blank" rel="noreferrer">{{ copy.sourceOpen }}</a>
                  </div>
                  <p v-if="doc.author || doc.published_at" class="muted">
                    {{ [doc.author, doc.published_at ? formatDateTime(doc.published_at) : null].filter(Boolean).join(" · ") }}
                  </p>
                  <div class="visual-doc-images">
                    <img v-for="imageUrl in (doc.image_urls ?? []).slice(0, 3)" :key="imageUrl" :src="imageUrl" :alt="doc.title" loading="lazy" />
                  </div>
                </article>
              </div>
            </section>

            <div v-if="trip.itinerary" class="page-grid">
              <article v-for="day in trip.itinerary.days" :key="day.day_index" class="day-card itinerary-day-card">
                <div class="day-card__header">
                  <div>
                    <p class="kicker">{{ t('common.daysLabel', { day: day.day_index, title: day.title }) }}</p>
                    <h3>{{ day.title }}</h3>
                  </div>
                  <strong class="day-card__cost">{{ formatCurrency(day.total_cost) }}</strong>
                </div>

                <p>{{ day.summary }}</p>

                <section v-if="day.weather" class="day-weather">
                  <div class="day-weather__header">
                    <span class="item-badge">{{ locale === "zh-CN" ? "天气" : "Weather" }}</span>
                  </div>
                  <p class="day-weather__summary">{{ day.weather.summary }}</p>
                  <ul v-if="day.weather.notes.length" class="summary-list day-weather__notes">
                    <li v-for="note in day.weather.notes" :key="note">{{ note }}</li>
                  </ul>
                </section>

                <ol class="itinerary-items">
                  <li v-for="item in day.items" :key="item.id" class="itinerary-item">
                    <div class="item-time">{{ item.start_time }} - {{ item.end_time }}</div>
                    <div class="item-main">
                      <div class="item-topline">
                        <strong>{{ item.name }}</strong>
                        <div class="item-badges">
                          <span class="item-badge">{{ formatItemType(item.type) }}</span>
                          <span v-if="formatImagePriorityTier(item.image_priority_tier)" class="item-badge">{{ formatImagePriorityTier(item.image_priority_tier) }}</span>
                          <span class="score-chip">{{ formatScore(item.score) }}</span>
                        </div>
                      </div>
                      <p class="muted">{{ copy.locationLabel }} 路 {{ item.location }}</p>
                      <p class="item-note">{{ item.note }}</p>
                      <ul v-if="itemBookingLines(item).length" class="summary-list">
                        <li v-for="line in itemBookingLines(item)" :key="`${item.id}-${line}`">{{ line }}</li>
                      </ul>
                      <a
                        v-if="item.booking_info?.official_booking_url"
                        class="button-link"
                        :href="item.booking_info.official_booking_url"
                        target="_blank"
                        rel="noreferrer"
                      >
                        {{ copy.sourceOpen }}
                      </a>
                      <p v-if="item.image_priority_reason" class="muted">{{ item.image_priority_reason }}</p>
                      <p v-if="formatImageStatus(item.image_status)" class="muted">{{ formatImageStatus(item.image_status) }}</p>
                      <p v-if="item.image_status === 'failed' && item.image_failure_reason" class="muted">{{ item.image_failure_reason }}</p>
                      <div v-if="item.image_urls?.length" class="visual-doc-images itinerary-item-images">
                        <img v-for="imageUrl in item.image_urls.slice(0, 3)" :key="imageUrl" :src="imageUrl" :alt="item.name" loading="lazy" />
                      </div>
                      <div v-if="item.image_source_urls?.length" class="chip-list">
                        <a
                          v-for="sourceUrl in item.image_source_urls.slice(0, 3)"
                          :key="`${item.id}-${sourceUrl}`"
                          class="button-link"
                          :href="sourceUrl"
                          target="_blank"
                          rel="noreferrer"
                        >
                          {{ copy.imageSourcesLabel ?? "Source" }}
                        </a>
                      </div>
                    </div>
                  </li>
                </ol>
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
                <button class="primary" type="button" :disabled="actionLocked || !canGenerate" @click="generate">{{ t('common.generateItinerary') }}</button>
              </template>
            </StatePanel>
          </article>
        </div>

        <div class="workspace-column">
          <article class="panel panel-stack">
            <div>
              <p class="kicker">{{ communityCopy.kicker }}</p>
              <h2>{{ communityCopy.title }}</h2>
              <p class="muted">{{ communityCopy.description }}</p>
            </div>

            <div v-if="trip.itinerary" class="panel-subsection">
              <img v-if="communityPreviewImage" class="community-cover" :src="communityPreviewImage" :alt="trip.title" />
              <div>
                <h3>{{ trip.title }}</h3>
                <p class="muted">{{ trip.itinerary.summary }}</p>
              </div>
              <div class="chip-list">
                <span class="subtle-chip">{{ communityCopy.previewDays }}: {{ communityPreviewDays }}</span>
                <span class="subtle-chip">{{ communityCopy.previewBudget }}: {{ formatCurrency(trip.budget) }}</span>
                <span v-for="interest in communityPreviewInterestTags" :key="interest" class="detail-chip detail-chip--soft">{{ interest }}</span>
              </div>
            </div>

            <div :class="['panel-banner', { 'panel-banner--warn': communityPublication?.is_stale }]">
              <strong>
                {{
                  communityPublication
                    ? communityPublication.is_stale
                      ? communityCopy.staleTitle
                      : communityCopy.publishedTitle
                    : communityCopy.unpublishedTitle
                }}
              </strong>
              <p class="muted">
                {{
                  communityPublication
                    ? communityPublication.is_stale
                      ? communityCopy.staleMessage
                      : communityCopy.publishedMessage
                    : hasItinerary
                      ? communityCopy.unpublishedMessage
                      : communityCopy.needsItineraryMessage
                }}
              </p>
            </div>

            <div class="inline-actions">
              <button
                v-if="!communityPublication"
                class="primary"
                type="button"
                :disabled="!hasItinerary || communityActionLocked"
                @click="openCommunityEditor('create')"
              >
                {{ communityPending ? communityCopy.publishingAction : communityCopy.publishAction }}
              </button>
              <template v-else>
                <RouterLink class="button-link primary" :to="`/community/${communityPublication.post_id}`">{{ communityCopy.viewAction }}</RouterLink>
                <button type="button" :disabled="communityActionLocked" @click="refreshCommunityPost">
                  {{ communityPending ? communityCopy.refreshingAction : communityCopy.refreshAction }}
                </button>
                <button type="button" :disabled="communityActionLocked" @click="openCommunityEditor('edit')">{{ communityCopy.editAction }}</button>
                <button class="button-danger" type="button" :disabled="communityActionLocked" @click="removeCommunityPost">
                  {{ communityPending ? communityCopy.removingAction : communityCopy.removeAction }}
                </button>
              </template>
            </div>
          </article>

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
            <StatePanel v-else-if="hasSearched && searchResults.length === 0" kind="empty" :title="copy.searchEmptyTitle" :message="copy.searchEmptyMessage" compact />

            <div v-if="searchResults.length" class="page-grid">
              <article v-for="doc in searchResults" :key="doc.id" class="search-card panel-stack">
                <div class="search-card__header">
                  <div>
                    <p class="kicker">{{ fieldValue(doc.source_type) }}</p>
                    <h3>{{ doc.place_name || doc.title }}</h3>
                  </div>
                  <span class="score-chip">{{ t('common.finalScore', { value: doc.scores.final_score }) }}</span>
                </div>

                <p>{{ doc.summary }}</p>

                <div class="panel-subsection">
                  <p class="kicker">{{ copy.structuredFieldsTitle }}</p>
                  <dl class="data-grid">
                    <div class="data-pair">
                      <dt>{{ copy.placeNameLabel }}</dt>
                      <dd>{{ fieldValue(doc.place_name || doc.title) }}</dd>
                    </div>
                    <div class="data-pair">
                      <dt>{{ copy.categoryLabel }}</dt>
                      <dd>{{ fieldValue(doc.category) }}</dd>
                    </div>
                    <div class="data-pair">
                      <dt>{{ copy.openingHoursLabel }}</dt>
                      <dd>{{ fieldValue(doc.opening_hours) }}</dd>
                    </div>
                    <div class="data-pair">
                      <dt>{{ copy.priceHintLabel }}</dt>
                      <dd>{{ fieldValue(doc.price_hint) }}</dd>
                    </div>
                    <div class="data-pair">
                      <dt>{{ copy.addressLabel }}</dt>
                      <dd>{{ fieldValue(doc.address) }}</dd>
                    </div>
                    <div class="data-pair">
                      <dt>{{ copy.geoLabel }}</dt>
                      <dd>{{ formatGeo(doc) }}</dd>
                    </div>
                    <div class="data-pair">
                      <dt>{{ copy.sourceTypeLabel }}</dt>
                      <dd>{{ fieldValue(doc.source_type) }}</dd>
                    </div>
                    <div class="data-pair">
                      <dt>{{ copy.platformLabel }}</dt>
                      <dd>{{ fieldValue(doc.platform) }}</dd>
                    </div>
                    <div class="data-pair">
                      <dt>{{ locale === "zh-CN" ? "作者" : "Author" }}</dt>
                      <dd>{{ fieldValue(doc.author) }}</dd>
                    </div>
                    <div class="data-pair">
                      <dt>{{ locale === "zh-CN" ? "发布时间" : "Published" }}</dt>
                      <dd>{{ doc.published_at ? formatDateTime(doc.published_at) : copy.notAvailable }}</dd>
                    </div>
                    <div class="data-pair">
                      <dt>{{ locale === "zh-CN" ? "互动数据" : "Engagement" }}</dt>
                      <dd>{{ fieldValue(doc.engagement_hint) }}</dd>
                    </div>
                  </dl>
                </div>

                <div v-if="doc.source_tags?.length" class="chip-list">
                  <span v-for="tag in doc.source_tags" :key="tag" class="detail-chip detail-chip--soft">{{ tag }}</span>
                </div>

                <ul class="summary-list" v-if="doc.scores.reasons.length">
                  <li v-for="reason in doc.scores.reasons" :key="reason">{{ reason }}</li>
                </ul>

                <a class="button-link" :href="doc.url" target="_blank" rel="noreferrer">{{ copy.sourceOpen }}</a>
              </article>
            </div>
          </article>

          <article v-if="groundingReferenceDocs.length" class="panel panel-stack">
            <div>
              <p class="kicker">{{ locale === "zh-CN" ? "参考来源" : "Grounding references" }}</p>
              <h2>{{ locale === "zh-CN" ? "本次规划使用的参考来源" : "Grounding sources used" }}</h2>
              <p class="muted">{{ locale === "zh-CN" ? "以下是本次规划实际带入模型上下文的参考来源。" : "These are the grounding sources actually carried into this planning run." }}</p>
            </div>

            <div class="reference-doc-grid">
              <article v-for="doc in groundingReferenceDocs" :key="doc.id" class="reference-doc-card panel-subsection">
                <div class="visual-doc-card__header">
                  <div>
                    <p class="kicker">{{ fieldValue(doc.platform) }}</p>
                    <h3>{{ doc.place_name || doc.title }}</h3>
                  </div>
                  <a class="button-link" :href="doc.url" target="_blank" rel="noreferrer">{{ copy.sourceOpen }}</a>
                </div>
                <p>{{ doc.summary }}</p>
                <p v-if="doc.author || doc.published_at" class="muted">
                  {{ [doc.author, doc.published_at ? formatDateTime(doc.published_at) : null].filter(Boolean).join(" · ") }}
                </p>
                <div v-if="doc.source_tags?.length" class="chip-list">
                  <span v-for="tag in doc.source_tags" :key="tag" class="detail-chip detail-chip--soft">{{ tag }}</span>
                </div>
                <div v-if="doc.image_urls?.length" class="visual-doc-images">
                  <img v-for="imageUrl in doc.image_urls.slice(0, 3)" :key="imageUrl" :src="imageUrl" :alt="doc.title" loading="lazy" />
                </div>
              </article>
            </div>
          </article>

          <article v-if="trip.latest_agent_trace" class="panel panel-stack">
            <div>
              <p class="kicker">{{ latestSuccessfulExecutionKicker }}</p>
              <h2>{{ formatTraceProvider(trip.latest_agent_trace.provider) }}</h2>
              <p class="muted">{{ latestSuccessfulExecutionDescription }}</p>
            </div>

            <div class="metric-grid">
              <article v-for="metric in executionMetrics" :key="metric.label" class="metric-card">
                <p class="kicker">{{ metric.label }}</p>
                <strong>{{ metric.value }}</strong>
              </article>
            </div>

            <div v-if="agentRuns.length" class="agent-run-grid">
              <article v-for="agent in agentRuns" :key="agent.key" class="agent-run-card panel-subsection">
                <div class="agent-run-card__header">
                  <div>
                    <p class="kicker">{{ agent.title }}</p>
                    <h3>{{ agent.description }}</h3>
                  </div>
                  <span class="score-chip">{{ formatAgentRunStatus(agent.status) }}</span>
                </div>
                <p v-if="agent.prompt_focus" class="muted"><strong>{{ copy.agentPromptLabel }}:</strong> {{ agent.prompt_focus }}</p>
                <p v-if="agent.output_summary" class="muted"><strong>{{ copy.agentOutputLabel }}:</strong> {{ agent.output_summary }}</p>
                <p v-if="agent.model" class="muted"><strong>{{ copy.agentModelLabel }}:</strong> {{ agent.model }}</p>
                <p v-if="agent.prompt_version" class="muted"><strong>{{ copy.agentPromptVersionLabel }}:</strong> {{ agent.prompt_version }}</p>
                <p v-if="agentEndpoint(agent)" class="muted"><strong>{{ "Endpoint" }}:</strong> {{ agentEndpoint(agent) }}</p>
                <p v-if="agentWireApi(agent)" class="muted"><strong>{{ "Wire API" }}:</strong> {{ agentWireApi(agent) }}</p>
                <div v-if="agentDisplayCitations(agent).length" class="panel-subsection">
                  <p class="kicker">{{ copy.agentCitationsLabel }}</p>
                  <ul class="summary-list">
                    <li v-for="citation in agentDisplayCitations(agent)" :key="`${agent.key}-${citation.href}`">
                      <a class="button-link" :href="citation.href" target="_blank" rel="noreferrer">{{ citation.label }}</a>
                    </li>
                  </ul>
                </div>
                <ul v-if="agentVisibleNotes(agent).length" class="summary-list">
                  <li v-for="note in agentVisibleNotes(agent)" :key="`${agent.key}-${note}`">{{ note }}</li>
                </ul>
              </article>
            </div>

            <div>
              <p class="kicker">{{ copy.agentNotesLabel }}</p>
              <ul class="detail-list">
                <li v-for="note in trip.latest_agent_trace.notes" :key="note">{{ note }}</li>
              </ul>
            </div>
            <p v-if="trip.latest_agent_trace.license_notice" class="muted">{{ trip.latest_agent_trace.license_notice }}</p>
          </article>
        </div>
      </div>
    </template>

    <div v-if="communityEditorOpen && trip" class="modal-backdrop" @click.self="closeCommunityEditor">
      <article class="panel panel-stack modal-card">
        <div>
          <p class="kicker">{{ communityCopy.kicker }}</p>
          <h2>{{ communityEditorMode === 'create' ? communityCopy.modalCreateTitle : communityCopy.modalEditTitle }}</h2>
          <p class="muted">{{ communityCopy.noteHint }}</p>
        </div>

        <div class="panel-subsection">
          <img v-if="communityPreviewImage" class="community-cover" :src="communityPreviewImage" :alt="trip.title" />
          <div>
            <p class="kicker">{{ communityCopy.previewTitle }}</p>
            <h3>{{ trip.title }}</h3>
            <p class="muted">{{ trip.itinerary?.summary }}</p>
          </div>
          <div class="chip-list">
            <span class="subtle-chip">{{ communityCopy.previewDays }}: {{ communityPreviewDays }}</span>
            <span class="subtle-chip">{{ communityCopy.previewBudget }}: {{ formatCurrency(trip.budget) }}</span>
            <span v-for="interest in communityPreviewInterestTags" :key="interest" class="detail-chip detail-chip--soft">{{ interest }}</span>
          </div>
        </div>

        <div class="field">
          <label for="community-note">{{ communityCopy.noteLabel }}</label>
          <textarea
            id="community-note"
            v-model="communityNoteDraft"
            :placeholder="communityCopy.notePlaceholder"
            maxlength="280"
          />
          <p class="muted">{{ communityNoteDraft.length }}/280</p>
        </div>

        <div class="inline-actions">
          <button class="primary" type="button" :disabled="communityPending" @click="submitCommunityEditor">
            {{
              communityPending
                ? communityEditorMode === "create"
                  ? communityCopy.publishingAction
                  : communityCopy.savingAction
                : communityEditorMode === "create"
                  ? communityCopy.submitCreate
                  : communityCopy.submitEdit
            }}
          </button>
          <button type="button" :disabled="communityPending" @click="closeCommunityEditor">{{ communityCopy.cancelAction }}</button>
        </div>
      </article>
    </div>
  </section>
</template>
