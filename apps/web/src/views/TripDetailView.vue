<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import type {
  AgentRunStep,
  CommunityPostSummary,
  GeneratedItinerary,
  ItineraryDay,
  ItineraryItem,
  JobTimelineEntry,
  SearchDocument,
  TransportBookingSummary,
  Trip,
  TripRefineInput,
  TripRefineSession
} from "@travelmind/shared-types"
import LlmStatusNotice from "@/components/LlmStatusNotice.vue"
import PoiImage from "@/components/PoiImage.vue"
import TripJourneyFlow from "@/components/TripJourneyFlow.vue"
import StatePanel from "@/components/StatePanel.vue"
import JobProgressSummary from "@/components/JobProgressSummary.vue"
import { jobPresentation, jobTitle, publicJobError } from "@/lib/jobPresentation"
import { useAuthStore } from "@/stores/auth"
import StatusPill from "@/components/StatusPill.vue"
import TmButton from "@/components/ui/TmButton.vue"
import TmMetricCard from "@/components/ui/TmMetricCard.vue"
import TmAuroraPanel from "@/components/ui/TmAuroraPanel.vue"
import TmProgressTrack from "@/components/ui/TmProgressTrack.vue"
import TmField from "@/components/ui/TmField.vue"
import TmSelect from "@/components/ui/TmSelect.vue"
import TmTextarea from "@/components/ui/TmTextarea.vue"
import TmAnchorNav from "@/components/ui/TmAnchorNav.vue"
import { api, getErrorMessage, type JobRecord } from "@/lib/api"
import { isJobActive, isJobTerminal } from "@/lib/jobStatus"
import { enrichGeneratedItineraryWithBudget } from "@/lib/budgeting"
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
const route = useRoute()
const settingsStore = useLlmSettingsStore()
const jobGuard = useJobGuardStore()
const auth = useAuthStore()
void settingsStore.bootstrap()

const isDebug = computed(() => {
  if (!auth.user?.is_admin) {
    return false
  }
  const flag = route.query.debug
  if (Array.isArray(flag)) {
    return flag.some((value) => value === "1" || value === "true")
  }
  return flag === "1" || flag === "true"
})

const refineModalOpen = ref(false)
async function openRefineModal() {
  if (actionLocked.value || !canUseModel.value) {
    return
  }
  refineError.value = null
  refineModalOpen.value = true
  await loadRefineContext()
}
function closeRefineModal() {
  if (refinePending.value) {
    return
  }
  refineModalOpen.value = false
}

const trip = ref<Trip | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const activeJob = ref<JobRecord | null>(null)
const generatePending = ref(false)
const generateError = ref<string | null>(null)
const resumeGeneratePending = ref(false)
const resumeGenerateError = ref<string | null>(null)
const cancelJobPending = ref(false)
const cancelJobError = ref<string | null>(null)
const exportPending = ref(false)
const exportError = ref<string | null>(null)
const imageEnrichPending = ref(false)
const imageEnrichError = ref<string | null>(null)
const deletePending = ref(false)
const deleteError = ref<string | null>(null)
const refinePending = ref(false)
const refineError = ref<string | null>(null)
const itineraryEditorOpen = ref(false)
const itineraryDraft = ref<GeneratedItinerary | null>(null)
const itinerarySavePending = ref(false)
const itinerarySaveError = ref<string | null>(null)
const itinerarySaveNotice = ref<string | null>(null)
const searchPending = ref(false)
const searchError = ref<string | null>(null)
const searchResults = ref<SearchDocument[]>([])
const hasSearched = ref(false)
const searchQuery = ref("best quiet morning spots")
const manualLinks = ref("https://kyoto.travel/en")
const refineSession = ref<TripRefineSession | null>(null)
const refineSessionPending = ref(false)
const refineGuideTitle = ref("")
const refineGuideContent = ref("")
const refineCommunityPosts = ref<CommunityPostSummary[]>([])
const selectedCommunityPostId = ref("")
const customRefineInstruction = ref("")
const communityPending = ref(false)
const communityError = ref<string | null>(null)
const communityNotice = ref<string | null>(null)
const communityNoteDraft = ref("")
const communityEditorOpen = ref(false)
const communityEditorMode = ref<"create" | "edit">("create")
let timer: number | null = null
const cancelRequestedJobIds = new Set<string>()
const JOB_POLL_INTERVAL_MS = 3000

