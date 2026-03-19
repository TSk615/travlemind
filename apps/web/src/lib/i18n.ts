export type LocaleCode = "en-US" | "zh-CN"

export const DEFAULT_LOCALE: LocaleCode = "en-US"
export const LOCALE_STORAGE_KEY = "travelmind_locale"
export const SUPPORTED_LOCALES = [
  { code: "zh-CN", shortLabel: "中" },
  { code: "en-US", shortLabel: "EN" }
] as const

const messages: Record<LocaleCode, Record<string, unknown>> = {
  "en-US": {
    meta: { appTitle: "Travel planning workspace" },
    language: { label: "Language", english: "English", chinese: "Chinese" },
    layout: {
      tagline: "From scattered inspiration to executable itineraries.",
      nav: { home: "Home", trips: "Trips", newTrip: "New Trip" },
      checkingSession: "Checking session...",
      signIn: "Sign in",
      logOut: "Log out"
    },
    state: { kind: { loading: "Loading", error: "Error", empty: "Empty", info: "Info" } },
    status: { queued: "Queued", running: "Running", completed: "Completed", failed: "Failed", cancelled: "Cancelled" },
    common: {
      retry: "Retry",
      createTrip: "Create trip",
      openTrip: "Open trip",
      openDashboard: "Open dashboard",
      startNewTrip: "Start a new trip",
      useStarterBrief: "Use starter brief",
      clearForm: "Clear form",
      loadStarterBrief: "Load starter brief",
      generateItinerary: "Generate itinerary",
      generating: "Generating...",
      exportPdf: "Export PDF",
      exporting: "Exporting...",
      runSearch: "Run search",
      searching: "Searching...",
      openSource: "Open source",
      openExport: "Open export",
      downloadPdf: "Download PDF",
      openGeneratedFile: "Open generated file",
      backToTrip: "Back to trip",
      budgetValue: "Budget {value}",
      travelersCount: "{count} traveler(s)",
      paceValue: "{value} pace",
      updatedAt: "Updated {value}",
      estimatedTotal: "Estimated total: {value}",
      estimatedDailyCost: "Estimated daily cost: {value}",
      finalScore: "Final score: {value}",
      noItineraryYet: "No itinerary generated yet.",
      daysLabel: "Day {day}: {title}",
      pace: { slow: "Slow", balanced: "Balanced", packed: "Packed" },
      transport: { rail: "Rail", car: "Car", walking: "Walking", mixed: "Mixed" }
    },
    home: {
      kicker: "MVP workspace",
      title: "Plan the trip before the tabs win.",
      description: "TravelMind AI turns destination research, itinerary drafting, source review, and PDF handoff into one guided workflow.",
      highlightKicker: "What ships in MVP",
      highlightTitle: "One usable loop",
      highlightItems: [
        "Create a trip with destination, dates, and preferences.",
        "Trigger AI itinerary generation through an async job.",
        "Search official sources and manual links with normalized scoring.",
        "Export the result as a lightweight PDF artifact."
      ],
      cards: {
        search: { kicker: "Search", title: "Official-first retrieval", description: "Seeded official sources plus manual links, with placeholder trust scoring for future ranking upgrades." },
        planning: { kicker: "Planning", title: "Adapter-based agents", description: "`helloagents` stays behind an internal orchestrator boundary, so the product contract is not locked to a PoC dependency." },
        export: { kicker: "Export", title: "Shareable trip packets", description: "PDF export runs through the same job system as itinerary generation, which keeps progress reporting consistent." }
      }
    },
    login: {
      kicker: "Account",
      welcomeBack: "Welcome back",
      createTitle: "Create your workspace login",
      helperLogin: "Use your existing workspace login to reach the trip dashboard and async job flows.",
      helperRegister: "Registration creates the same cookie-backed MVP session the protected trip routes expect.",
      loginTab: "Login",
      registerTab: "Register",
      checkingTitle: "Checking existing session",
      checkingMessage: "Verifying whether an auth cookie is already active before showing the form.",
      unableSignIn: "Unable to sign in",
      unableCreate: "Unable to create account",
      name: "Name",
      email: "Email",
      password: "Password",
      signIn: "Sign in",
      signingIn: "Signing in...",
      createAccount: "Create account",
      creatingAccount: "Creating account...",
      cookieNote: "MVP auth uses HttpOnly cookies issued by FastAPI.",
      registerNote: "Name, email, and password are posted directly to the auth contract."
    },
    trips: {
      kicker: "Trips",
      title: "Your planning workspace",
      description: "This dashboard stays narrow in MVP: create, inspect, generate, export.",
      loadingTitle: "Loading trips",
      loadingMessage: "Fetching the latest trip list from the authenticated `/api/v1/trips` endpoint.",
      unavailableTitle: "Trip dashboard unavailable",
      emptyTitle: "No trips yet",
      emptyMessage: "Create the first trip to unlock itinerary generation, grounded search, and PDF export."
    },
    tripForm: {
      kicker: "New trip",
      title: "Capture the planning brief",
      description: "The AI planner consumes the same structured input the rest of the workflow uses, so we keep the form explicit.",
      creatingTitle: "Creating trip",
      creatingMessage: "Posting the planning brief to `/api/v1/trips` and waiting for the persisted record.",
      needsAttentionTitle: "Trip brief needs attention",
      blankTitle: "Trip brief is blank",
      blankMessage: "Add destination, dates, budget, and interests before creating the trip.",
      titleLabel: "Trip title",
      destinationLabel: "Destination",
      startDateLabel: "Start date",
      endDateLabel: "End date",
      budgetLabel: "Budget",
      travelersLabel: "Travelers",
      paceLabel: "Pace",
      transportLabel: "Transport",
      interestsLabel: "Interests",
      accommodationLabel: "Accommodation preference",
      interestsPlaceholder: "temples, coffee, quiet neighborhoods",
      createTrip: "Create trip",
      creatingTrip: "Creating trip...",
      contractNote: "The form maps directly to the backend `TripCreateRequest` contract.",
      validation: {
        title: "Trip title must be at least 3 characters.",
        destination: "Destination must be at least 2 characters.",
        datesRequired: "Start date and end date are required.",
        datesRange: "End date must be on or after the start date.",
        budget: "Budget must be greater than 0.",
        travelers: "Travelers must be at least 1."
      }
    },
    tripDetail: {
      loadingTitle: "Loading trip",
      loadingMessage: "Fetching the latest trip record, itinerary, and agent trace.",
      unavailableTitle: "Trip unavailable",
      agentTrace: "Agent trace",
      generationFailedTitle: "Generation request failed",
      exportFailedTitle: "Export request failed",
      generatingTitle: "Generating itinerary",
      generatingMessage: "Polling the job status endpoint until the async workflow reaches a terminal state.",
      exportingTitle: "Building PDF export",
      asyncFailedTitle: "Async job failed",
      itineraryKicker: "Itinerary",
      itineraryPendingTitle: "Itinerary is being generated",
      itineraryPendingMessage: "Stay on this page or reopen the trip later; the result is persisted to the same trip record.",
      itineraryEmptyTitle: "No itinerary generated yet",
      itineraryEmptyMessage: "Trigger the planner job once the trip brief looks correct.",
      searchKicker: "Search",
      searchTitle: "Collect grounded signals",
      searchDescription: "First-party tourism pages and manual links are normalized into `SearchDocument` records.",
      queryLabel: "Query",
      linksLabel: "Manual links",
      searchLoadingTitle: "Searching approved sources",
      searchLoadingMessage: "Calling the MVP search endpoint and waiting for normalized documents.",
      searchFailedTitle: "Search failed",
      searchEmptyBeforeTitle: "No source review yet",
      searchEmptyBeforeMessage: "Run a search to collect official or manual documents for this trip.",
      searchEmptyTitle: "No matching sources found",
      searchEmptyMessage: "Try a broader query or add more manual links from official tourism pages."
    },
    exportView: {
      loadingTitle: "Loading export job",
      loadingMessage: "Fetching the latest PDF export status from `/api/v1/jobs/:id`.",
      unavailableTitle: "Export job unavailable",
      kicker: "Export job",
      refreshFailedTitle: "Status refresh failed",
      runningTitle: "Export still running",
      runningPolling: "Polling for the latest worker status.",
      runningWaiting: "Waiting for the worker to complete the PDF export.",
      failedTitle: "Export failed",
      resultKicker: "Result",
      emptyTitle: "No export artifact returned",
      emptyMessage: "The job completed, but no result payload was attached to the response envelope."
    }
  },
  "zh-CN": {
    meta: { appTitle: "旅行规划工作台" },
    language: { label: "语言", english: "英文", chinese: "中文" },
    layout: {
      tagline: "把零散灵感整理成可执行行程。",
      nav: { home: "首页", trips: "行程", newTrip: "新建行程" },
      checkingSession: "正在检查会话...",
      signIn: "登录",
      logOut: "退出"
    },
    state: { kind: { loading: "加载中", error: "错误", empty: "空状态", info: "信息" } },
    status: { queued: "排队中", running: "执行中", completed: "已完成", failed: "失败", cancelled: "已取消" },
    common: {
      retry: "重试",
      createTrip: "创建行程",
      openTrip: "打开行程",
      openDashboard: "打开工作台",
      startNewTrip: "开始新行程",
      useStarterBrief: "使用示例表单",
      clearForm: "清空表单",
      loadStarterBrief: "载入示例表单",
      generateItinerary: "生成行程",
      generating: "生成中...",
      exportPdf: "导出 PDF",
      exporting: "导出中...",
      runSearch: "开始检索",
      searching: "检索中...",
      openSource: "打开来源",
      openExport: "查看导出",
      downloadPdf: "下载 PDF",
      openGeneratedFile: "打开生成文件",
      backToTrip: "返回行程",
      budgetValue: "预算 {value}",
      travelersCount: "{count} 位出行者",
      paceValue: "{value}",
      updatedAt: "更新于 {value}",
      estimatedTotal: "预计总花费：{value}",
      estimatedDailyCost: "预计每日花费：{value}",
      finalScore: "最终评分：{value}",
      noItineraryYet: "尚未生成行程。",
      daysLabel: "第 {day} 天：{title}",
      pace: { slow: "慢节奏", balanced: "均衡", packed: "紧凑" },
      transport: { rail: "铁路", car: "自驾", walking: "步行", mixed: "混合" }
    },
    home: {
      kicker: "MVP 工作台",
      title: "别让几十个标签页替你做旅行决策。",
      description: "TravelMind AI 将目的地调研、行程草拟、信息核验和 PDF 导出整合成一条完整工作流。",
      highlightKicker: "MVP 当前能力",
      highlightTitle: "一个可用闭环",
      highlightItems: [
        "创建包含目的地、日期和偏好的行程。",
        "通过异步任务触发 AI 行程生成。",
        "检索官方来源与手动链接，并输出统一评分。",
        "将结果导出为轻量 PDF 文件。"
      ],
      cards: {
        search: { kicker: "检索", title: "官方优先召回", description: "当前版本优先使用官方来源和手动链接，并为后续评分升级预留占位能力。" },
        planning: { kicker: "规划", title: "可替换 Agent 编排", description: "`helloagents` 被封装在内部编排边界之后，产品接口不会被 PoC 依赖锁死。" },
        export: { kicker: "导出", title: "可分享行程包", description: "PDF 导出与行程生成共用同一套任务系统，因此进度反馈保持一致。" }
      }
    },
    login: {
      kicker: "账户",
      welcomeBack: "欢迎回来",
      createTitle: "创建你的工作台账户",
      helperLogin: "使用已有账户进入行程工作台，并继续查看异步任务状态。",
      helperRegister: "注册后会直接创建与受保护路由兼容的 Cookie 会话。",
      loginTab: "登录",
      registerTab: "注册",
      checkingTitle: "正在检查已有会话",
      checkingMessage: "先确认浏览器里是否已经存在有效登录 Cookie，再决定是否展示表单。",
      unableSignIn: "登录失败",
      unableCreate: "创建账户失败",
      name: "名称",
      email: "邮箱",
      password: "密码",
      signIn: "登录",
      signingIn: "登录中...",
      createAccount: "创建账户",
      creatingAccount: "创建中...",
      cookieNote: "MVP 登录使用 FastAPI 下发的 HttpOnly Cookie。",
      registerNote: "名称、邮箱和密码会直接提交到认证接口。"
    },
    trips: {
      kicker: "行程",
      title: "你的规划工作台",
      description: "MVP 只聚焦四件事：创建、查看、生成、导出。",
      loadingTitle: "正在加载行程",
      loadingMessage: "从受保护的 `/api/v1/trips` 接口拉取最新行程列表。",
      unavailableTitle: "行程工作台不可用",
      emptyTitle: "还没有行程",
      emptyMessage: "创建第一条行程后，就可以开始生成路线、检索信息和导出 PDF。"
    },
    tripForm: {
      kicker: "新建行程",
      title: "填写规划 Brief",
      description: "AI 规划器直接消费这份结构化输入，所以表单会保持明确和可控。",
      creatingTitle: "正在创建行程",
      creatingMessage: "正在将规划 Brief 提交到 `/api/v1/trips`，并等待记录写入。",
      needsAttentionTitle: "行程 Brief 需要补充",
      blankTitle: "行程 Brief 为空",
      blankMessage: "请先填写目的地、日期、预算和兴趣偏好，再创建行程。",
      titleLabel: "行程标题",
      destinationLabel: "目的地",
      startDateLabel: "开始日期",
      endDateLabel: "结束日期",
      budgetLabel: "预算",
      travelersLabel: "出行人数",
      paceLabel: "节奏",
      transportLabel: "交通方式",
      interestsLabel: "兴趣偏好",
      accommodationLabel: "住宿偏好",
      interestsPlaceholder: "寺庙, 咖啡, 安静街区",
      createTrip: "创建行程",
      creatingTrip: "创建中...",
      contractNote: "这份表单会直接映射到后端 `TripCreateRequest`。",
      validation: {
        title: "行程标题至少需要 3 个字符。",
        destination: "目的地至少需要 2 个字符。",
        datesRequired: "开始日期和结束日期不能为空。",
        datesRange: "结束日期不能早于开始日期。",
        budget: "预算必须大于 0。",
        travelers: "出行人数至少为 1。"
      }
    },
    tripDetail: {
      loadingTitle: "正在加载行程",
      loadingMessage: "获取最新行程记录、已生成路线和 Agent 执行痕迹。",
      unavailableTitle: "行程不可用",
      agentTrace: "Agent 轨迹",
      generationFailedTitle: "生成请求失败",
      exportFailedTitle: "导出请求失败",
      generatingTitle: "正在生成行程",
      generatingMessage: "轮询任务状态接口，直到异步流程进入终态。",
      exportingTitle: "正在生成 PDF",
      asyncFailedTitle: "异步任务失败",
      itineraryKicker: "行程",
      itineraryPendingTitle: "行程正在生成",
      itineraryPendingMessage: "你可以留在当前页面，也可以稍后回来；结果会写回同一条行程记录。",
      itineraryEmptyTitle: "还没有生成行程",
      itineraryEmptyMessage: "确认 Brief 无误后即可触发行程生成任务。",
      searchKicker: "检索",
      searchTitle: "收集可信信号",
      searchDescription: "官方旅游页面和手动链接会被统一归一化成 `SearchDocument` 记录。",
      queryLabel: "查询词",
      linksLabel: "手动链接",
      searchLoadingTitle: "正在检索已批准来源",
      searchLoadingMessage: "调用 MVP 搜索接口并等待归一化后的文档结果。",
      searchFailedTitle: "检索失败",
      searchEmptyBeforeTitle: "还没有进行信息核验",
      searchEmptyBeforeMessage: "先执行一次检索，收集与这次行程相关的官方或手动来源。",
      searchEmptyTitle: "没有找到匹配来源",
      searchEmptyMessage: "试试更宽泛的关键词，或补充更多官方旅游链接。"
    },
    exportView: {
      loadingTitle: "正在加载导出任务",
      loadingMessage: "从 `/api/v1/jobs/:id` 获取最新 PDF 导出状态。",
      unavailableTitle: "导出任务不可用",
      kicker: "导出任务",
      refreshFailedTitle: "状态刷新失败",
      runningTitle: "导出仍在进行",
      runningPolling: "正在轮询最新 Worker 状态。",
      runningWaiting: "正在等待 Worker 完成 PDF 导出。",
      failedTitle: "导出失败",
      resultKicker: "结果",
      emptyTitle: "没有返回导出文件",
      emptyMessage: "任务虽然完成了，但响应里没有附带结果信息。"
    }
  }
}