const { locale, t } = useI18n()
const enCopy = {
  notAvailable: "N/A",
  currentJob: "Current job",
  noActiveJob: "No active job yet.",
  noActiveJobMessage: "Generation, refinement, image enrichment, and export run as backend jobs and continue after this page closes.",
  browserGenerateMessage: "Generating through the backend planning workflow.",
  browserRefineMessage: "Refining through the backend workflow with server-side trip context.",
  browserSaved: "Saved back to backend",
  browserSavedMessage: "The generated itinerary has been persisted to your Trip record.",
  resumeGenerationActionLabel: "Continue from failed node",
  resumeGenerationRunningLabel: "Continuing...",
  resumeGenerationFailedTitle: "Failed to continue generation",
  directModeTitle: "Durable backend planning",
  directModeMessage: "Generation and refinement run as durable backend jobs, so closing this page does not discard progress.",
  quickRefineTitle: "Quick refine",
  quickRefineSubtitle: "Run a durable backend refinement with saved conversation and guide context.",
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
    "trip.generate": "Backend generation",
    "trip.refine": "Backend refinement",
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
  noActiveJobMessage: "生成、微调、景点补图与导出均作为后端任务运行，关闭页面也不会丢失进度。",
  browserGenerateMessage: "正在通过后端规划工作流生成行程。",
  browserRefineMessage: "正在通过后端工作流结合服务端行程上下文进行微调。",
  browserSaved: "已回写到后端",
  browserSavedMessage: "生成后的行程已经写回当前 Trip 记录。",
  resumeGenerationActionLabel: "继续生成",
  resumeGenerationRunningLabel: "继续生成中...",
  resumeGenerationFailedTitle: "继续生成失败",
  directModeTitle: "后端持久规划",
  directModeMessage: "生成与微调均作为可持久恢复的后端任务运行，关闭页面也不会丢失进度。",
  quickRefineTitle: "快速微调",
  quickRefineSubtitle: "使用已保存的对话、攻略与社区来源运行后端微调任务。",
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
  briefKicker: "出行需求",
  briefTitle: "本次出行安排",
  briefDescription: "确认目的地、日期和偏好，方便继续调整行程。",
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
    "trip.generate": "后端生成",
    "trip.refine": "后端微调",
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
const cancelJobActionLabel = computed(() => (locale.value === "zh-CN" ? "停止任务" : "Stop task"))
const cancelJobRunningLabel = computed(() => (locale.value === "zh-CN" ? "正在停止..." : "Stopping..."))
const cancelJobFailedTitle = computed(() => (locale.value === "zh-CN" ? "停止任务失败" : "Failed to stop task"))
const cancelJobConfirmMessage = computed(() =>
  locale.value === "zh-CN"
    ? "停止当前任务？已发出的上游请求可能会在后台短暂收尾，但页面会立即取消这个任务。"
    : "Stop the current task? In-flight upstream requests may take a moment to unwind, but this job will be cancelled now."
)
const tripId = computed(() => String(props.id ?? ""))
const routeJobId = computed(() => String(props.jobId ?? ""))
const hasItinerary = computed(() => Boolean(trip.value?.itinerary))
const isJobRunning = computed(() => isJobActive(activeJob.value?.status))
const canCancelActiveJob = computed(() => Boolean(activeJob.value && isJobRunning.value))
const actionLocked = computed(() => generatePending.value || resumeGeneratePending.value || refinePending.value || exportPending.value || deletePending.value || itinerarySavePending.value || isJobRunning.value)
const imageEnrichInProgress = computed(() => activeJob.value?.type === "trip.image_enrich" && isJobRunning.value)
const canRetryImageEnrichment = computed(() => Boolean(hasItinerary.value && !actionLocked.value && !imageEnrichPending.value && !imageEnrichInProgress.value && !auth.user?.generation_quota))
const canUseModel = computed(() => settingsStore.loaded && settingsStore.isConfigured)
const canGenerate = computed(() => settingsStore.loaded && settingsStore.isConfigured)
const canResumeGeneration = computed(() =>
  Boolean(activeJob.value?.status === "failed" && activeJob.value?.type === "trip.generate" && activeJob.value?.can_resume && !resumeGeneratePending.value && !isJobRunning.value)
)
const usesLangGraph = computed(() => settingsStore.usesLangGraph)
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
const anchorSections = computed(() => {
  const sections = [
    { id: "overview", label: locale.value === "zh-CN" ? "概览" : "Overview" },
    { id: "job", label: locale.value === "zh-CN" ? "任务" : "Job" },
    { id: "brief", label: locale.value === "zh-CN" ? "出行需求" : "Travel brief" },
    { id: "itinerary", label: locale.value === "zh-CN" ? "行程" : "Itinerary" }
  ]
  if (isDebug.value) {
    sections.push({ id: "search", label: locale.value === "zh-CN" ? "搜索" : "Search" })
    if (trip.value?.latest_agent_trace) {
      sections.push({ id: "agents", label: "Agents" })
    }
  }
  return sections
})

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
  return isJobActive(activeJob.value.status)
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
const itineraryEditorCopy = computed(() =>
  locale.value === "zh-CN"
    ? {
        editAction: "编辑行程",
        saveAction: "保存行程",
        savingAction: "保存中...",
        cancelAction: "取消编辑",
        addDayAction: "添加一天",
        addStopAction: "添加行程点",
        removeDayAction: "删除当天",
        removeStopAction: "删除",
        summaryLabel: "行程摘要",
        risksLabel: "风险提醒",
        risksHint: "每行一条提醒，可留空。",
        dayTitleLabel: "当天标题",
        daySummaryLabel: "当天摘要",
        dayCostLabel: "当天预算",
        itemNameLabel: "名称",
        itemTypeLabel: "类型",
        itemStartLabel: "开始时间",
        itemEndLabel: "结束时间",
        itemLocationLabel: "地点",
        itemScoreLabel: "评分",
        itemNoteLabel: "备注",
        stopLabel: "行程点",
        saveSuccess: "行程已保存。",
        saveFailedTitle: "保存行程失败",
        validationSummary: "请填写行程摘要。",
        validationDayTitle: "请填写每天的标题。",
        validationItemName: "请填写每个行程点的名称。",
        validationItemTime: "请填写每个行程点的开始和结束时间。",
        validationItemType: "请填写每个行程点的类型。"
      }
    : {
        editAction: "Edit itinerary",
        saveAction: "Save itinerary",
        savingAction: "Saving...",
        cancelAction: "Cancel edit",
        addDayAction: "Add day",
        addStopAction: "Add stop",
        removeDayAction: "Remove day",
        removeStopAction: "Remove",
        summaryLabel: "Itinerary summary",
        risksLabel: "Risk notes",
        risksHint: "One note per line. Optional.",
        dayTitleLabel: "Day title",
        daySummaryLabel: "Day summary",
        dayCostLabel: "Day budget",
        itemNameLabel: "Name",
        itemTypeLabel: "Type",
        itemStartLabel: "Start time",
        itemEndLabel: "End time",
        itemLocationLabel: "Location",
        itemScoreLabel: "Score",
        itemNoteLabel: "Note",
        stopLabel: "Stop",
        saveSuccess: "Itinerary saved.",
        saveFailedTitle: "Failed to save itinerary",
        validationSummary: "Add an itinerary summary.",
        validationDayTitle: "Add a title for each day.",
        validationItemName: "Add a name for each itinerary stop.",
        validationItemTime: "Add start and end times for each itinerary stop.",
        validationItemType: "Add a type for each itinerary stop."
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
const shouldDisplayItinerary = computed(() => Boolean(trip.value?.itinerary))
const itineraryView = ref<"flow" | "list">("flow")
const isJourneyView = computed(() => shouldDisplayItinerary.value && itineraryView.value === "flow")
async function showFullStop(stop: { dayIndex: number; itemId: string }) {
  itineraryView.value = "list"
  await nextTick()
  const node = document.getElementById(`itinerary-stop-${stop.dayIndex}-${stop.itemId}`)
  node?.scrollIntoView({ behavior: "auto", block: "center" })
  node?.focus({ preventScroll: true })
}
async function editFromJourney() {
  itineraryView.value = "list"
  openItineraryEditor()
  await nextTick()
  document.getElementById("itinerary")?.scrollIntoView({ behavior: "auto", block: "start" })
}

const pendingImageDisplayTitle = computed(() => (locale.value === "zh-CN" ? "正在补充景点图片" : "Adding attraction images"))
const pendingImageDisplayMessage = computed(() =>
  locale.value === "zh-CN"
    ? "攻略已生成，正在补充可追溯的景点实景图。"
    : "The itinerary is generated. We are adding images from Trip.com, Pixabay, and Pexels, then the full guide will appear automatically."
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
    case "langgraph":
      return locale.value === "zh-CN" ? "最近一次实际执行：LangGraph 工作流" : "Latest execution: LangGraph workflow"
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
    return usesLangGraph.value
      ? locale.value === "zh-CN"
        ? "当前配置为 LangGraph，但这条行程还没有成功执行记录。完成一次生成或润色后，这里会显示每个角色实际调用的 endpoint、model 和状态。"
        : "LangGraph is configured, but this trip does not have a successful execution trace yet. After the next generation or refinement run, this panel will show the endpoint, model, and status used by each role."
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

  if (latestTrace.value.provider === "langgraph") {
    return agentRuns.value.length > 0
      ? locale.value === "zh-CN"
        ? `最近一次成功执行来自后端 LangGraph 工作流，已记录 ${agentRuns.value.length} 个角色的 endpoint、model 与状态。`
        : `The latest successful run came from the backend LangGraph workflow, with ${agentRuns.value.length} recorded roles and their endpoints, models, and statuses.`
      : locale.value === "zh-CN"
        ? "最近一次成功执行来自后端 LangGraph 工作流。"
        : "The latest successful run came from the backend LangGraph workflow."
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
const noActiveJobMessage = computed(() => "准备好出行信息后，点击生成即可开始；离开页面后仍会继续处理。")

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
const refineWorkbenchCopy = computed(() => ({
  title: "Conversational refine",
  subtitle: "Refine this itinerary with remembered conversation, uploaded guide notes, and community guide references.",
  memoryTitle: "Conversation memory",
  memoryEmpty: "No refine conversation yet.",
  uploadedTitle: "Uploaded guides",
  uploadedEmpty: "No uploaded guide notes yet.",
  guideTitleLabel: "Guide title",
  guideTitlePlaceholder: "Example: Kyoto food notes",
  guideContentLabel: "Guide content",
  guideContentPlaceholder: "Paste text from a guide, travel note, or checklist.",
  guideFileLabel: "Import text file",
  addGuide: "Add guide",
  communityTitle: "Community guides",
  communityEmpty: "No community guide selected yet.",
  communitySelectLabel: "Published community guide",
  communitySelectPlaceholder: "Choose a community guide",
  attachCommunity: "Attach guide",
  removeSource: "Remove",
  resetMemory: "Reset memory",
  resetConfirm: "Clear this trip's refine conversation and attached guide sources?",
  contextLabel: "Context",
  messagesLabel: "messages",
  uploadedLabel: "uploaded",
  communityLabel: "community",
  assistantSummaryPrefix: "Updated itinerary",
  guideValidation: "Add a title and at least 20 characters of guide content.",
  communityValidation: "Choose a community guide first."
}))
const refineConversationMessages = computed(() => refineSession.value?.messages ?? [])
const refineUploadedGuides = computed(() => refineSession.value?.uploaded_guides ?? [])
const refineCommunitySources = computed(() => refineSession.value?.community_sources ?? [])
const refineCommunityOptions = computed(() => {
  const attachedPostIds = new Set(refineCommunitySources.value.map((source) => source.post_id))
  return refineCommunityPosts.value
    .filter((post) => !attachedPostIds.has(post.id))
    .map((post) => ({
      value: post.id,
      label: `${post.destination} - ${post.title}`
    }))
})
const refineContextSummary = computed(() => {
  const labels = refineWorkbenchCopy.value
  return [
    `${refineConversationMessages.value.length} ${labels.messagesLabel}`,
    `${refineUploadedGuides.value.length} ${labels.uploadedLabel}`,
    `${refineCommunitySources.value.length} ${labels.communityLabel}`
  ].join(" / ")
})
const quickRefineActions = computed(() => copy.value.quickRefineActions)
const itineraryDraftRisksText = computed(() => (itineraryDraft.value?.risks ?? []).join("\n"))
const itineraryItemTypeOptions = computed(() => {
  const defaultTypes = ["sight", "meal", "explore", "transit", "hotel", "photo"]
  const draftTypes = itineraryDraft.value?.days.flatMap((day) => day.items.map((item) => item.type.trim()).filter(Boolean)) ?? []
  return Array.from(new Set([...defaultTypes, ...draftTypes])).map((value) => ({
    value,
    label: formatItemType(value)
  }))
})
const budgetPanelTitle = computed(() => (locale.value === "zh-CN" ? "参考预算明细" : "Reference budget details"))
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
    { label: locale.value === "zh-CN" ? (budgetSummary.value.incomplete ? "已计参考费用" : "预计总花费") : (budgetSummary.value.incomplete ? "Priced reference subtotal" : "Estimated total"), value: formatCurrency(budgetSummary.value.estimated_total) },
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
const stayRecommendation = computed(() => trip.value?.itinerary?.stay_recommendation ?? null)
const stayPanelTitle = computed(() => (locale.value === "zh-CN" ? "住宿推荐" : "Stay recommendation"))
const stayHotelFields = computed(() => {
  const hotel = stayRecommendation.value?.final_recommended_hotel
  if (!hotel) {
    return []
  }
  return [
    { label: locale.value === "zh-CN" ? "推荐酒店" : "Recommended hotel", value: fieldValue(hotel.name) },
    { label: "来源核验", value: hotel.identity_status === "page_verified" ? "名称与来源页面已核对；房价和可订状态待确认" : "待核验" },
    { label: locale.value === "zh-CN" ? "区域" : "Area", value: fieldValue(hotel.area) },
    { label: locale.value === "zh-CN" ? "类型" : "Type", value: fieldValue(hotel.hotel_type) },
    { label: locale.value === "zh-CN" ? "价格" : "Price", value: fieldValue(hotel.price_hint) },
    { label: locale.value === "zh-CN" ? "评价" : "Reviews", value: fieldValue([hotel.review_score, hotel.review_count].filter(Boolean).join(" / ")) },
    { label: locale.value === "zh-CN" ? "匹配度" : "Fit", value: fieldValue(hotel.preference_match || hotel.reason) }
  ]
})
const stayHighlights = computed(() => {
  const stay = stayRecommendation.value
  if (!stay) {
    return []
  }
  return uniqueCompactStrings([
    ...(stay.recommended_areas ?? []).map((area) => `${locale.value === "zh-CN" ? "推荐区域" : "Area"}: ${area}`),
    ...(stay.stay_strategy ?? []),
    ...(stay.budget_notes ?? []),
    ...(stay.review_notes ?? []),
    ...(stay.preference_match_notes ?? []),
    ...(stay.price_timeliness_notes ?? []),
    ...(stay.hotel_risks ?? []),
    ...(stay.final_recommended_hotel?.evidence_notes ?? [])
  ]).slice(0, 6)
})
const stayCandidateRows = computed(() => (stayRecommendation.value?.hotel_candidates ?? []).slice(0, 3))
const staySourceUrls = computed(() => {
  const stay = stayRecommendation.value
  if (!stay) {
    return []
  }
  return uniqueCompactStrings([
    ...(stay.source_urls ?? []),
    ...(stay.final_recommended_hotel?.source_urls ?? []),
    ...stayCandidateRows.value.flatMap((candidate) => candidate.source_urls ?? [])
  ]).slice(0, 4)
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
const transportServiceCandidates = computed(() => (transportBookingSummary.value?.service_candidates ?? []).slice(0, 6))
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

function cloneItinerary(itinerary: GeneratedItinerary): GeneratedItinerary {
  return JSON.parse(JSON.stringify(itinerary)) as GeneratedItinerary
}

function splitDraftLines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
}

function uniqueCompactStrings(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const value of values) {
    const normalized = (value ?? "").trim()
    if (!normalized || seen.has(normalized)) {
      continue
    }
    seen.add(normalized)
    result.push(normalized)
  }
  return result
}

function normalizeDraftAmount(value: string | number | null | undefined): number {
  const amount = typeof value === "number" ? value : Number(value ?? 0)
  if (!Number.isFinite(amount)) {
    return 0
  }
  return Math.max(0, Math.round((amount + Number.EPSILON) * 100) / 100)
}

function normalizeDraftScore(value: string | number | null | undefined): number {
  const score = typeof value === "number" ? value : Number(value ?? 0)
  if (!Number.isFinite(score)) {
    return 0
  }
  return Math.min(1, Math.max(0, Math.round((score + Number.EPSILON) * 100) / 100))
}

function createDraftItemId(dayIndex: number): string {
  return `manual_day_${dayIndex}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

function createManualItineraryItem(dayIndex: number): ItineraryItem {
  return {
    id: createDraftItemId(dayIndex),
    type: "explore",
    name: locale.value === "zh-CN" ? "新行程点" : "New stop",
    start_time: "09:00",
    end_time: "10:00",
    location: trip.value?.destination ?? "",
    score: 0.8,
    note: ""
  }
}

function createManualItineraryDay(dayIndex: number): ItineraryDay {
  return {
    day_index: dayIndex,
    title: locale.value === "zh-CN" ? `第 ${dayIndex} 天` : `Day ${dayIndex}`,
    summary: "",
    total_cost: 0,
    items: [createManualItineraryItem(dayIndex)]
  }
}

function renumberItineraryDraftDays() {
  if (!itineraryDraft.value) {
    return
  }
  itineraryDraft.value.days.forEach((day, index) => {
    day.day_index = index + 1
  })
}

function openItineraryEditor() {
  if (!trip.value?.itinerary || actionLocked.value) {
    return
  }
  itineraryDraft.value = cloneItinerary(trip.value.itinerary)
  itinerarySaveError.value = null
  itinerarySaveNotice.value = null
  itineraryEditorOpen.value = true
}

function cancelItineraryEditor() {
  if (itinerarySavePending.value) {
    return
  }
  itineraryDraft.value = null
  itinerarySaveError.value = null
  itineraryEditorOpen.value = false
}

function updateItineraryDraftRisks(value: string) {
  if (!itineraryDraft.value) {
    return
  }
  itineraryDraft.value.risks = splitDraftLines(value)
}

function updateItineraryDraftSummary(value: string) {
  if (!itineraryDraft.value) {
    return
  }
  itineraryDraft.value.summary = value
}

function addItineraryDraftDay() {
  if (!itineraryDraft.value || itinerarySavePending.value) {
    return
  }
  itineraryDraft.value.days.push(createManualItineraryDay(itineraryDraft.value.days.length + 1))
}

function removeItineraryDraftDay(dayIndex: number) {
  if (!itineraryDraft.value || itinerarySavePending.value || itineraryDraft.value.days.length <= 1) {
    return
  }
  itineraryDraft.value.days.splice(dayIndex, 1)
  renumberItineraryDraftDays()
}

function addItineraryDraftItem(day: ItineraryDay) {
  if (itinerarySavePending.value) {
    return
  }
  day.items.push(createManualItineraryItem(day.day_index))
}

function removeItineraryDraftItem(day: ItineraryDay, itemIndex: number) {
  if (itinerarySavePending.value || day.items.length <= 1) {
    return
  }
  day.items.splice(itemIndex, 1)
}

function normalizeItineraryDraft(): GeneratedItinerary | null {
  const draft = itineraryDraft.value
  if (!draft) {
    return null
  }

  const summary = draft.summary.trim()
  if (!summary) {
    itinerarySaveError.value = itineraryEditorCopy.value.validationSummary
    return null
  }

  const days: ItineraryDay[] = []
  for (const [dayIndex, day] of draft.days.entries()) {
    const title = day.title.trim()
    if (!title) {
      itinerarySaveError.value = itineraryEditorCopy.value.validationDayTitle
      return null
    }

    const items: ItineraryItem[] = []
    for (const [itemIndex, item] of day.items.entries()) {
      const type = item.type.trim()
      const name = item.name.trim()
      const startTime = item.start_time.trim()
      const endTime = item.end_time.trim()

      if (!type) {
        itinerarySaveError.value = itineraryEditorCopy.value.validationItemType
        return null
      }
      if (!name) {
        itinerarySaveError.value = itineraryEditorCopy.value.validationItemName
        return null
      }
      if (!startTime || !endTime) {
        itinerarySaveError.value = itineraryEditorCopy.value.validationItemTime
        return null
      }

      items.push({
        ...item,
        id: item.id.trim() || createDraftItemId(dayIndex + 1),
        type,
        name,
        start_time: startTime,
        end_time: endTime,
        location: item.location.trim(),
        score: normalizeDraftScore(item.score),
        note: item.note.trim()
      })

      if (!items[itemIndex].location) {
        items[itemIndex].location = trip.value?.destination ?? ""
      }
    }

    days.push({
      ...day,
      day_index: dayIndex + 1,
      title,
      summary: day.summary.trim(),
      total_cost: normalizeDraftAmount(day.total_cost),
      items
    })
  }

  const dayCostTotal = days.reduce((sum, day) => sum + normalizeDraftAmount(day.total_cost), 0)
  return {
    ...draft,
    summary,
    total_budget_estimate: dayCostTotal > 0 ? normalizeDraftAmount(dayCostTotal) : normalizeDraftAmount(draft.total_budget_estimate),
    days,
    risks: splitDraftLines((draft.risks ?? []).join("\n"))
  }
}

async function saveItineraryEditor() {
  if (!trip.value || !itineraryDraft.value) {
    return
  }

  itinerarySaveNotice.value = null
  itinerarySaveError.value = null
  const normalized = normalizeItineraryDraft()
  if (!normalized) {
    return
  }

  itinerarySavePending.value = true
  try {
    const enrichedItinerary = enrichGeneratedItineraryWithBudget(trip.value, normalized)
    trip.value = await api.saveTripItinerary(tripId.value, {
      itinerary: enrichedItinerary
    })
    itineraryDraft.value = trip.value.itinerary ? cloneItinerary(trip.value.itinerary) : null
    itineraryEditorOpen.value = false
    itinerarySaveNotice.value = itineraryEditorCopy.value.saveSuccess
    schedulePendingImageRefresh()
  } catch (value) {
    itinerarySaveError.value = getErrorMessage(value, itineraryEditorCopy.value.saveFailedTitle)
  } finally {
    itinerarySavePending.value = false
  }
}

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

function clampProgress(value?: number | null, status?: string): number {
  if (typeof value === "number") {
    return Math.max(0, Math.min(100, Math.round(value)))
  }
  if (status === "completed") {
    return 100
  }
  return 0
}

function isTerminalJobStatus(status?: string | null): boolean {
  return isJobTerminal(status)
}

function formatProgress(value?: number | null, status?: string): string {
  if (typeof value === "number" || isJobActive(status) || status === "completed") {
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
    service_candidates: Array.isArray(raw.service_candidates)
      ? raw.service_candidates.filter((item): item is NonNullable<TransportBookingSummary["service_candidates"]>[number] => Boolean(item && typeof item === "object"))
      : [],
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
    (summary.service_candidates?.length ?? 0) > 0 ||
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
  if (value === "cancelled") {
    return locale.value === "zh-CN" ? "已取消" : "Cancelled"
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
  return jobTitle(value)
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
    case "langgraph":
      return locale.value === "zh-CN" ? "LangGraph 后端工作流" : "LangGraph backend workflow"
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

async function loadRefineContext() {
  if (!trip.value) {
    return
  }

  refineSessionPending.value = true
  try {
    const [session, posts] = await Promise.all([
      api.getRefineSession(tripId.value),
      api.listCommunityPosts()
    ])
    refineSession.value = session
    refineCommunityPosts.value = posts
  } catch (value) {
    refineError.value = getErrorMessage(value, refineWorkbenchCopy.value.title)
  } finally {
    refineSessionPending.value = false
  }
}

async function ensureRefineSessionLoaded(): Promise<TripRefineSession | null> {
  if (!refineSession.value) {
    await loadRefineContext()
  }
  return refineSession.value
}

async function addRefineUploadedGuide() {
  const title = refineGuideTitle.value.trim()
  const content = refineGuideContent.value.trim()
  if (!title || content.length < 20) {
    refineError.value = refineWorkbenchCopy.value.guideValidation
    return
  }

  refineSessionPending.value = true
  refineError.value = null
  try {
    refineSession.value = await api.addUploadedGuide(tripId.value, {
      title,
      content,
      source_type: "manual_text"
    })
    refineGuideTitle.value = ""
    refineGuideContent.value = ""
  } catch (value) {
    refineError.value = getErrorMessage(value, refineWorkbenchCopy.value.addGuide)
  } finally {
    refineSessionPending.value = false
  }
}

async function handleGuideFileSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) {
    return
  }
  try {
    const text = await file.text()
    if (!refineGuideTitle.value.trim()) {
      refineGuideTitle.value = file.name.replace(/\.[^.]+$/, "")
    }
    refineGuideContent.value = text.slice(0, 40000)
  } catch (value) {
    refineError.value = getErrorMessage(value, "Unable to read guide file")
  } finally {
    input.value = ""
  }
}

async function removeRefineUploadedGuide(sourceId: string) {
  refineSessionPending.value = true
  refineError.value = null
  try {
    refineSession.value = await api.removeUploadedGuide(tripId.value, sourceId)
  } catch (value) {
    refineError.value = getErrorMessage(value, refineWorkbenchCopy.value.removeSource)
  } finally {
    refineSessionPending.value = false
  }
}

async function attachSelectedCommunitySource() {
  const postId = selectedCommunityPostId.value.trim()
  if (!postId) {
    refineError.value = refineWorkbenchCopy.value.communityValidation
    return
  }

  refineSessionPending.value = true
  refineError.value = null
  try {
    refineSession.value = await api.attachCommunitySource(tripId.value, { post_id: postId })
    selectedCommunityPostId.value = ""
  } catch (value) {
    refineError.value = getErrorMessage(value, refineWorkbenchCopy.value.attachCommunity)
  } finally {
    refineSessionPending.value = false
  }
}

async function removeRefineCommunitySource(sourceId: string) {
  refineSessionPending.value = true
  refineError.value = null
  try {
    refineSession.value = await api.removeCommunitySource(tripId.value, sourceId)
  } catch (value) {
    refineError.value = getErrorMessage(value, refineWorkbenchCopy.value.removeSource)
  } finally {
    refineSessionPending.value = false
  }
}

async function resetRefineSession() {
  if (!window.confirm(refineWorkbenchCopy.value.resetConfirm)) {
    return
  }

  refineSessionPending.value = true
  refineError.value = null
  try {
    await api.resetRefineSession(tripId.value)
    refineSession.value = await api.getRefineSession(tripId.value)
    selectedCommunityPostId.value = ""
    refineGuideTitle.value = ""
    refineGuideContent.value = ""
  } catch (value) {
    refineError.value = getErrorMessage(value, refineWorkbenchCopy.value.resetMemory)
  } finally {
    refineSessionPending.value = false
  }
}

function schedulePendingImageRefresh() {
  if (timer !== null || isJobRunning.value || !hasPendingItemImages.value) {
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

async function pollJob(jobId: string, kind: "generate" | "refine" | "export" | "image_enrich") {
  stopPolling()

  try {
    activeJob.value = await api.getJob(jobId)
    if (cancelRequestedJobIds.has(jobId) && activeJob.value.status !== "cancelled") {
      return
    }
    if (isTerminalJobStatus(activeJob.value.status)) {
      if ((kind === "generate" || kind === "refine") && activeJob.value.status === "completed") {
        const followupJobId = String(activeJob.value.result?.followup_job_id ?? "").trim()
        if (followupJobId) {
          await pollJob(followupJobId, "image_enrich")
          return
        }
      }
      await loadTrip(false)
      if (activeJob.value.status === "failed") {
        const message = isDebug.value
          ? (activeJob.value.error_message?.trim() || "任务未完成")
          : jobPresentation(activeJob.value).detail
        if (kind === "generate") {
          generateError.value = message
        } else if (kind === "refine") {
          refineError.value = message
        } else if (kind === "image_enrich") {
          imageEnrichError.value = message
        } else if (kind === "export") {
          exportError.value = message
        }
      }
      if (kind !== "export" && activeJob.value.status !== "cancelled") {
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
    } else if (kind === "refine") {
      refineError.value = message
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

    const job = await api.generateTrip(tripId.value)
    activeJob.value = job
    await pollJob(job.job_id, "generate")
  } catch (value) {
    const message = getErrorMessage(value, t("tripDetail.generationFailedTitle"))
    generateError.value = message
  } finally {
    generatePending.value = false
  }
}

async function resumeFailedGeneration() {
  const failedJobId = activeJob.value?.job_id
  if (!failedJobId || !canResumeGeneration.value) {
    return
  }

  resumeGeneratePending.value = true
  resumeGenerateError.value = null
  generateError.value = null

  try {
    const job = await api.retryJob(failedJobId)
    activeJob.value = job
    await pollJob(job.job_id, "generate")
  } catch (value) {
    resumeGenerateError.value = getErrorMessage(value, copy.value.resumeGenerationFailedTitle)
  } finally {
    resumeGeneratePending.value = false
  }
}

async function cancelActiveJob() {
  const job = activeJob.value
  if (!job || !canCancelActiveJob.value || cancelJobPending.value || !window.confirm(cancelJobConfirmMessage.value)) {
    return
  }

  cancelJobPending.value = true
  cancelJobError.value = null
  cancelRequestedJobIds.add(job.job_id)
  try {
    const cancelledJob = await api.cancelJob(job.job_id)
    stopPolling()
    activeJob.value = cancelledJob
    await loadTrip(false)
  } catch (value) {
    cancelRequestedJobIds.delete(job.job_id)
    cancelJobError.value = getErrorMessage(value, cancelJobFailedTitle.value)
  } finally {
    cancelJobPending.value = false
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
    const job = await api.refineTrip(tripId.value, payload)
    activeJob.value = job
    await pollJob(job.job_id, "refine")
    await loadRefineContext()
  } catch (value) {
    const message = getErrorMessage(value, t("tripDetail.asyncFailedTitle"))
    refineError.value = message
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
    const job = await api.enrichTripImages(tripId.value, true)
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
    cancelJobError.value = null
    cancelRequestedJobIds.clear()
    exportError.value = null
    imageEnrichError.value = null
    refineError.value = null
    searchError.value = null
    communityError.value = null
    communityNotice.value = null
    searchResults.value = []
    hasSearched.value = false
    refineSession.value = null
    refineCommunityPosts.value = []
    refineGuideTitle.value = ""
    refineGuideContent.value = ""
    selectedCommunityPostId.value = ""
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
      stageMessage: jobPresentation(currentJob).label
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
  <div class="tm-detail tm-detail--portal" :class="{ 'tm-detail--journey': isJourneyView }">
    <StatePanel v-if="loading" kind="loading" :title="t('tripDetail.loadingTitle')" :message="t('tripDetail.loadingMessage')" />
    <StatePanel v-else-if="error" kind="error" :title="t('tripDetail.unavailableTitle')" :message="error" :action-label="t('common.retry')" @action="loadTrip(true)" />

    <template v-else-if="trip">
      <!-- Header -->
      <header class="tm-detail__header">
        <div class="tm-detail__header-info">
          <p class="tm-detail__kicker">{{ `${trip.origin} → ${trip.destination}` }}</p>
          <h1 class="tm-detail__title">{{ trip.title }}</h1>
          <div class="tm-detail__meta">
            <span>{{ formatDateRange(trip.start_date, trip.end_date) }}</span>
            <span>{{ t('common.budgetValue', { value: formatCurrency(trip.budget) }) }}</span>
            <span>{{ t('common.travelersCount', { count: trip.travelers }) }}</span>
            <span>{{ t('common.paceValue', { value: paceLabel(trip.pace) }) }}</span>
          </div>
        </div>
        <div class="tm-detail__header-actions">
          <TmButton variant="primary" :disabled="actionLocked || !canGenerate" :loading="generatePending" @click="generate">
            {{ generatePending ? t('common.generating') : t('common.generateItinerary') }}
          </TmButton>
          <TmButton variant="secondary" :disabled="!hasItinerary || actionLocked || !canUseModel" @click="openRefineModal">
            {{ copy.quickRefineTitle }}
          </TmButton>
          <TmButton variant="secondary" :disabled="!hasItinerary || communityActionLocked" :loading="communityPending" @click="openCommunityEditor(communityPublication ? 'edit' : 'create')">
            {{ communityPublication ? communityCopy.editAction : communityCopy.publishAction }}
          </TmButton>
          <TmButton variant="secondary" :disabled="!hasItinerary || actionLocked" :loading="exportPending" @click="exportPdf">
            {{ exportPending ? exportActionRunningLabel : exportActionLabel }}
          </TmButton>
          <TmButton variant="danger" :disabled="actionLocked || deletePending" :loading="deletePending" @click="removeTrip">
            {{ deletePending ? deletingTripLabel : deleteTripLabel }}
          </TmButton>
        </div>
      </header>

      <div v-if="shouldDisplayItinerary" class="tm-detail__view-switch">
        <div role="group" :aria-label="locale === 'zh-CN' ? '行程展示方式' : 'Itinerary display'">
          <button type="button" :aria-pressed="isJourneyView" :disabled="itineraryEditorOpen" @click="itineraryView = 'flow'">{{ locale === 'zh-CN' ? '流动旅程' : 'Journey flow' }}</button>
          <button type="button" :aria-pressed="!isJourneyView" @click="itineraryView = 'list'">{{ locale === 'zh-CN' ? '完整清单' : 'Full itinerary' }}</button>
        </div>
        <button v-if="isJourneyView" type="button" :disabled="actionLocked" @click="editFromJourney">{{ itineraryEditorCopy.editAction }} ↗</button>
      </div>
      <div v-if="isJourneyView && activeJob" class="tm-detail__journey-job" role="status">
        <JobProgressSummary :job="activeJob" compact /><button type="button" @click="itineraryView = 'list'">查看处理进度 ↗</button>
      </div>
      <!-- Overview metrics -->
      <section v-if="shouldDisplayItinerary && !isJourneyView" id="overview" class="tm-detail__overview">
        <p class="tm-detail__section-kicker">{{ copy.overviewKicker }}</p>
        <h2 class="tm-detail__section-title">{{ trip.itinerary?.summary }}</h2>
        <div class="tm-detail__metrics">
          <TmMetricCard v-for="metric in itineraryMetrics" :key="metric.label" :label="metric.label" :value="metric.value" />
        </div>
      </section>

      <!-- Anchor nav -->
      <TmAnchorNav v-if="!isJourneyView" :items="anchorSections" />

      <!-- Status notices -->
      <LlmStatusNotice v-if="isDebug && !isJourneyView" compact />
      <StatePanel v-if="isDebug && !isJourneyView" :kind="actualExecutionKind" :title="currentModeTitle" :message="currentModeMessage" compact />
      <StatePanel v-if="generateError" kind="error" :title="t('tripDetail.generationFailedTitle')" :message="isDebug ? generateError : publicJobError(generateError)" compact />
      <StatePanel v-if="resumeGenerateError" kind="error" :title="copy.resumeGenerationFailedTitle" :message="isDebug ? resumeGenerateError : publicJobError(resumeGenerateError)" compact />
      <StatePanel v-if="cancelJobError" kind="error" :title="cancelJobFailedTitle" :message="isDebug ? cancelJobError : publicJobError(cancelJobError)" compact />
      <StatePanel v-if="refineError" kind="error" :title="copy.quickRefineTitle" :message="isDebug ? refineError : publicJobError(refineError)" compact />
      <StatePanel v-if="exportError" kind="error" :title="t('tripDetail.exportFailedTitle')" :message="isDebug ? exportError : publicJobError(exportError)" compact />
      <StatePanel v-if="imageEnrichError" kind="error" :title="copy.enrichImagesActionLabel" :message="isDebug ? imageEnrichError : publicJobError(imageEnrichError)" compact />
      <StatePanel v-if="itinerarySaveError" kind="error" :title="itineraryEditorCopy.saveFailedTitle" :message="itinerarySaveError" compact />
      <StatePanel v-if="itinerarySaveNotice" kind="info" :title="itineraryEditorCopy.saveAction" :message="itinerarySaveNotice" compact />
      <StatePanel v-if="deleteError" kind="error" :title="deleteTripFailedTitle" :message="deleteError" compact />
      <StatePanel v-if="communityError" kind="error" :title="communityCopy.title" :message="communityError" compact />
      <StatePanel v-if="communityNotice" kind="info" :title="communityCopy.title" :message="communityNotice" compact />

      <TripJourneyFlow v-if="isJourneyView && trip.itinerary" :itinerary="trip.itinerary" :start-date="trip.start_date" @inspect="showFullStop" />
      <details v-if="isDebug && isJourneyView" class="tm-detail__journey-settings"><summary>{{ locale === 'zh-CN' ? '模型状态与设置' : 'Model status and settings' }}</summary><LlmStatusNotice compact /></details>

      <!-- Main body: single column -->
      <div v-show="!isJourneyView" class="tm-detail__body">
        <div class="tm-detail__main">

          <!-- Job status -->
          <section id="job" class="tm-detail__section">
            <TmAuroraPanel :active="isJobRunning" :completed="activeJob?.status === 'completed'">
              <div class="tm-detail__section-header">
                <p class="tm-detail__section-kicker">{{ copy.currentJob }}</p>
                <h2 class="tm-detail__section-title">{{ activeJob ? formatJobType(activeJob.type) : copy.noActiveJob }}</h2>
                <p v-if="isDebug" class="tm-detail__section-desc">{{ activeJob ? activeJob.job_id : noActiveJobMessage }}</p>
              </div>
              <div class="tm-detail__section-actions">
                <TmButton v-if="canCancelActiveJob || cancelJobPending" variant="danger" size="sm" :disabled="!canCancelActiveJob" :loading="cancelJobPending" @click="cancelActiveJob">
                  {{ cancelJobPending ? cancelJobRunningLabel : cancelJobActionLabel }}
                </TmButton>
                <TmButton v-if="canResumeGeneration || resumeGeneratePending" variant="primary" size="sm" :disabled="!canResumeGeneration" :loading="resumeGeneratePending" @click="resumeFailedGeneration">
                  {{ resumeGeneratePending ? copy.resumeGenerationRunningLabel : copy.resumeGenerationActionLabel }}
                </TmButton>
                <TmButton v-if="hasItinerary && !isJobRunning && !auth.user?.generation_quota" variant="ghost" size="sm" :disabled="!canRetryImageEnrichment" :loading="imageEnrichPending" @click="retryImageEnrichment">
                  {{ imageEnrichPending ? copy.enrichImagesActionRunningLabel : copy.enrichImagesActionLabel }}
                </TmButton>
              </div>

              <StatePanel v-if="!activeJob" kind="info" :title="copy.noActiveJob" :message="noActiveJobMessage" compact />

              <template v-else>
                <JobProgressSummary :job="activeJob" />
                <details v-if="isDebug" class="tm-detail__diagnostics">
                  <summary>任务诊断（仅供调试）</summary>
                <div class="tm-detail__metrics">
                  <TmMetricCard :label="copy.stageLabel" :value="formatStage(activeJob.stage)" />
                  <TmMetricCard :label="copy.progressLabel" :value="formatProgress(activeJob.progress_percent, activeJob.status)" />
                  <TmMetricCard :label="copy.updatedLabel" :value="formatDateTime(activeJob.updated_at)" />
                </div>

                <TmProgressTrack :value="jobProgress" :label="copy.progressLabel" :variant="isJobRunning ? 'aurora' : 'default'" />

                <p class="tm-detail__muted">{{ fieldValue(activeJob.stage_message) }}</p>
                <p v-if="imageJobBackendHint" class="tm-detail__muted">{{ imageJobBackendHint }}</p>
                <p v-if="imageEnrichmentStatusSummary" class="tm-detail__muted">{{ imageEnrichmentStatusSummary }}</p>

                <!-- Image debug -->
                <div
                  v-if="activeJob.type === 'trip.image_enrich' && (imageEnrichmentDebugRows.length || imageQueryNotes.length || imageCandidateDebugNotes.length || imageReviewerDebugNotes.length)"
                  class="tm-detail__subsection"
                >
                  <div class="tm-detail__subsection-header">
                    <h3>{{ imageDebugTitle }}</h3>
                    <span class="tm-detail__muted">{{ imageEnrichmentDebugRows.length }}</span>
                  </div>

                  <div v-if="imageEnrichmentDebugRows.length" class="tm-detail__debug-grid">
                    <article v-for="row in imageEnrichmentDebugRows" :key="row.item_id" class="tm-detail__debug-card">
                      <div class="tm-detail__debug-card-header">
                        <strong>{{ row.name || row.item_id }}</strong>
                        <StatusPill :status="row.status" />
                      </div>
                      <p class="tm-detail__muted">{{ imageDebugSummaryTitle }}: {{ row.priority_tier || copy.notAvailable }}</p>
                      <p class="tm-detail__muted">{{ locale === 'zh-CN' ? `图片 ${row.image_count ?? 0} 张，来源 ${row.source_count ?? 0} 条。` : `${row.image_count ?? 0} images, ${row.source_count ?? 0} sources.` }}</p>
                      <p v-if="row.failure_reason" class="tm-detail__muted">{{ row.failure_reason }}</p>
                    </article>
                  </div>

                  <div v-if="imageQueryNotes.length" class="tm-detail__subsection">
                    <p class="tm-detail__kicker">{{ imageDebugQueriesTitle }}</p>
                    <ul class="tm-detail__list">
                      <li v-for="note in imageQueryNotes" :key="note">{{ note }}</li>
                    </ul>
                  </div>
                  <div v-if="imageCandidateDebugNotes.length" class="tm-detail__subsection">
                    <p class="tm-detail__kicker">{{ imageDebugCandidatesTitle }}</p>
                    <ul class="tm-detail__list">
                      <li v-for="note in imageCandidateDebugNotes" :key="note">{{ note }}</li>
                    </ul>
                  </div>
                  <div v-if="imageReviewerDebugNotes.length" class="tm-detail__subsection">
                    <p class="tm-detail__kicker">{{ imageDebugReviewerTitle }}</p>
                    <ul class="tm-detail__list">
                      <li v-for="note in imageReviewerDebugNotes" :key="note">{{ note }}</li>
                    </ul>
                  </div>
                  <p v-if="!imageEnrichmentDebugRows.length && !imageQueryNotes.length && !imageCandidateDebugNotes.length && !imageReviewerDebugNotes.length" class="tm-detail__muted">
                    {{ imageDebugEmptyMessage }}
                  </p>
                </div>

                <!-- Timeline -->
                <div class="tm-detail__subsection">
                  <div class="tm-detail__subsection-header">
                    <h3>{{ copy.timelineTitle }}</h3>
                    <span class="tm-detail__muted">{{ jobTimeline.length }}</span>
                  </div>
                  <StatePanel v-if="jobTimeline.length === 0" kind="info" :title="copy.timelineEmptyTitle" :message="copy.timelineEmptyMessage" compact />
                  <ol v-else class="tm-detail__timeline">
                    <li v-for="entry in jobTimeline" :key="`${entry.recorded_at}-${entry.status}-${entry.stage ?? 'none'}`" class="tm-detail__timeline-item">
                      <div class="tm-detail__timeline-meta">
                        <StatusPill :status="entry.status" />
                        <span class="tm-detail__muted">{{ formatStage(entry.stage) }}</span>
                        <span class="tm-detail__muted">{{ formatDateTime(entry.recorded_at) }}</span>
                      </div>
                      <p>{{ fieldValue(entry.stage_message) }}</p>
                    </li>
                  </ol>
                </div>
                </details>
              </template>
            </TmAuroraPanel>
          </section>

          <!-- Planning brief -->
          <section id="brief" class="tm-detail__section">
            <div class="tm-detail__section-header">
              <p class="tm-detail__section-kicker">{{ copy.briefKicker }}</p>
              <h2 class="tm-detail__section-title">{{ copy.briefTitle }}</h2>
              <p class="tm-detail__section-desc">{{ copy.briefDescription }}</p>
            </div>
            <dl class="tm-detail__data-grid">
              <div v-for="field in planningBriefFields" :key="field.label" class="tm-detail__data-pair">
                <dt>{{ field.label }}</dt>
                <dd>{{ field.value }}</dd>
              </div>
            </dl>
            <div class="tm-detail__subsection">
              <p class="tm-detail__kicker">{{ copy.interestsLabel }}</p>
              <div class="tm-detail__chips">
                <span v-if="tripInterests.length === 0" class="tm-detail__chip">{{ copy.noInterests }}</span>
                <span v-for="interest in tripInterests" :key="interest" class="tm-detail__chip">{{ interest }}</span>
              </div>
            </div>
          </section>

          <!-- Budget -->
          <section v-if="budgetSummary" id="budget" class="tm-detail__section">
            <p v-if="budgetSummary.incomplete" class="tm-detail__section-desc">
              尚有未计价费用，当前余额仅供参考：{{ budgetSummary.unpriced_items?.join("、") }}
            </p>
            <div class="tm-detail__section-header">
              <p class="tm-detail__section-kicker">{{ budgetPanelTitle }}</p>
              <h2 class="tm-detail__section-title">{{ budgetPanelTitle }}</h2>
              <p class="tm-detail__section-desc">{{ budgetPanelDescription }}</p>
            </div>
            <div class="tm-detail__metrics">
              <TmMetricCard v-for="metric in budgetMetrics" :key="metric.label" :label="metric.label" :value="metric.value" />
            </div>
            <div class="tm-detail__metrics">
              <TmMetricCard v-for="category in budgetBreakdownCards" :key="category.key" :label="category.label" :value="category.value" />
            </div>
            <div class="tm-detail__subsection">
              <h3>{{ budgetLineItemsTitle }}</h3>
              <ul class="tm-detail__list">
                <li v-for="item in budgetLineItems" :key="item.key">
                  {{ formatBudgetLineItemTitle(item.title, item.note) }} · {{ formatCurrency(item.amount) }}
                </li>
              </ul>
            </div>
          </section>

          <!-- Transport & Booking -->
          <section v-if="stayRecommendation || transportBookingSummary || reservationEntries.length" id="booking" class="tm-detail__section">
            <div class="tm-detail__section-header">
              <p class="tm-detail__section-kicker">{{ bookingPanelTitle }}</p>
              <h2 class="tm-detail__section-title">{{ bookingPanelTitle }}</h2>
              <p class="tm-detail__section-desc">{{ bookingPanelDescription }}</p>
            </div>
            <div v-if="stayRecommendation" class="tm-detail__subsection">
              <h3>{{ stayPanelTitle }}</h3>
              <dl v-if="stayHotelFields.length" class="tm-detail__data-grid">
                <div v-for="field in stayHotelFields" :key="field.label" class="tm-detail__data-pair">
                  <dt>{{ field.label }}</dt>
                  <dd>{{ field.value }}</dd>
                </div>
              </dl>
              <div v-if="stayHighlights.length" class="tm-detail__chips">
                <span v-for="note in stayHighlights" :key="note" class="tm-detail__chip">{{ note }}</span>
              </div>
              <ul v-if="stayCandidateRows.length" class="tm-detail__list">
                <li v-for="candidate in stayCandidateRows" :key="candidate.name">
                  <strong>{{ candidate.name }}</strong>
                  <span v-if="candidate.area"> · {{ candidate.area }}</span>
                  <span v-if="candidate.price_hint"> · {{ candidate.price_hint }}</span>
                  <p v-if="candidate.reason || candidate.preference_match" class="tm-detail__muted">{{ candidate.preference_match || candidate.reason }}</p>
                </li>
              </ul>
              <div v-if="staySourceUrls.length" class="tm-detail__inline-links">
                <a v-for="url in staySourceUrls" :key="url" class="tm-detail__link" :href="url" target="_blank" rel="noreferrer">{{ copy.sourceOpen }}</a>
              </div>
            </div>
            <div v-if="transportBookingSummary" class="tm-detail__subsection">
              <h3>{{ transportBookingTitle }}</h3>
              <dl class="tm-detail__data-grid">
                <div v-for="field in transportBookingFields" :key="field.label" class="tm-detail__data-pair">
                  <dt>{{ field.label }}</dt>
                  <dd>{{ field.value }}</dd>
                </div>
              </dl>
              <div v-if="transportBookingHighlights.length" class="tm-detail__chips">
                <span v-for="note in transportBookingHighlights" :key="note" class="tm-detail__chip">{{ note }}</span>
              </div>
              <ul v-if="transportServiceCandidates.length" class="tm-detail__list">
                <li v-for="candidate in transportServiceCandidates" :key="`${candidate.scope}-${candidate.service_number}-${candidate.departure_date}`">
                  <strong>{{ candidate.scope === "return" ? "返程" : "去程" }} · {{ candidate.service_number }}</strong>
                  <span> · {{ candidate.origin }} {{ candidate.departure_time }} → {{ candidate.destination }} {{ candidate.arrival_time }}</span>
                  <span v-if="candidate.fare_class || candidate.fare_amount"> · {{ candidate.fare_class || "参考票价" }} {{ typeof candidate.fare_amount === "number" ? formatCurrency(candidate.fare_amount) : "待确认" }}</span>
                  <p class="tm-detail__muted">
                    {{ candidate.schedule_status === "date_specific" ? "指定日期计划时刻" : "静态参考时刻" }}
                    · {{ candidate.evidence_status === "verified" ? "来源正文已复核" : candidate.evidence_status === "referenced" ? "有来源，正文待复核" : candidate.evidence_status === "conflicted" ? "来源存在冲突" : "未记录复核状态" }}
                    · 余票/实时状态{{ candidate.availability_status === "unknown" ? "未核验" : candidate.availability_status }}
                    · 查询于 {{ candidate.schedule_checked_at }}
                  </p>
                  <p v-if="candidate.evidence_reason" class="tm-detail__muted">{{ candidate.evidence_reason }}</p>
                  <a class="tm-detail__link" :href="candidate.source_url" target="_blank" rel="noreferrer">{{ copy.sourceOpen }}</a>
                </li>
              </ul>
              <a v-if="transportBookingSummary.official_booking_url" class="tm-detail__link" :href="transportBookingSummary.official_booking_url" target="_blank" rel="noreferrer">{{ copy.sourceOpen }}</a>
            </div>
            <div v-if="reservationEntries.length" class="tm-detail__subsection">
              <h3>{{ reservationChecklistTitle }}</h3>
              <ul class="tm-detail__list">
                <li v-for="entry in reservationEntries" :key="entry.key">
                  <strong>{{ entry.title }}</strong>
                  <ul class="tm-detail__list--nested">
                    <li v-for="line in entry.lines" :key="`${entry.key}-${line}`">{{ line }}</li>
                  </ul>
                  <a v-if="entry.officialUrl" class="tm-detail__link" :href="entry.officialUrl" target="_blank" rel="noreferrer">{{ copy.sourceOpen }}</a>
                </li>
              </ul>
            </div>
          </section>

          <!-- Itinerary -->
          <section id="itinerary" class="tm-detail__section">
            <div class="tm-detail__section-header">
              <p class="tm-detail__section-kicker">{{ t('tripDetail.itineraryKicker') }}</p>
              <h2 class="tm-detail__section-title">{{ copy.itineraryPanelTitle }}</h2>
              <p class="tm-detail__section-desc">{{ copy.itineraryPanelDescription }}</p>
            </div>

            <div v-if="shouldDisplayItinerary" class="tm-detail__section-actions">
              <template v-if="itineraryEditorOpen">
                <TmButton variant="primary" :disabled="itinerarySavePending" :loading="itinerarySavePending" @click="saveItineraryEditor">
                  {{ itinerarySavePending ? itineraryEditorCopy.savingAction : itineraryEditorCopy.saveAction }}
                </TmButton>
                <TmButton variant="ghost" :disabled="itinerarySavePending" @click="cancelItineraryEditor">
                  {{ itineraryEditorCopy.cancelAction }}
                </TmButton>
              </template>
              <TmButton v-else variant="secondary" :disabled="actionLocked" @click="openItineraryEditor">
                {{ itineraryEditorCopy.editAction }}
              </TmButton>
            </div>

            <template v-if="itineraryEditorOpen && itineraryDraft">
              <div class="tm-detail__editor">
                <TmTextarea
                  id="itinerary-summary"
                  :model-value="itineraryDraft.summary"
                  :label="itineraryEditorCopy.summaryLabel"
                  :rows="3"
                  required
                  @update:model-value="updateItineraryDraftSummary"
                />
                <TmTextarea
                  id="itinerary-risks"
                  :model-value="itineraryDraftRisksText"
                  :label="itineraryEditorCopy.risksLabel"
                  :hint="itineraryEditorCopy.risksHint"
                  :rows="3"
                  @update:model-value="updateItineraryDraftRisks"
                />

                <div class="tm-detail__days">
                  <article v-for="(day, dayIndex) in itineraryDraft.days" :key="`edit-day-${day.day_index}`" class="tm-detail__day-card tm-detail__day-card--editing">
                    <div class="tm-detail__day-header">
                      <div>
                        <p class="tm-detail__kicker">{{ t('common.daysLabel', { day: dayIndex + 1, title: day.title }) }}</p>
                        <h3 class="tm-detail__day-title">{{ day.title }}</h3>
                      </div>
                      <div class="tm-detail__section-actions">
                        <TmButton variant="ghost" size="sm" :disabled="itinerarySavePending" @click="addItineraryDraftItem(day)">
                          {{ itineraryEditorCopy.addStopAction }}
                        </TmButton>
                        <TmButton variant="ghost" size="sm" :disabled="itinerarySavePending || itineraryDraft.days.length <= 1" @click="removeItineraryDraftDay(dayIndex)">
                          {{ itineraryEditorCopy.removeDayAction }}
                        </TmButton>
                      </div>
                    </div>

                    <div class="tm-detail__editor-grid">
                      <TmField
                        :id="`day-${dayIndex}-title`"
                        :model-value="day.title"
                        :label="itineraryEditorCopy.dayTitleLabel"
                        required
                        @update:model-value="(v: string | number) => day.title = String(v)"
                      />
                      <TmField
                        :id="`day-${dayIndex}-cost`"
                        type="number"
                        :min="0"
                        :model-value="day.total_cost"
                        :label="itineraryEditorCopy.dayCostLabel"
                        @update:model-value="(v: string | number) => day.total_cost = normalizeDraftAmount(v)"
                      />
                      <TmTextarea
                        class="tm-detail__editor-wide"
                        :id="`day-${dayIndex}-summary`"
                        :model-value="day.summary"
                        :label="itineraryEditorCopy.daySummaryLabel"
                        :rows="3"
                        @update:model-value="(v: string) => day.summary = v"
                      />
                    </div>

                    <ol class="tm-detail__editor-items">
                      <li v-for="(item, itemIndex) in day.items" :key="`${item.id}-${itemIndex}`" class="tm-detail__editor-item">
                        <div class="tm-detail__editor-item-header">
                          <p class="tm-detail__kicker">{{ itineraryEditorCopy.stopLabel }} {{ itemIndex + 1 }}</p>
                          <TmButton variant="ghost" size="sm" :disabled="itinerarySavePending || day.items.length <= 1" @click="removeItineraryDraftItem(day, itemIndex)">
                            {{ itineraryEditorCopy.removeStopAction }}
                          </TmButton>
                        </div>
                        <div class="tm-detail__editor-grid tm-detail__editor-grid--item">
                          <TmField
                            :id="`day-${dayIndex}-item-${itemIndex}-name`"
                            :model-value="item.name"
                            :label="itineraryEditorCopy.itemNameLabel"
                            required
                            @update:model-value="(v: string | number) => item.name = String(v)"
                          />
                          <TmSelect
                            :id="`day-${dayIndex}-item-${itemIndex}-type`"
                            :model-value="item.type"
                            :label="itineraryEditorCopy.itemTypeLabel"
                            :options="itineraryItemTypeOptions"
                            required
                            @update:model-value="(v: string) => item.type = v"
                          />
                          <TmField
                            :id="`day-${dayIndex}-item-${itemIndex}-start`"
                            :model-value="item.start_time"
                            :label="itineraryEditorCopy.itemStartLabel"
                            required
                            @update:model-value="(v: string | number) => item.start_time = String(v)"
                          />
                          <TmField
                            :id="`day-${dayIndex}-item-${itemIndex}-end`"
                            :model-value="item.end_time"
                            :label="itineraryEditorCopy.itemEndLabel"
                            required
                            @update:model-value="(v: string | number) => item.end_time = String(v)"
                          />
                          <TmField
                            :id="`day-${dayIndex}-item-${itemIndex}-location`"
                            :model-value="item.location"
                            :label="itineraryEditorCopy.itemLocationLabel"
                            @update:model-value="(v: string | number) => item.location = String(v)"
                          />
                          <TmField
                            :id="`day-${dayIndex}-item-${itemIndex}-score`"
                            type="number"
                            :min="0"
                            :max="1"
                            :model-value="item.score"
                            :label="itineraryEditorCopy.itemScoreLabel"
                            @update:model-value="(v: string | number) => item.score = normalizeDraftScore(v)"
                          />
                          <TmTextarea
                            class="tm-detail__editor-wide"
                            :id="`day-${dayIndex}-item-${itemIndex}-note`"
                            :model-value="item.note"
                            :label="itineraryEditorCopy.itemNoteLabel"
                            :rows="3"
                            @update:model-value="(v: string) => item.note = v"
                          />
                        </div>
                      </li>
                    </ol>
                  </article>
                </div>

                <div class="tm-detail__section-actions">
                  <TmButton variant="secondary" :disabled="itinerarySavePending" @click="addItineraryDraftDay">
                    {{ itineraryEditorCopy.addDayAction }}
                  </TmButton>
                </div>
              </div>
            </template>

            <template v-else>
              <StatePanel v-if="trip.itinerary && hasPendingItemImages" kind="loading" :title="pendingImageDisplayTitle" :message="pendingImageDisplayMessage" compact />

              <ul v-if="shouldDisplayItinerary && trip.itinerary?.risks?.length" class="tm-detail__risk-list">
                <li v-for="risk in trip.itinerary.risks" :key="risk">{{ risk }}</li>
              </ul>

              <!-- Referenced visuals -->
              <section v-if="shouldDisplayItinerary && citedXhsVisualDocs.length" class="tm-detail__visuals">
                <span class="tm-detail__badge">{{ locale === "zh-CN" ? "参考风景图" : "Referenced visuals" }}</span>
                <div class="tm-detail__visual-grid">
                  <article v-for="doc in citedXhsVisualDocs" :key="doc.id" class="tm-detail__visual-card">
                    <div class="tm-detail__visual-card-header">
                      <strong>{{ doc.place_name || doc.title }}</strong>
                      <a class="tm-detail__link" :href="doc.url" target="_blank" rel="noreferrer">{{ copy.sourceOpen }}</a>
                    </div>
                    <p v-if="doc.author || doc.published_at" class="tm-detail__muted">
                      {{ [doc.author, doc.published_at ? formatDateTime(doc.published_at) : null].filter(Boolean).join(" · ") }}
                    </p>
                    <div class="tm-detail__visual-images">
                      <img v-for="imageUrl in (doc.image_urls ?? []).slice(0, 3)" :key="imageUrl" :src="imageUrl" :alt="doc.title" loading="lazy" />
                    </div>
                  </article>
                </div>
              </section>

              <!-- Day cards -->
              <div v-if="shouldDisplayItinerary" class="tm-detail__days">
                <article v-for="day in trip.itinerary?.days ?? []" :key="day.day_index" class="tm-detail__day-card">
                  <div class="tm-detail__day-header">
                    <div>
                      <p class="tm-detail__kicker">{{ t('common.daysLabel', { day: day.day_index, title: day.title }) }}</p>
                      <h3 class="tm-detail__day-title">{{ day.title }}</h3>
                    </div>
                    <strong class="tm-detail__day-cost">{{ formatCurrency(day.total_cost) }}</strong>
                  </div>
                  <p class="tm-detail__day-summary">{{ day.summary }}</p>
                  <section v-if="day.flexible_windows?.length" class="tm-detail__weather" aria-label="Flexible time windows">
                    <span class="tm-detail__badge">{{ locale === "zh-CN" ? "自由与弹性时间" : "Flexible time" }}</span>
                    <p v-for="(window, wi) in day.flexible_windows" :key="`${day.day_index}-flex-${wi}`">
                      <strong>{{ window.start_time }}—{{ window.end_time }}</strong> · {{ window.note }}
                    </p>
                  </section>

                  <section v-if="day.weather" class="tm-detail__weather">
                    <span class="tm-detail__badge">{{ locale === "zh-CN" ? "天气" : "Weather" }}</span>
                    <p>{{ day.weather.summary }}</p>
                    <p v-if="day.weather.condition || day.weather.temperature_min_c || day.weather.temperature_max_c || day.weather.precipitation_probability || day.weather.wind" class="tm-detail__muted">
                      {{ [
                        day.weather.condition,
                        day.weather.temperature_min_c || day.weather.temperature_max_c ? `${day.weather.temperature_min_c || "?"}–${day.weather.temperature_max_c || "?"}°C` : null,
                        day.weather.precipitation_probability ? `降水概率 ${day.weather.precipitation_probability}` : null,
                        day.weather.wind
                      ].filter(Boolean).join(" · ") }}
                    </p>
                    <p v-if="day.weather.checked_at" class="tm-detail__muted">
                      {{ day.weather.forecast_type === "seasonal_reference" ? "季节性参考" : "逐日预报快照" }}
                      · {{ day.weather.evidence_status === "verified" ? "来源正文已复核" : day.weather.evidence_status === "referenced" ? "有来源，正文待复核" : day.weather.evidence_status === "conflicted" ? "部分字段与来源冲突" : "未记录复核状态" }}
                      · 查询于 {{ day.weather.checked_at }}<span v-if="day.weather.forecast_updated_at && day.weather.forecast_updated_at !== 'unknown'"> · 来源更新于 {{ day.weather.forecast_updated_at }}</span>
                    </p>
                    <p v-if="day.weather.evidence_reason" class="tm-detail__muted">{{ day.weather.evidence_reason }}</p>
                    <ul v-if="day.weather.notes.length" class="tm-detail__list--nested">
                      <li v-for="note in day.weather.notes" :key="note">{{ note }}</li>
                    </ul>
                    <div v-if="day.weather.citations?.length" class="tm-detail__chips tm-detail__weather-sources">
                      <a
                        v-for="(sourceUrl, sourceIndex) in day.weather.citations.slice(0, 3)"
                        :key="`${day.day_index}-weather-${sourceUrl}`"
                        class="tm-detail__link"
                        :href="sourceUrl"
                        target="_blank"
                        rel="noreferrer"
                      >{{ locale === "zh-CN" ? `天气来源 ${sourceIndex + 1}` : `Weather source ${sourceIndex + 1}` }}</a>
                    </div>
                  </section>

                  <ol class="tm-detail__items">
                    <li v-for="item in day.items" :id="`itinerary-stop-${day.day_index}-${item.id}`" :key="item.id" class="tm-detail__item" tabindex="-1">
                      <div class="tm-detail__item-time">
                        {{ item.start_time }} - {{ item.end_day_offset ? '+' + item.end_day_offset + '天 ' : '' }}{{ item.end_time }}
                        <span
                          v-if="['transport', 'transit', 'rail', 'flight', 'ferry'].includes(item.type.toLowerCase()) && item.booking_info && !item.booking_info.schedule_verified && ['reference', 'date_specific'].includes(item.booking_info.schedule_status || '')"
                        >（{{ item.booking_info.evidence_status === 'verified' ? '来源正文已复核' : '正文待复核' }}，运行/余票待确认）</span>
                        <span
                          v-else-if="['transport', 'transit', 'rail', 'flight', 'ferry'].includes(item.type.toLowerCase()) && item.booking_info && !item.booking_info.schedule_verified"
                        >（建议时段，班次待确认）</span>
                      </div>
                      <div class="tm-detail__item-body">
                        <div class="tm-detail__item-topline">
                          <strong>{{ item.name }}</strong>
                          <div class="tm-detail__item-badges">
                            <span class="tm-detail__badge">{{ formatItemType(item.type) }}</span>
                            <span v-if="formatImagePriorityTier(item.image_priority_tier)" class="tm-detail__badge" :title="item.image_priority_reason || undefined">{{ formatImagePriorityTier(item.image_priority_tier) }}</span>
                            <StatusPill :status="formatScore(item.score)" />
                          </div>
                        </div>
                        <p class="tm-detail__muted">{{ copy.locationLabel }} · {{ item.location }}</p>
                        <p class="tm-detail__item-note">{{ item.note }}</p>
                        <ul v-if="itemBookingLines(item).length" class="tm-detail__list--nested">
                          <li v-for="line in itemBookingLines(item)" :key="`${item.id}-${line}`">{{ line }}</li>
                        </ul>
                        <section v-if="item.nearby_suggestions?.length" class="tm-detail__nearby">
                          <p class="tm-detail__nearby-title">附近与同片区备选</p>
                          <ul class="tm-detail__nearby-list">
                            <li v-for="suggestion in item.nearby_suggestions" :key="`${item.id}-nearby-${suggestion.name}`" class="tm-detail__nearby-item">
                              <div>
                                <strong>{{ suggestion.name }}</strong>
                                <span v-if="suggestion.area || suggestion.suggested_time" class="tm-detail__muted">
                                  · {{ [suggestion.area, suggestion.suggested_time].filter(Boolean).join(' · ') }}
                                </span>
                                <span class="tm-detail__badge">{{ suggestion.relation_type === 'suggested_pair' ? '推荐搭配' : '同片区备选' }}</span>
                              </div>
                              <p v-if="suggestion.reason">{{ suggestion.reason }}</p>
                              <p v-if="suggestion.relation_note" class="tm-detail__muted">{{ suggestion.relation_note }}</p>
                              <p v-if="suggestion.highlights?.length" class="tm-detail__muted">看点：{{ suggestion.highlights.join('、') }}</p>
                              <div v-if="suggestion.source_urls?.length" class="tm-detail__chips">
                                <a
                                  v-for="(sourceUrl, sourceIndex) in suggestion.source_urls"
                                  :key="`${item.id}-${suggestion.name}-${sourceUrl}`"
                                  class="tm-detail__link"
                                  :href="sourceUrl"
                                  target="_blank"
                                  rel="noreferrer"
                                >参考来源 {{ sourceIndex + 1 }}</a>
                              </div>
                            </li>
                          </ul>
                        </section>
                        <a v-if="item.booking_info?.official_booking_url" class="tm-detail__link" :href="item.booking_info.official_booking_url" target="_blank" rel="noreferrer">{{ copy.sourceOpen }}</a>
                        <p v-if="formatImageStatus(item.image_status)" class="tm-detail__muted">{{ formatImageStatus(item.image_status) }}</p>
                        <p v-if="item.image_status === 'failed' && item.image_failure_reason" class="tm-detail__muted">{{ item.image_failure_reason }}</p>
                        <div v-if="item.image_urls?.length" class="tm-detail__visual-images">
                          <PoiImage :urls="item.image_urls" :backups="item.image_backup_urls" :alt="item.name" />
                        </div>
                        <div v-if="item.image_source_urls?.length" class="tm-detail__chips">
                          <a v-for="sourceUrl in item.image_source_urls.slice(0, 3)" :key="`${item.id}-${sourceUrl}`" class="tm-detail__link" :href="sourceUrl" target="_blank" rel="noreferrer">{{ copy.imageSourcesLabel ?? "Source" }}</a>
                        </div>
                      </div>
                    </li>
                  </ol>
                </article>
              </div>
            </template>

            <StatePanel v-if="!trip.itinerary" kind="empty" :title="t('tripDetail.itineraryEmptyTitle')" :message="t('tripDetail.itineraryEmptyMessage')" compact>
              <template #actions>
                <TmButton variant="primary" :disabled="actionLocked || !canGenerate" @click="generate">{{ t('common.generateItinerary') }}</TmButton>
              </template>
            </StatePanel>
          </section>

          <!-- Debug-only panels: search grounding, grounding references, agent pipeline -->
          <template v-if="isDebug">
            <!-- Search grounding -->
            <section id="search" class="tm-detail__section">
              <div class="tm-detail__section-header">
                <p class="tm-detail__section-kicker">{{ copy.searchPanelTitle }}</p>
                <h2 class="tm-detail__section-title">{{ copy.searchPanelTitle }}</h2>
                <p class="tm-detail__section-desc">{{ copy.searchPanelMessage }}</p>
              </div>
              <TmField id="query" :model-value="searchQuery" :label="copy.queryLabel" @update:model-value="(v: string | number) => searchQuery = String(v)" />
              <TmTextarea id="links" :model-value="manualLinks" :label="copy.linksLabel" :rows="2" @update:model-value="(v: string) => manualLinks = v" />
              <div class="tm-detail__section-actions">
                <TmButton variant="primary" :disabled="searchPending" :loading="searchPending" @click="runSearch">
                  {{ searchPending ? copy.searching : copy.runSearch }}
                </TmButton>
              </div>

              <StatePanel v-if="searchError" kind="error" :title="t('tripDetail.searchFailedTitle')" :message="searchError" compact />
              <StatePanel v-else-if="hasSearched && searchResults.length === 0" kind="empty" :title="copy.searchEmptyTitle" :message="copy.searchEmptyMessage" compact />

              <div v-if="searchResults.length" class="tm-detail__search-results">
                <article v-for="doc in searchResults" :key="doc.id" class="tm-detail__search-card">
                  <div class="tm-detail__search-card-header">
                    <div>
                      <p class="tm-detail__kicker">{{ fieldValue(doc.source_type) }}</p>
                      <h3>{{ doc.place_name || doc.title }}</h3>
                    </div>
                    <StatusPill :status="t('common.finalScore', { value: doc.scores.final_score })" />
                  </div>
                  <p class="tm-detail__muted">{{ doc.summary }}</p>
                  <dl class="tm-detail__data-grid">
                    <div class="tm-detail__data-pair"><dt>{{ copy.placeNameLabel }}</dt><dd>{{ fieldValue(doc.place_name || doc.title) }}</dd></div>
                    <div class="tm-detail__data-pair"><dt>{{ copy.categoryLabel }}</dt><dd>{{ fieldValue(doc.category) }}</dd></div>
                    <div class="tm-detail__data-pair"><dt>{{ copy.openingHoursLabel }}</dt><dd>{{ fieldValue(doc.opening_hours) }}</dd></div>
                    <div class="tm-detail__data-pair"><dt>{{ copy.priceHintLabel }}</dt><dd>{{ fieldValue(doc.price_hint) }}</dd></div>
                    <div class="tm-detail__data-pair"><dt>{{ copy.addressLabel }}</dt><dd>{{ fieldValue(doc.address) }}</dd></div>
                    <div class="tm-detail__data-pair"><dt>{{ copy.geoLabel }}</dt><dd>{{ formatGeo(doc) }}</dd></div>
                    <div class="tm-detail__data-pair"><dt>{{ copy.platformLabel }}</dt><dd>{{ fieldValue(doc.platform) }}</dd></div>
                  </dl>
                  <div v-if="doc.source_tags?.length" class="tm-detail__chips">
                    <span v-for="tag in doc.source_tags" :key="tag" class="tm-detail__chip">{{ tag }}</span>
                  </div>
                  <a class="tm-detail__link" :href="doc.url" target="_blank" rel="noreferrer">{{ copy.sourceOpen }}</a>
                </article>
              </div>
            </section>

            <!-- Grounding references -->
            <section v-if="groundingReferenceDocs.length" id="grounding" class="tm-detail__section">
              <div class="tm-detail__section-header">
                <p class="tm-detail__section-kicker">{{ locale === "zh-CN" ? "参考来源" : "Grounding references" }}</p>
                <h2 class="tm-detail__section-title">{{ locale === "zh-CN" ? "本次规划使用的参考来源" : "Grounding sources used" }}</h2>
                <p class="tm-detail__section-desc">{{ locale === "zh-CN" ? "以下是本次规划实际带入模型上下文的参考来源。" : "These are the grounding sources actually carried into this planning run." }}</p>
              </div>
              <div class="tm-detail__reference-grid">
                <article v-for="doc in groundingReferenceDocs" :key="doc.id" class="tm-detail__reference-card">
                  <div class="tm-detail__reference-card-header">
                    <div>
                      <p class="tm-detail__kicker">{{ fieldValue(doc.platform) }}</p>
                      <h3>{{ doc.place_name || doc.title }}</h3>
                    </div>
                    <a class="tm-detail__link" :href="doc.url" target="_blank" rel="noreferrer">{{ copy.sourceOpen }}</a>
                  </div>
                  <p class="tm-detail__muted">{{ doc.summary }}</p>
                  <p v-if="doc.author || doc.published_at" class="tm-detail__muted">
                    {{ [doc.author, doc.published_at ? formatDateTime(doc.published_at) : null].filter(Boolean).join(" · ") }}
                  </p>
                  <div v-if="doc.source_tags?.length" class="tm-detail__chips">
                    <span v-for="tag in doc.source_tags" :key="tag" class="tm-detail__chip">{{ tag }}</span>
                  </div>
                  <div v-if="doc.image_urls?.length" class="tm-detail__visual-images">
                    <img v-for="imageUrl in doc.image_urls.slice(0, 3)" :key="imageUrl" :src="imageUrl" :alt="doc.title" loading="lazy" />
                  </div>
                </article>
              </div>
            </section>

            <!-- Agent pipeline -->
            <section v-if="trip.latest_agent_trace" id="agents" class="tm-detail__section">
              <div class="tm-detail__section-header">
                <p class="tm-detail__section-kicker">{{ latestSuccessfulExecutionKicker }}</p>
                <h2 class="tm-detail__section-title">{{ formatTraceProvider(trip.latest_agent_trace.provider) }}</h2>
                <p class="tm-detail__section-desc">{{ latestSuccessfulExecutionDescription }}</p>
              </div>
              <div class="tm-detail__metrics">
                <TmMetricCard v-for="metric in executionMetrics" :key="metric.label" :label="metric.label" :value="metric.value" />
              </div>
              <div v-if="agentRuns.length" class="tm-detail__agent-grid">
                <article v-for="agent in agentRuns" :key="agent.key" class="tm-detail__agent-card">
                  <div class="tm-detail__agent-card-header">
                    <div>
                      <p class="tm-detail__kicker">{{ agent.title }}</p>
                      <h3>{{ agent.description }}</h3>
                    </div>
                    <StatusPill :status="formatAgentRunStatus(agent.status)" />
                  </div>
                  <p v-if="agent.prompt_focus" class="tm-detail__muted"><strong>{{ copy.agentPromptLabel }}:</strong> {{ agent.prompt_focus }}</p>
                  <p v-if="agent.output_summary" class="tm-detail__muted"><strong>{{ copy.agentOutputLabel }}:</strong> {{ agent.output_summary }}</p>
                  <p v-if="agent.model" class="tm-detail__muted"><strong>{{ copy.agentModelLabel }}:</strong> {{ agent.model }}</p>
                  <p v-if="agent.prompt_version" class="tm-detail__muted"><strong>{{ copy.agentPromptVersionLabel }}:</strong> {{ agent.prompt_version }}</p>
                  <p v-if="agentEndpoint(agent)" class="tm-detail__muted"><strong>接口地址：</strong> {{ agentEndpoint(agent) }}</p>
                  <p v-if="agentWireApi(agent)" class="tm-detail__muted"><strong>接口格式：</strong> {{ agentWireApi(agent) }}</p>
                  <div v-if="agentDisplayCitations(agent).length" class="tm-detail__subsection">
                    <p class="tm-detail__kicker">{{ copy.agentCitationsLabel }}</p>
                    <ul class="tm-detail__list--nested">
                      <li v-for="citation in agentDisplayCitations(agent)" :key="`${agent.key}-${citation.href}`">
                        <a class="tm-detail__link" :href="citation.href" target="_blank" rel="noreferrer">{{ citation.label }}</a>
                      </li>
                    </ul>
                  </div>
                  <ul v-if="agentVisibleNotes(agent).length" class="tm-detail__list--nested">
                    <li v-for="note in agentVisibleNotes(agent)" :key="`${agent.key}-${note}`">{{ note }}</li>
                  </ul>
                </article>
              </div>
              <div class="tm-detail__subsection">
                <p class="tm-detail__kicker">{{ copy.agentNotesLabel }}</p>
                <ul class="tm-detail__list">
                  <li v-for="note in trip.latest_agent_trace.notes" :key="note">{{ note }}</li>
                </ul>
              </div>
              <p v-if="trip.latest_agent_trace.license_notice" class="tm-detail__muted">{{ trip.latest_agent_trace.license_notice }}</p>
            </section>
          </template>
        </div>
      </div>
    </template>

    <!-- Refine modal -->
    <div v-if="refineModalOpen && trip" class="tm-detail__modal-backdrop" @click.self="closeRefineModal">
      <article class="tm-detail__modal-card tm-detail__modal-card--wide">
        <div class="tm-detail__section-header">
          <p class="tm-detail__section-kicker">{{ refineWorkbenchCopy.contextLabel }}: {{ refineContextSummary }}</p>
          <h2 class="tm-detail__section-title">{{ refineWorkbenchCopy.title }}</h2>
          <p class="tm-detail__section-desc">{{ refineWorkbenchCopy.subtitle }}</p>
        </div>

        <StatePanel v-if="refineSessionPending && !refineSession" kind="loading" :title="refineWorkbenchCopy.title" message="Loading refine context." compact />

        <div class="tm-detail__refine-workbench">
          <section class="tm-detail__refine-pane">
            <div class="tm-detail__subsection-header">
              <p class="tm-detail__kicker">{{ refineWorkbenchCopy.memoryTitle }}</p>
              <TmButton variant="ghost" size="sm" :disabled="refineSessionPending || refinePending" @click="resetRefineSession">
                {{ refineWorkbenchCopy.resetMemory }}
              </TmButton>
            </div>
            <div v-if="refineConversationMessages.length" class="tm-detail__refine-messages">
              <article v-for="message in refineConversationMessages.slice(-8)" :key="message.id" :class="['tm-detail__refine-message', `tm-detail__refine-message--${message.role}`]">
                <p class="tm-detail__kicker">{{ message.role }}</p>
                <p>{{ message.text }}</p>
              </article>
            </div>
            <p v-else class="tm-detail__muted">{{ refineWorkbenchCopy.memoryEmpty }}</p>
          </section>

          <section class="tm-detail__refine-pane">
            <p class="tm-detail__kicker">{{ refineWorkbenchCopy.uploadedTitle }}</p>
            <div v-if="refineUploadedGuides.length" class="tm-detail__source-list">
              <article v-for="guide in refineUploadedGuides" :key="guide.id" class="tm-detail__source-row">
                <div>
                  <strong>{{ guide.title }}</strong>
                  <p class="tm-detail__muted">{{ guide.content.slice(0, 140) }}{{ guide.content.length > 140 ? "..." : "" }}</p>
                </div>
                <TmButton variant="ghost" size="sm" :disabled="refineSessionPending || refinePending" @click="removeRefineUploadedGuide(guide.id)">
                  {{ refineWorkbenchCopy.removeSource }}
                </TmButton>
              </article>
            </div>
            <p v-else class="tm-detail__muted">{{ refineWorkbenchCopy.uploadedEmpty }}</p>
            <div class="tm-detail__editor-grid">
              <TmField
                id="refine-guide-title"
                :model-value="refineGuideTitle"
                :label="refineWorkbenchCopy.guideTitleLabel"
                :placeholder="refineWorkbenchCopy.guideTitlePlaceholder"
                @update:model-value="(v: string | number) => refineGuideTitle = String(v)"
              />
              <label class="tm-detail__file-field">
                <span>{{ refineWorkbenchCopy.guideFileLabel }}</span>
                <input type="file" accept=".txt,.md,.json,.csv,.html,.htm" :disabled="refineSessionPending || refinePending" @change="handleGuideFileSelected" />
              </label>
            </div>
            <TmTextarea
              id="refine-guide-content"
              :model-value="refineGuideContent"
              :label="refineWorkbenchCopy.guideContentLabel"
              :placeholder="refineWorkbenchCopy.guideContentPlaceholder"
              :rows="4"
              @update:model-value="(v: string) => refineGuideContent = v"
            />
            <TmButton variant="secondary" size="sm" :disabled="refineSessionPending || refinePending" @click="addRefineUploadedGuide">
              {{ refineWorkbenchCopy.addGuide }}
            </TmButton>
          </section>

          <section class="tm-detail__refine-pane">
            <p class="tm-detail__kicker">{{ refineWorkbenchCopy.communityTitle }}</p>
            <div v-if="refineCommunitySources.length" class="tm-detail__source-list">
              <article v-for="source in refineCommunitySources" :key="source.id" class="tm-detail__source-row">
                <div>
                  <strong>{{ source.title }}</strong>
                  <p class="tm-detail__muted">{{ source.destination }} / {{ source.author_name }} / {{ source.itinerary_summary }}</p>
                </div>
                <TmButton variant="ghost" size="sm" :disabled="refineSessionPending || refinePending" @click="removeRefineCommunitySource(source.id)">
                  {{ refineWorkbenchCopy.removeSource }}
                </TmButton>
              </article>
            </div>
            <p v-else class="tm-detail__muted">{{ refineWorkbenchCopy.communityEmpty }}</p>
            <div class="tm-detail__refine-community-picker">
              <TmSelect
                id="refine-community-source"
                :model-value="selectedCommunityPostId"
                :label="refineWorkbenchCopy.communitySelectLabel"
                :placeholder="refineWorkbenchCopy.communitySelectPlaceholder"
                :options="refineCommunityOptions"
                :disabled="refineSessionPending || refinePending || refineCommunityOptions.length === 0"
                @update:model-value="(v: string) => selectedCommunityPostId = v"
              />
              <TmButton variant="secondary" size="sm" :disabled="refineSessionPending || refinePending || !selectedCommunityPostId" @click="attachSelectedCommunitySource">
                {{ refineWorkbenchCopy.attachCommunity }}
              </TmButton>
            </div>
          </section>
        </div>

        <div class="tm-detail__quick-actions">
          <TmButton v-for="action in quickRefineActions" :key="action.label" variant="ghost" size="sm" :disabled="actionLocked || !canUseModel" @click="runPresetRefine(action)">
            {{ action.label }}
          </TmButton>
        </div>
        <TmTextarea
          id="custom-refine"
          :model-value="customRefineInstruction"
          :label="copy.customRefineLabel"
          :placeholder="copy.customRefinePlaceholder"
          :rows="4"
          @update:model-value="(v: string) => customRefineInstruction = v"
        />
        <StatePanel v-if="refineError" kind="error" :title="copy.quickRefineTitle" :message="isDebug ? refineError : publicJobError(refineError)" compact />
        <div class="tm-detail__section-actions">
          <TmButton variant="primary" :disabled="actionLocked || !canUseModel" :loading="refinePending" @click="submitCustomRefine">
            {{ refinePending ? copy.refining : copy.customRefineSubmit }}
          </TmButton>
          <TmButton variant="ghost" :disabled="refinePending" @click="closeRefineModal">{{ communityCopy.cancelAction }}</TmButton>
        </div>
      </article>
    </div>

    <!-- Community editor modal -->
    <div v-if="communityEditorOpen && trip" class="tm-detail__modal-backdrop" @click.self="closeCommunityEditor">
      <article class="tm-detail__modal-card">
        <div class="tm-detail__section-header">
          <p class="tm-detail__section-kicker">{{ communityCopy.kicker }}</p>
          <h2 class="tm-detail__section-title">{{ communityEditorMode === 'create' ? communityCopy.modalCreateTitle : communityCopy.modalEditTitle }}</h2>
          <p class="tm-detail__section-desc">{{ communityCopy.noteHint }}</p>
        </div>

        <div class="tm-detail__community-preview">
          <img v-if="communityPreviewImage" class="tm-detail__community-cover" :src="communityPreviewImage" :alt="trip.title" />
          <p class="tm-detail__kicker">{{ communityCopy.previewTitle }}</p>
          <h3>{{ trip.title }}</h3>
          <p class="tm-detail__muted">{{ trip.itinerary?.summary }}</p>
          <div class="tm-detail__chips">
            <span class="tm-detail__chip--subtle">{{ communityCopy.previewDays }}: {{ communityPreviewDays }}</span>
            <span class="tm-detail__chip--subtle">{{ communityCopy.previewBudget }}: {{ formatCurrency(trip.budget) }}</span>
            <span v-for="interest in communityPreviewInterestTags" :key="interest" class="tm-detail__chip">{{ interest }}</span>
          </div>
        </div>

        <TmTextarea
          id="community-note"
          :model-value="communityNoteDraft"
          :label="communityCopy.noteLabel"
          :placeholder="communityCopy.notePlaceholder"
          :rows="4"
          @update:model-value="(v: string) => communityNoteDraft = v"
        />
        <p class="tm-detail__muted">{{ communityNoteDraft.length }}/280</p>

        <div class="tm-detail__section-actions">
          <TmButton variant="primary" :disabled="communityPending" :loading="communityPending" @click="submitCommunityEditor">
            {{ communityPending ? (communityEditorMode === "create" ? communityCopy.publishingAction : communityCopy.savingAction) : (communityEditorMode === "create" ? communityCopy.submitCreate : communityCopy.submitEdit) }}
          </TmButton>
          <TmButton variant="ghost" :disabled="communityPending" @click="closeCommunityEditor">{{ communityCopy.cancelAction }}</TmButton>
        </div>
      </article>
    </div>
  </div>
</template>

<style scoped>
.tm-detail {
  max-width: var(--tm-content-max-width);
  margin: 0 auto;
}

.tm-detail__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--tm-space-6);
  margin-bottom: var(--tm-space-6);
  flex-wrap: wrap;
}

.tm-detail__header-actions {
  display: flex;
  gap: var(--tm-space-3);
  flex-wrap: wrap;
}

.tm-detail__kicker {
  font-size: var(--tm-text-xs);
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--tm-clay);
  margin: 0;
}

.tm-detail__title {
  font-family: var(--tm-font-display);
  font-size: var(--tm-text-2xl);
  color: var(--tm-moss);
  margin: 0 0 var(--tm-space-2) 0;
}

.tm-detail__meta {
  display: flex;
  gap: var(--tm-space-4);
  flex-wrap: wrap;
  font-size: var(--tm-text-sm);
  color: var(--tm-stone);
}

.tm-detail__overview {
  margin-bottom: var(--tm-space-6);
}

.tm-detail__metrics {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: var(--tm-space-4);
  margin-top: var(--tm-space-4);
}
/* Body layout */
.tm-detail__body {
  display: block;
}

.tm-detail__main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--tm-space-10, 40px);
}

.tm-detail__section {
  padding: var(--tm-space-8, 32px);
  border-radius: var(--tm-radius-2xl, 28px);
  background-color: var(--tm-snow);
  border: none;
  box-shadow: var(--tm-shadow-card);
  display: flex;
  flex-direction: column;
  gap: var(--tm-space-6);
}

.tm-detail__section-header { display: flex; flex-direction: column; gap: var(--tm-space-2); }
.tm-detail__section-kicker { font-size: var(--tm-text-xs); font-weight: 800; text-transform: uppercase; letter-spacing: 0.12em; color: var(--tm-clay); margin: 0; }
.tm-detail__section-title { font-size: var(--tm-text-lg); font-weight: 700; color: var(--tm-tea); margin: 0; }
.tm-detail__section-desc { font-size: var(--tm-text-sm); color: var(--tm-stone); margin: 0; }
.tm-detail__section-actions { display: flex; gap: var(--tm-space-3); flex-wrap: wrap; }
.tm-detail__muted { font-size: var(--tm-text-sm); color: var(--tm-stone); margin: 0; }

.tm-detail__subsection { display: flex; flex-direction: column; gap: var(--tm-space-3); padding-top: var(--tm-space-3); border-top: var(--tm-border-hairline); }
.tm-detail__subsection-header { display: flex; justify-content: space-between; align-items: center; }
.tm-detail__inline-links { display: flex; flex-wrap: wrap; gap: var(--tm-space-2); }

.tm-detail__data-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--tm-space-3); }
.tm-detail__data-pair dt { font-size: var(--tm-text-xs); font-weight: 700; color: var(--tm-stone); text-transform: uppercase; letter-spacing: 0.05em; }
.tm-detail__data-pair dd { font-size: var(--tm-text-sm); color: var(--tm-tea); margin: 0; }

.tm-detail__chips { display: flex; flex-wrap: wrap; gap: var(--tm-space-2); }
.tm-detail__chip { padding: 4px 10px; border-radius: var(--tm-radius-sm); background-color: rgba(93, 122, 99, 0.06); font-size: var(--tm-text-xs); font-weight: 600; color: var(--tm-moss); }
.tm-detail__chip--subtle { padding: 4px 10px; border-radius: var(--tm-radius-sm); background-color: var(--tm-mist); font-size: var(--tm-text-xs); color: var(--tm-stone); }

.tm-detail__link { font-size: var(--tm-text-sm); font-weight: 600; color: var(--tm-moss); text-decoration: none; }
.tm-detail__link:hover { text-decoration: underline; }

.tm-detail__list { list-style: none; padding: 0; margin: 0; font-size: var(--tm-text-sm); color: var(--tm-tea); }
.tm-detail__list--nested { list-style: disc; padding-left: var(--tm-space-4); font-size: var(--tm-text-sm); color: var(--tm-stone); }

.tm-detail__badge { display: inline-block; padding: 3px 8px; border-radius: var(--tm-radius-sm); background-color: var(--tm-mist); font-size: var(--tm-text-xs); font-weight: 700; color: var(--tm-stone); }

.tm-detail__timeline { list-style: none; padding: 0; margin: 0; }
.tm-detail__timeline-item { padding-left: var(--tm-space-4); border-left: 2px solid var(--tm-mist); margin-bottom: var(--tm-space-3); }
.tm-detail__timeline-meta { display: flex; align-items: center; gap: var(--tm-space-2); }

.tm-detail__days { display: flex; flex-direction: column; gap: var(--tm-space-8, 32px); }
.tm-detail__day-card {
  padding: var(--tm-space-8, 32px);
  border-radius: var(--tm-radius-2xl, 28px);
  background-color: var(--tm-snow);
  border: none;
  box-shadow: var(--tm-shadow-raised-md);
}
.tm-detail__day-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: var(--tm-space-3); }
.tm-detail__day-title { font-size: var(--tm-text-xl, 1.25rem); font-weight: 700; color: var(--tm-tea); margin: 0; }
.tm-detail__day-cost { font-family: var(--tm-font-mono); font-size: var(--tm-text-base); font-weight: 700; color: var(--tm-moss); padding: var(--tm-space-1) var(--tm-space-3); background: rgba(93, 122, 99, 0.08); border-radius: var(--tm-radius-sm); }
.tm-detail__day-summary { font-size: var(--tm-text-sm); color: var(--tm-stone); margin: 0 0 var(--tm-space-4) 0; }

.tm-detail__editor { display: flex; flex-direction: column; gap: var(--tm-space-6); }
.tm-detail__day-card--editing { display: flex; flex-direction: column; gap: var(--tm-space-5); }
.tm-detail__editor-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: var(--tm-space-4); }
.tm-detail__editor-grid--item { align-items: start; }
.tm-detail__editor-wide { grid-column: 1 / -1; }
.tm-detail__editor-items { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: var(--tm-space-4); }
.tm-detail__editor-item { padding: var(--tm-space-4); border-radius: var(--tm-radius-lg); background-color: var(--tm-mist); border: var(--tm-border-subtle); }
.tm-detail__editor-item-header { display: flex; justify-content: space-between; align-items: center; gap: var(--tm-space-3); margin-bottom: var(--tm-space-4); }

.tm-detail__items { list-style: none; padding: 0; margin: 0; }
.tm-detail__item {
  display: grid;
  grid-template-columns: 90px 1fr;
  gap: var(--tm-space-4);
  padding: var(--tm-space-4) 0 var(--tm-space-4) var(--tm-space-4);
  border-top: none;
  border-left: 3px solid var(--tm-mist);
  margin-left: var(--tm-space-2);
  transition: border-color var(--tm-duration-fast) var(--tm-ease-out);
}
.tm-detail__item:hover {
  border-left-color: var(--tm-moss);
}
.tm-detail__item-time { font-family: var(--tm-font-mono); font-size: var(--tm-text-xs); color: var(--tm-stone); }
.tm-detail__item-body { display: flex; flex-direction: column; gap: var(--tm-space-2); }
.tm-detail__item-topline { display: flex; justify-content: space-between; align-items: center; gap: var(--tm-space-2); }
.tm-detail__item-badges { display: flex; gap: var(--tm-space-1); flex-wrap: wrap; }
.tm-detail__item-note { font-size: var(--tm-text-sm); color: var(--tm-tea); margin: 0; }
.tm-detail__nearby { margin-top: var(--tm-space-2); padding: var(--tm-space-3); border-radius: var(--tm-radius-md); background: rgba(93, 122, 99, 0.06); }
.tm-detail__nearby-title { margin: 0 0 var(--tm-space-2); font-size: var(--tm-text-sm); font-weight: 700; color: var(--tm-moss); }
.tm-detail__nearby-list { display: flex; flex-direction: column; gap: var(--tm-space-3); margin: 0; padding: 0; list-style: none; }
.tm-detail__nearby-item { font-size: var(--tm-text-sm); color: var(--tm-tea); }
.tm-detail__nearby-item p { margin: var(--tm-space-1) 0 0; }

.tm-detail__visual-images { display: flex; gap: var(--tm-space-3); overflow-x: auto; }
.tm-detail__visual-images img { width: 120px; height: 80px; object-fit: cover; border-radius: var(--tm-radius-md); }

.tm-detail__visual-card,
.tm-detail__reference-card,
.tm-detail__search-card,
.tm-detail__agent-card,
.tm-detail__debug-card {
  padding: var(--tm-space-4);
  border-radius: var(--tm-radius-lg);
  background-color: var(--tm-mist);
  border: var(--tm-border-subtle);
  display: flex;
  flex-direction: column;
  gap: var(--tm-space-2);
}

.tm-detail__visual-card-header,
.tm-detail__reference-card-header,
.tm-detail__search-card-header,
.tm-detail__agent-card-header,
.tm-detail__debug-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.tm-detail__reference-grid,
.tm-detail__search-results,
.tm-detail__agent-grid,
.tm-detail__debug-grid,
.tm-detail__visual-grid {
  display: flex;
  flex-direction: column;
  gap: var(--tm-space-4);
}

.tm-detail__quick-actions { display: flex; flex-wrap: wrap; gap: var(--tm-space-2); }
.tm-detail__weather { padding: var(--tm-space-3); border-radius: var(--tm-radius-md); background-color: var(--tm-mist); }
.tm-detail__risk-list { list-style: none; padding: 0; margin: 0; }
.tm-detail__risk-list li { padding: var(--tm-space-2) var(--tm-space-3); border-radius: var(--tm-radius-sm); background-color: var(--tm-warning-bg); border: 1px solid var(--tm-warning-border); font-size: var(--tm-text-sm); color: var(--tm-warning); margin-bottom: var(--tm-space-2); }

.tm-detail__banner { padding: var(--tm-space-3) var(--tm-space-4); border-radius: var(--tm-radius-md); background-color: var(--tm-mist); border: var(--tm-border-subtle); }
.tm-detail__banner--warn { background-color: var(--tm-warning-bg); border-color: var(--tm-warning-border); }

.tm-detail__community-preview { display: flex; flex-direction: column; gap: var(--tm-space-2); }
.tm-detail__community-cover { width: 100%; height: 140px; object-fit: cover; border-radius: var(--tm-radius-md); }

.tm-detail__modal-backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.4); display: grid; place-items: center; z-index: 100; padding: var(--tm-space-6); }
.tm-detail__modal-card { max-width: 560px; width: 100%; padding: var(--tm-space-8); border-radius: var(--tm-radius-2xl); background-color: var(--tm-paper); box-shadow: var(--tm-shadow-float); display: flex; flex-direction: column; gap: var(--tm-space-4); }
.tm-detail__modal-card--wide { max-width: min(960px, calc(100vw - 32px)); max-height: calc(100vh - 48px); overflow: auto; }

.tm-detail__refine-workbench { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--tm-space-4); }
.tm-detail__refine-pane { display: flex; flex-direction: column; gap: var(--tm-space-3); min-width: 0; padding: var(--tm-space-4); border-radius: var(--tm-radius-lg); background-color: var(--tm-mist); border: var(--tm-border-subtle); }
.tm-detail__refine-messages,
.tm-detail__source-list { display: flex; flex-direction: column; gap: var(--tm-space-2); max-height: 220px; overflow: auto; }
.tm-detail__refine-message,
.tm-detail__source-row { padding: var(--tm-space-3); border-radius: var(--tm-radius-md); background-color: var(--tm-paper); box-shadow: var(--tm-shadow-inset-sm); }
.tm-detail__refine-message p,
.tm-detail__source-row p { margin: 0; overflow-wrap: anywhere; }
.tm-detail__refine-message--user { border-left: 3px solid var(--tm-moss); }
.tm-detail__refine-message--assistant { border-left: 3px solid var(--tm-clay); }
.tm-detail__source-row { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--tm-space-3); }
.tm-detail__file-field { display: flex; flex-direction: column; gap: var(--tm-space-2); font-size: var(--tm-text-sm); font-weight: 700; color: var(--tm-tea); }
.tm-detail__file-field input { width: 100%; font-size: var(--tm-text-sm); color: var(--tm-stone); }
.tm-detail__refine-community-picker { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: end; gap: var(--tm-space-3); }

@media (max-width: 1024px) {
  .tm-detail__body { display: block; }
}

@media (max-width: 768px) {
  .tm-detail__header { flex-direction: column; }
  .tm-detail__item { grid-template-columns: 1fr; }
  .tm-detail__data-grid { grid-template-columns: 1fr; }
  .tm-detail__refine-workbench { grid-template-columns: 1fr; }
  .tm-detail__refine-community-picker { grid-template-columns: 1fr; }
}

/* Journey mode is additive: the full booking/editor/debug workbench remains available. */
.tm-detail--portal { --tm-moss: #46685c; --tm-clay: #77866d; --tm-paper: #f1f3ed; --tm-mist: #e8ede3; --tm-snow: #fbfcf7; --tm-tea: #2f443b; --tm-stone: #6c7c6d; --tm-font-display: "Portal Manrope", "Microsoft YaHei", sans-serif; }
.tm-detail--journey { padding: 32px 38px 40px; border: 1px solid white; border-radius: 28px; background: radial-gradient(ellipse at 100% 0, #f7eadd88, transparent 40%), linear-gradient(145deg, #f6f7ef, #edf2e7); box-shadow: 0 20px 70px #52684d08; }
.tm-detail--portal .tm-detail__title { margin: 8px 0 14px; font-size: 32px; font-weight: 400; line-height: 1.5; letter-spacing: -.04em; overflow-wrap: anywhere; }
.tm-detail--portal .tm-detail__header-info { flex: 1 1 400px; min-width: 0; }
.tm-detail--portal .tm-detail__header-actions { gap: 8px; padding-top: 8px; }
.tm-detail--portal .tm-detail__header-actions :deep(.tm-btn) { min-height: 40px; padding: 10px 14px; font-size: 11px; box-shadow: none; }
.tm-detail--portal .tm-detail__header-actions :deep(.tm-btn--primary) { background: #46685c; color: #fff; border-color: #46685c; }
.tm-detail--portal .tm-detail__header-actions :deep(.tm-btn--danger) { color: #927269; background: transparent; border-color: #e0dcd1; }
.tm-detail--portal .tm-detail__kicker { font-size: 10px; font-weight: 500; letter-spacing: .07em; }
.tm-detail--portal .tm-detail__meta { gap: 8px 19px; font-size: 11px; line-height: 1.8; }
.tm-detail__view-switch { display: flex; justify-content: space-between; align-items: center; gap: 14px; padding-bottom: 12px; border-bottom: 1px solid #dce3da; }
.tm-detail__view-switch > div { display: inline-flex; gap: 4px; padding: 4px; border: 1px solid #fff; border-radius: 100px; background: #e9eee3; }
.tm-detail__view-switch button, .tm-detail__journey-job button { min-height: 40px; padding: 10px 18px; border: 0; border-radius: 100px; background: transparent; color: #687d69; font-size: 11px; box-shadow: none; }
.tm-detail__view-switch button[aria-pressed="true"] { background: #46685c; color: #fff; }
.tm-detail__view-switch button:focus-visible { outline: 2px solid #46685c; outline-offset: 3px; }
.tm-detail__journey-job { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 18px; padding: 10px 16px; border: 1px solid #d6dfcf; border-radius: 14px; background: #ffffff88; color: #6c7c6d; font-size: 11px; }
.tm-detail__journey-job code { max-width: 100%; overflow-wrap: anywhere; font-size: 9px; }
.tm-detail__journey-job button { margin-left: auto; }
.tm-detail__journey-settings { margin-top: 28px; border-top: 1px solid #dce3da; color: #7b8b76; font-size: 11px; }
.tm-detail__journey-settings summary { min-height: 44px; padding: 14px 0; cursor: pointer; }
@media (max-width: 760px) {
  .tm-detail--journey { padding: 24px 18px 28px; border-radius: 22px; }
  .tm-detail--portal .tm-detail__header-info { flex-basis: auto; }
  .tm-detail--portal .tm-detail__title { font-size: 25px; }
  .tm-detail--portal .tm-detail__header-actions { width: 100%; padding-top: 0; }
  .tm-detail--portal .tm-detail__header-actions :deep(.tm-btn) { flex: 1 1 auto; }
  .tm-detail__view-switch { gap: 6px; }
  .tm-detail__view-switch button { padding-inline: 12px; font-size: 10px; }
  .tm-detail__view-switch > button { padding-inline: 4px; }
}

</style>