function resolveMessage(source: Record<string, unknown>, key: string): string | null {
  const segments = key.split(".")
  let current: unknown = source

  for (const segment of segments) {
    if (current === null || typeof current !== "object" || !(segment in current)) {
      return null
    }
    current = (current as Record<string, unknown>)[segment]
  }

  return typeof current === "string" ? current : null
}

export function normalizeLocale(rawLocale?: string | null): LocaleCode {
  if (!rawLocale) {
    return DEFAULT_LOCALE
  }

  return rawLocale.toLowerCase().startsWith("zh") ? "zh-CN" : "en-US"
}

export function readPreferredLocale(): LocaleCode {
  if (typeof window !== "undefined") {
    try {
      const storedLocale = window.localStorage.getItem(LOCALE_STORAGE_KEY)
      if (storedLocale) {
        return normalizeLocale(storedLocale)
      }
    } catch {
      // Ignore localStorage failures and fall back to the browser locale.
    }

    return normalizeLocale(window.navigator.language)
  }

  return DEFAULT_LOCALE
}

export function applyLocale(locale: LocaleCode): void {
  if (typeof document !== "undefined") {
    document.documentElement.lang = locale
  }

  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, locale)
    } catch {
      // Ignore storage failures in private or restricted contexts.
    }
  }
}

export function getActiveLocale(): LocaleCode {
  if (typeof document !== "undefined" && document.documentElement.lang) {
    return normalizeLocale(document.documentElement.lang)
  }

  return readPreferredLocale()
}

export function translate(locale: LocaleCode, key: string, params?: Record<string, string | number>): string {
  const template = resolveMessage(messages[locale], key) ?? resolveMessage(messages[DEFAULT_LOCALE], key) ?? key

  if (!params) {
    return template
  }

  return template.replace(/\{(\w+)\}/g, (_, name: string) => String(params[name] ?? `{${name}}`))
}