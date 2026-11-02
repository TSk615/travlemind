<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue"
import type {
  ImageProvider,
  LlmAgentProvider,
  LlmModelInfo,
  LlmProviderProtocol,
  LlmSettingsInput,
  LlmWireApi,
  SearchServiceProvider,
  SearchServiceTransport,
  XhsAccountStatus,
  XhsBindingStatus
} from "@travelmind/shared-types"
import StatePanel from "@/components/StatePanel.vue"
import { api, getErrorMessage } from "@/lib/api"
import { useI18n } from "@/lib/useI18n"
import { useLlmSettingsStore } from "@/stores/llmSettings"

const settingsStore = useLlmSettingsStore()
const saveSuccess = ref<string | null>(null)
const clearPoiKey = ref(false)
const xhsStatus = ref<XhsAccountStatus | null>(null)
const xhsBinding = ref<XhsBindingStatus | null>(null)
const xhsPending = ref(false)
const xhsError = ref<string | null>(null)
const agentModelOptions = ref<LlmModelInfo[]>([])
const agentModelsLoading = ref(false)
const agentModelsError = ref<string | null>(null)
const agentTestLoading = ref(false)
const agentTestMessage = ref<string | null>(null)
const agentTestError = ref<string | null>(null)
const poiModelOptions = ref<LlmModelInfo[]>([])
const poiModelsLoading = ref(false)
const poiModelsError = ref<string | null>(null)
const poiTestLoading = ref(false)
const poiTestMessage = ref<string | null>(null)
const poiTestError = ref<string | null>(null)
let xhsPollTimer: number | null = null
let hydratingSettings = false
void settingsStore.bootstrap()

const form = reactive<{
  agent_provider_protocol: LlmProviderProtocol
  agent_base_url: string
  agent_api_key: string
  agent_model: string
  agent_wire_api: LlmWireApi
  agent_provider: LlmAgentProvider
  poi_provider_protocol: LlmProviderProtocol
  poi_base_url: string
  poi_api_key: string
  poi_model: string
  weather_model: string
  hotel_model: string
  transport_model: string
  poi_wire_api: LlmWireApi
  search_provider: SearchServiceProvider
  search_transport: SearchServiceTransport
  search_base_url: string
  search_api_key: string
  search_timeout_seconds: number
  xhs_source_enabled: boolean
  image_base_url: string
  image_api_key: string
  image_model: string
  image_provider: ImageProvider
}>({
  agent_provider_protocol: "openai",
  agent_base_url: "",
  agent_api_key: "",
  agent_model: "",
  agent_wire_api: "responses",
  agent_provider: "standard",
  poi_provider_protocol: "openai",
  poi_base_url: "",
  poi_api_key: "",
  poi_model: "",
  weather_model: "",
  hotel_model: "",
  transport_model: "",
  poi_wire_api: "responses",
  search_provider: "groksearch",
  search_transport: "mcp",
  search_base_url: "",
  search_api_key: "",
  search_timeout_seconds: 30,
  xhs_source_enabled: false,
  image_base_url: "",
  image_api_key: "",
  image_model: "",
  image_provider: "openai_compatible"
})

const enCopy = {
  kicker: "Settings",
  title: "Model settings",
  description:
    "Start with an API URL, key and model. Everything else is optional.",
  refresh: "Reload",
  save: "Save settings",
  saving: "Saving...",
  saveSuccessTitle: "Settings update",
  saveSuccessMessage: "Agent model settings and search service settings have been updated.",
  loadErrorTitle: "Unable to load settings",
  saveErrorTitle: "Unable to save settings",
  agentSection: "Agent model",
  agentSectionHint: "Controls the model endpoint used for generation and refinement.",
  protocolLabel: "Model protocol",
  protocolOpenAI: "OpenAI",
  protocolNewApi: "New API",
  protocolGemini: "Gemini",
  protocolClaude: "Claude",
  protocolNeiApi: "NEI API",
  providerLabel: "Planning provider",
  providerStandard: "Standard",
  providerLangGraph: "LangGraph",
  baseUrlLabel: "Base URL",
  baseUrlPlaceholder: "https://api.example.com/v1",
  modelLabel: "Model",
  modelPlaceholder: "Select a fetched model or enter a model ID",
  fetchModels: "Fetch models",
  fetchingModels: "Fetching...",
  modelFetchSuccess: "Models loaded. Choose one from the model field.",
  modelFetchEmpty: "The provider returned no selectable models.",
  modelFetchError: "Unable to fetch models",
  fetchedModelsLabel: "Fetched models",
  fetchedModelsHint: "Pick a fetched model to fill the model field, or keep typing a custom model name.",
  fetchedModelsPlaceholder: "Select a fetched model",
  currentModelOption: "current value",
  testConnection: "Test request",
  testingConnection: "Testing...",
  testConnectionSuccessTitle: "Connection test passed",
  testConnectionSuccess: "Model replied in {latency} ms.",
  testConnectionError: "Unable to test connection",
  endpointPreviewLabel: "Endpoint preview",
  wireApiLabel: "API format",
  wireApiResponses: "Responses API",
  wireApiChat: "Chat Completions API",
  apiKeyLabel: "API key",
  apiKeyPlaceholder: "Enter a new key to save or replace",
  storedKeyLabel: "Stored key",
  noStoredKey: "No API key is stored yet.",
  keyHelp: "Leave the API key blank to keep the current stored value.",
  searchSection: "Search service",
  searchSectionHint:
    "Controls the grounding service used by backend search and LangGraph roles. You can switch between MCP access and direct API access.",
  searchProviderLabel: "Search provider",
  searchProviderGrokSearch: "GrokSearch bridge",
  searchProviderTavily: "Tavily",
  searchProviderHint: "GrokSearch currently works through the MCP bridge only. Tavily currently works through the API only.",
  searchTransportLabel: "Connection type",
  searchTransportMcp: "MCP",
  searchTransportApi: "API",
  searchBaseUrlLabel: "Search base URL",
  searchBaseUrlMcpPlaceholder: "https://your-mcp-server.example.com/mcp",
  searchBaseUrlApiPlaceholder: "https://your-search-api.example.com",
  searchTimeoutLabel: "Timeout (seconds)",
  xhsToggleLabel: "Enable Xiaohongshu source",
  xhsToggleHint: "Allow Xiaohongshu posts to be merged into search grounding when available.",
  searchStoredKeyLabel: "Stored search key",
  statusHint: "Agent settings affect text model execution. Search service settings affect grounded search."
}

const zhCopy = {
  kicker: "设置",
  title: "模型设置",
  description:
    "先配置接口地址、密钥和模型，其他选项按需调整。",
  refresh: "重新加载",
  save: "保存设置",
  saving: "保存中...",
  saveSuccessTitle: "设置提示",
  saveSuccessMessage: "模型配置与搜索服务配置已更新。",
  loadErrorTitle: "无法加载设置",
  saveErrorTitle: "无法保存设置",
  agentSection: "行程主模型",
  agentSectionHint: "用于理解需求、生成行程和修改规划。",
  protocolLabel: "模型协议",
  protocolOpenAI: "OpenAI",
  protocolNewApi: "New API",
  protocolGemini: "Gemini",
  protocolClaude: "Claude",
  protocolNeiApi: "NEI API",
  providerLabel: "规划提供方",
  providerStandard: "标准模式",
  providerLangGraph: "LangGraph",
  baseUrlLabel: "接口地址",
  baseUrlPlaceholder: "https://api.example.com/v1",
  modelLabel: "模型",
  modelPlaceholder: "获取列表后选择，或输入模型名称",
  fetchModels: "获取模型列表",
  fetchingModels: "正在获取...",
  modelFetchSuccess: "模型列表已加载，请从模型字段中选择。",
  modelFetchEmpty: "服务商没有返回可选择的模型。",
  modelFetchError: "无法获取模型列表",
  fetchedModelsLabel: "可用模型",
  fetchedModelsHint: "可选择已获取的模型，也可以继续输入自定义模型名称。",
  fetchedModelsPlaceholder: "请选择模型",
  currentModelOption: "当前值",
  testConnection: "测试调用",
  testingConnection: "正在测试...",
  testConnectionSuccessTitle: "连接测试通过",
  testConnectionSuccess: "模型已在 {latency} 毫秒内响应。",
  testConnectionError: "无法测试连接",
  endpointPreviewLabel: "接口预览",
  wireApiLabel: "接口格式",
  wireApiResponses: "Responses 接口",
  wireApiChat: "Chat Completions 接口",
  apiKeyLabel: "API 密钥",
  apiKeyPlaceholder: "输入新的密钥以保存或替换",
  storedKeyLabel: "已保存的密钥",
  noStoredKey: "当前还没有保存 API 密钥。",
  keyHelp: "如果要保留当前已保存的 API 密钥，请将输入框留空。",
  searchSection: "搜索服务",
  searchSectionHint:
    "控制后端搜索与 LangGraph 角色使用的 grounding 服务。你可以在 MCP 访问和直接 API 访问之间切换。",
  searchProviderLabel: "搜索提供方",
  searchProviderGrokSearch: "GrokSearch 桥接",
  searchProviderTavily: "Tavily",
  searchProviderHint: "GrokSearch 目前仅支持通过 MCP 桥接使用；Tavily 目前仅支持 API 传输。",
  searchTransportLabel: "连接方式",
  searchTransportMcp: "MCP",
  searchTransportApi: "API",
  searchBaseUrlLabel: "搜索接口地址",
  searchBaseUrlMcpPlaceholder: "https://your-mcp-server.example.com/mcp",
  searchBaseUrlApiPlaceholder: "https://your-search-api.example.com",
  searchTimeoutLabel: "超时时间（秒）",
  xhsToggleLabel: "启用小红书来源",
  xhsToggleHint: "可用时允许将小红书帖子合并到搜索 grounding 结果中。",
  searchStoredKeyLabel: "已保存的搜索密钥",
  statusHint: "模型设置会影响模型执行；搜索服务设置会影响后端搜索，包括 MCP 或直接 API 调用。"
}

const simpleEnCopy = {
  configured: "Saved", incomplete: "Not configured", optional: "Optional", advanced: "Advanced connection options",
  advancedHint: "Protocol, API format and planning workflow", savedKey: "Key stored; leave blank to keep it.",
  newKey: "Your key is encrypted when saved.", requestHint: "Loading models does not verify generation. Testing sends a short request and may incur a small charge.",
  poiTitle: "Separate research model", poiHint: "Optional. POI, weather, hotel and transport roles otherwise use the main model.",
  followMain: "Follow the main model", poiDefault: "Default research model", followResearch: "Follow the default research model",
  roleModels: "Choose models for individual roles", roleModelsHint: "Leave a role blank to use the default research model.",
  weather: "Weather", hotel: "Hotels", transport: "Transport", resetPoi: "Clear separate model settings", resetPoiHint: "Takes effect after saving. Research roles will use the main model.",
  searchHint: "Normally uses the server's search service. Only change this to connect your own service.",
  serverDefault: "Server default", customSearch: "Custom service", searchConnection: "Advanced search options",
  statusHint: "Saving does not test model availability. Use Test request before generating a trip.",
  loading: "Loading settings…", connectionSummary: "Protocol and API format", endpointNote: "Request endpoint", modelNotListed: "The current model is not in the returned list. Choose an available model and test it."
}
const simpleZhCopy: typeof simpleEnCopy = {
  configured: "已保存", incomplete: "未配置", optional: "可选", advanced: "高级连接选项",
  advancedHint: "协议、接口格式和规划模式", savedKey: "已保存密钥；留空即可保留。",
  newKey: "密钥保存后会加密存储。", requestHint: "获取列表不代表模型可调用。测试会发送一条简短请求，可能产生少量费用。",
  poiTitle: "搜索专用模型", poiHint: "默认跟随主模型。只有需要为景点、天气、酒店和交通使用另一组模型时，才需要配置。",
  followMain: "跟随主模型", poiDefault: "搜索默认模型", followResearch: "跟随搜索默认模型",
  roleModels: "为专家单独选择模型", roleModelsHint: "留空即可跟随搜索默认模型，不需要分别填写。",
  weather: "天气", hotel: "酒店", transport: "交通", resetPoi: "清除独立模型配置", resetPoiHint: "保存后生效，搜索角色将改用主模型。",
  searchHint: "通常使用服务器默认搜索服务，无需填写。仅在接入自己的搜索服务时修改。",
  serverDefault: "服务器默认", customSearch: "自定义服务", searchConnection: "搜索高级选项",
  statusHint: "保存不代表模型可用，建议先测试调用，再生成行程。",
  loading: "正在加载设置…", connectionSummary: "协议与接口格式", endpointNote: "实际请求地址", modelNotListed: "当前模型不在返回列表中，请选择列表中的模型再测试。"
}

const { locale } = useI18n()
const copy = computed<typeof enCopy>(() => (locale.value === "zh-CN" ? ({ ...enCopy, ...zhCopy } as typeof enCopy) : enCopy))
const simple = computed(() => locale.value === "zh-CN" ? simpleZhCopy : simpleEnCopy)
const xhsAvailable = computed(() => settingsStore.settings?.search.xhs_available === true)
const agentModelMissing = computed(() => agentModelOptions.value.length > 0 && Boolean(form.agent_model.trim()) && !agentModelOptions.value.some(model => model.id === form.agent_model.trim()))
const poiModelMissing = computed(() => poiModelOptions.value.length > 0 && Boolean(form.poi_model.trim()) && !poiModelOptions.value.some(model => model.id === form.poi_model.trim()))
const protocolOptions = computed(() => [
  { value: "openai", label: copy.value.protocolOpenAI }, { value: "newapi", label: copy.value.protocolNewApi },
  { value: "gemini", label: copy.value.protocolGemini }, { value: "claude", label: copy.value.protocolClaude },
  { value: "neiapi", label: copy.value.protocolNeiApi }
])
const researchRoles = computed(() => [
  { key: "weather_model" as const, label: simple.value.weather },
  { key: "hotel_model" as const, label: simple.value.hotel },
  { key: "transport_model" as const, label: simple.value.transport }
])
const xhsCopy = computed(() =>
  locale.value === "zh-CN"
    ? {
        section: "小红书账号",
        hint: "绑定后可复用你自己的小红书登录态；未绑定或失效时，搜索会自动降级为非小红书来源。",
        statusLabel: "当前状态",
        statusBound: "已绑定",
        statusPending: "等待扫码",
        statusExpired: "会话已过期",
        statusUnbound: "未绑定",
        statusUnknown: "状态未知",
        connect: "开始绑定",
        reconnect: "重新绑定",
        unbind: "解绑",
        binding: "处理中...",
        pendingTitle: "请使用小红书扫码完成绑定",
        openLink: "打开绑定链接",
        codeLabel: "验证码",
        lastBound: "最近绑定",
        lastAvailable: "最近可用",
        boundAs: "绑定账号",
        bindFailed: "无法开始小红书绑定",
        statusFailed: "无法获取小红书绑定状态",
        pollFailed: "无法刷新绑定状态",
        deleteFailed: "无法解绑小红书账号",
        waiting: "正在等待扫码确认。",
        authorized: "绑定成功，后续搜索会复用该登录态。",
        cancelled: "绑定已取消。",
        failed: "绑定失败，请重试。",
        expired: "绑定二维码已过期，请重新发起。"
      }
    : {
        section: "Xiaohongshu Account",
        hint: "After binding once, TravelMind reuses your own Xiaohongshu session. If the session is missing or expired, search falls back to non-XHS sources.",
        statusLabel: "Current status",
        statusBound: "Bound",
        statusPending: "Waiting for scan",
        statusExpired: "Session expired",
        statusUnbound: "Not bound",
        statusUnknown: "Unknown",
        connect: "Bind account",
        reconnect: "Rebind",
        unbind: "Unbind",
        binding: "Working...",
        pendingTitle: "Scan with Xiaohongshu to finish binding",
        openLink: "Open bind link",
        codeLabel: "Verification code",
        lastBound: "Last bound",
        lastAvailable: "Last available",
        boundAs: "Bound profile",
        bindFailed: "Unable to start Xiaohongshu binding",
        statusFailed: "Unable to load Xiaohongshu binding status",
        pollFailed: "Unable to refresh binding status",
        deleteFailed: "Unable to unbind Xiaohongshu account",
        waiting: "Waiting for QR scan confirmation.",
        authorized: "Binding succeeded. Future searches will reuse this session.",
        cancelled: "Binding was cancelled.",
        failed: "Binding failed. Try again.",
        expired: "The QR code expired. Start a new binding flow."
      }
)
const isGrokSearchProvider = computed(() => form.search_provider === "groksearch")
const agentProtocolDefaultBaseUrls: Record<LlmProviderProtocol, string> = {
  openai: "https://api.openai.com/v1",
  newapi: "http://localhost:3000/v1",
  gemini: "https://generativelanguage.googleapis.com/v1beta",
  claude: "https://api.anthropic.com/v1",
  neiapi: "https://api.neiapi.com/v1"
}
const agentBaseUrlPlaceholder = computed(() => agentProtocolDefaultBaseUrls[form.agent_provider_protocol])
const poiBaseUrlPlaceholder = computed(() => agentProtocolDefaultBaseUrls[form.poi_provider_protocol])
const openAiWireApiLocked = computed(() => form.agent_provider_protocol === "openai")
const openAiPoiWireApiLocked = computed(() => form.poi_provider_protocol === "openai")

function buildEndpointPreview(
  provider: LlmProviderProtocol,
  baseUrl: string,
  fallbackBaseUrl: string,
  modelValue: string,
  wireApi: LlmWireApi
): string {
  const base = (baseUrl.trim() || fallbackBaseUrl).replace(/\/+$/, "")
  if (provider === "claude") {
    return base.endsWith("/messages") ? base : `${base}/messages`
  }
  if (provider === "gemini") {
    const model = modelValue.trim() || "{model}"
    const normalized = base.endsWith("/models") ? base : `${base}/models`
    return `${normalized}/${model.startsWith("models/") ? model.slice("models/".length) : model}:generateContent`
  }
  if (wireApi === "responses") {
    return base.endsWith("/responses") ? base : `${base}/responses`
  }
  return base.endsWith("/chat/completions") ? base : `${base}/chat/completions`
}

function wireApiForSearchModel(model: string): LlmWireApi {
  const normalized = model.trim().toLowerCase()
  if (normalized.startsWith("console/")) {
    return "responses"
  }
  if (normalized.startsWith("web/")) {
    return "chat_completions"
  }
  return form.poi_wire_api
}

const agentEndpointPreview = computed(() =>
  buildEndpointPreview(form.agent_provider_protocol, form.agent_base_url, agentBaseUrlPlaceholder.value, form.agent_model, form.agent_wire_api)
)
const poiEndpointPreview = computed(() =>
  buildEndpointPreview(form.poi_provider_protocol, form.poi_base_url, poiBaseUrlPlaceholder.value, form.poi_model, wireApiForSearchModel(form.poi_model))
)
function defaultWireApiForProtocol(protocol: LlmProviderProtocol): LlmWireApi {
  return protocol === "newapi" || protocol === "neiapi" ? "chat_completions" : "responses"
}
const searchBaseUrlPlaceholder = computed(() =>
  isGrokSearchProvider.value || form.search_transport === "mcp"
    ? copy.value.searchBaseUrlMcpPlaceholder
    : copy.value.searchBaseUrlApiPlaceholder
)
const xhsStatusLabel = computed(() => {
  if (xhsBinding.value?.status === "pending") {
    return xhsCopy.value.statusPending
  }
  if (xhsStatus.value?.xhs_bound) {
    return xhsCopy.value.statusBound
  }
  if (xhsStatus.value?.xhs_session_expired) {
    return xhsCopy.value.statusExpired
  }
  if (xhsStatus.value?.xhs_binding_required) {
    return xhsCopy.value.statusUnbound
  }
  return xhsCopy.value.statusUnknown
})
const xhsActionLabel = computed(() => (xhsStatus.value?.xhs_bound || xhsStatus.value?.xhs_session_expired ? xhsCopy.value.reconnect : xhsCopy.value.connect))
const xhsBindingMessage = computed(() => {
  switch (xhsBinding.value?.status) {
    case "authorized":
      return xhsCopy.value.authorized
    case "cancelled":
      return xhsCopy.value.cancelled
    case "failed":
      return xhsCopy.value.failed
    case "expired":
      return xhsCopy.value.expired
    case "pending":
      return xhsCopy.value.waiting
    default:
      return xhsBinding.value?.message ?? null
  }
})

watch(
  () => settingsStore.settings,
  (settings) => {
    hydratingSettings = true
    form.agent_base_url = settings?.agent.base_url ?? ""
    form.agent_model = settings?.agent.model ?? ""
    form.agent_api_key = ""
    form.agent_provider_protocol = settings?.agent.provider_protocol ?? "openai"
    form.agent_wire_api = settings?.agent.wire_api ?? defaultWireApiForProtocol(form.agent_provider_protocol)
    if (form.agent_provider_protocol === "openai") {
      form.agent_wire_api = "responses"
    }
    form.agent_provider = settings?.agent.agent_provider ?? "standard"
    form.poi_provider_protocol = settings?.agent.poi_provider_protocol ?? "openai"
    form.poi_base_url = settings?.agent.poi_base_url ?? ""
    form.poi_api_key = ""
    clearPoiKey.value = false
    form.poi_model = settings?.agent.poi_model ?? ""
    form.weather_model = settings?.agent.weather_model ?? form.poi_model
    form.hotel_model = settings?.agent.hotel_model ?? form.poi_model
    form.transport_model = settings?.agent.transport_model ?? form.poi_model
    form.poi_wire_api = settings?.agent.poi_wire_api ?? defaultWireApiForProtocol(form.poi_provider_protocol)
    form.search_provider = settings?.search.provider ?? "groksearch"
    form.search_transport =
      settings?.search.provider === "groksearch"
        ? "mcp"
        : settings?.search.provider === "tavily"
          ? "api"
          : (settings?.search.transport ?? "mcp")
    form.search_base_url = settings?.search.base_url ?? ""
    form.search_api_key = ""
    form.search_timeout_seconds = Number(settings?.search.timeout_seconds ?? 30)
    form.xhs_source_enabled = Boolean(settings?.search.xhs_source_enabled)
    form.image_base_url = settings?.image.base_url ?? ""
    form.image_api_key = ""
    form.image_model = settings?.image.model ?? ""
    form.image_provider = settings?.image.provider ?? "openai_compatible"
    agentModelOptions.value = []
    agentModelsError.value = null
    agentTestMessage.value = null
    agentTestError.value = null
    poiModelOptions.value = []
    poiModelsError.value = null
    poiTestMessage.value = null
    poiTestError.value = null
    hydratingSettings = false
  },
  { immediate: true }
)

watch(
  () => form.agent_provider_protocol,
  (provider, previousProvider) => {
    if (hydratingSettings) return
    const previousDefault = previousProvider ? agentProtocolDefaultBaseUrls[previousProvider] : ""
    if (!form.agent_base_url.trim() || form.agent_base_url.trim() === previousDefault) {
      form.agent_base_url = agentProtocolDefaultBaseUrls[provider]
    }
    const previousWireDefault = previousProvider ? defaultWireApiForProtocol(previousProvider) : null
    if (provider === "openai" || !form.agent_wire_api || form.agent_wire_api === previousWireDefault) {
      form.agent_wire_api = defaultWireApiForProtocol(provider)
    }
    agentModelOptions.value = []
    agentModelsError.value = null
    agentTestMessage.value = null
    agentTestError.value = null
  },
  { flush: "sync" }
)

watch(
  () => form.poi_provider_protocol,
  (provider, previousProvider) => {
    if (hydratingSettings) return
    const previousDefault = previousProvider ? agentProtocolDefaultBaseUrls[previousProvider] : ""
    if (!form.poi_base_url.trim() || form.poi_base_url.trim() === previousDefault) {
      form.poi_base_url = agentProtocolDefaultBaseUrls[provider]
    }
    const previousWireDefault = previousProvider ? defaultWireApiForProtocol(previousProvider) : null
    if (provider === "openai" || !form.poi_wire_api || form.poi_wire_api === previousWireDefault) {
      form.poi_wire_api = defaultWireApiForProtocol(provider)
    }
    poiModelOptions.value = []
    poiModelsError.value = null
    poiTestMessage.value = null
    poiTestError.value = null
  },
  { flush: "sync" }
)

watch(
  () => form.search_provider,
  (provider) => {
    if (provider === "groksearch") {
      form.search_transport = "mcp"
    } else if (provider === "tavily") {
      form.search_transport = "api"
    }
  }
)

function stopXhsPolling() {
  if (xhsPollTimer !== null) {
    window.clearTimeout(xhsPollTimer)
    xhsPollTimer = null
  }
}

function scheduleXhsPoll(bindId: string) {
  stopXhsPolling()
  xhsPollTimer = window.setTimeout(() => {
    void pollXhsBinding(bindId)
  }, 2000)
}

function formatStamp(value?: string | null): string | null {
  if (!value) {
    return null
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

async function refreshXhsStatus() {
  if (!xhsAvailable.value) return
  try {
    const status = await api.getXhsStatus()
    xhsStatus.value = status
    if (status.active_binding) {
      xhsBinding.value = status.active_binding
      if (status.active_binding.status === "pending") {
        scheduleXhsPoll(status.active_binding.bind_id)
      } else {
        stopXhsPolling()
      }
    } else if (!xhsBinding.value || xhsBinding.value.status === "pending") {
      xhsBinding.value = null
      stopXhsPolling()
    }
    xhsError.value = null
  } catch (error) {
    xhsError.value = getErrorMessage(error, xhsCopy.value.statusFailed)
  }
}

async function startXhsBinding() {
  xhsPending.value = true
  xhsError.value = null
  try {
    const binding = await api.startXhsBind()
    xhsBinding.value = binding
    await refreshXhsStatus()
    if (binding.status === "pending") {
      scheduleXhsPoll(binding.bind_id)
    }
  } catch (error) {
    xhsError.value = getErrorMessage(error, xhsCopy.value.bindFailed)
  } finally {
    xhsPending.value = false
  }
}

async function pollXhsBinding(bindId: string) {
  try {
    const binding = await api.getXhsBind(bindId)
    xhsBinding.value = binding
    if (binding.status === "pending") {
      scheduleXhsPoll(bindId)
      return
    }
    stopXhsPolling()
    await refreshXhsStatus()
  } catch (error) {
    stopXhsPolling()
    xhsError.value = getErrorMessage(error, xhsCopy.value.pollFailed)
  }
}

async function deleteXhsBinding() {
  xhsPending.value = true
  xhsError.value = null
  stopXhsPolling()
  try {
    xhsStatus.value = await api.deleteXhsBind()
    xhsBinding.value = null
  } catch (error) {
    xhsError.value = getErrorMessage(error, xhsCopy.value.deleteFailed)
  } finally {
    xhsPending.value = false
  }
}

async function refresh() {
  saveSuccess.value = null
  await settingsStore.fetch(true)
  if (xhsAvailable.value) await refreshXhsStatus()
}

async function fetchAgentModels() {
  agentModelsLoading.value = true
  agentModelsError.value = null
  agentTestMessage.value = null
  agentTestError.value = null
  saveSuccess.value = null
  try {
    const result = await api.listLlmModels({
      provider_protocol: form.agent_provider_protocol,
      base_url: form.agent_base_url.trim() || undefined,
      api_key: form.agent_api_key.trim() || undefined
    })
    form.agent_base_url = result.base_url || form.agent_base_url
    agentModelOptions.value = result.models
    if (result.models.length > 0 && !form.agent_model.trim()) {
      form.agent_model = result.models[0].id
    }
    saveSuccess.value = result.models.length > 0 ? copy.value.modelFetchSuccess : copy.value.modelFetchEmpty
  } catch (error) {
    agentModelsError.value = getErrorMessage(error, copy.value.modelFetchError)
  } finally {
    agentModelsLoading.value = false
  }
}

async function testAgentConnection() {
  agentTestLoading.value = true
  agentTestMessage.value = null
  agentTestError.value = null
  saveSuccess.value = null
  try {
    const result = await api.testLlmConnection({
      provider_protocol: form.agent_provider_protocol,
      base_url: form.agent_base_url.trim() || undefined,
      api_key: form.agent_api_key.trim() || undefined,
      model: form.agent_model.trim() || undefined,
      wire_api: form.agent_wire_api
    })
    agentTestMessage.value = copy.value.testConnectionSuccess.replace("{latency}", String(result.latency_ms))
  } catch (error) {
    agentTestError.value = getErrorMessage(error, copy.value.testConnectionError)
  } finally {
    agentTestLoading.value = false
  }
}

async function fetchPoiModels() {
  poiModelsLoading.value = true
  poiModelsError.value = null
  poiTestMessage.value = null
  poiTestError.value = null
  saveSuccess.value = null
  try {
    const result = await api.listLlmModels({
      scope: "poi",
      provider_protocol: form.poi_provider_protocol,
      base_url: form.poi_base_url.trim() || undefined,
      api_key: form.poi_api_key.trim() || undefined
    })
    form.poi_base_url = result.base_url || form.poi_base_url
    poiModelOptions.value = result.models
    if (!form.poi_model.trim()) {
      form.poi_model = result.models[0]?.id ?? ""
    }
    saveSuccess.value = result.models.length > 0 ? copy.value.modelFetchSuccess : copy.value.modelFetchEmpty
  } catch (error) {
    poiModelsError.value = getErrorMessage(error, copy.value.modelFetchError)
  } finally {
    poiModelsLoading.value = false
  }
}

async function testPoiConnection() {
  poiTestLoading.value = true
  poiTestMessage.value = null
  poiTestError.value = null
  saveSuccess.value = null
  try {
    const result = await api.testLlmConnection({
      scope: "poi",
      provider_protocol: form.poi_provider_protocol,
      base_url: form.poi_base_url.trim() || undefined,
      api_key: form.poi_api_key.trim() || undefined,
      model: form.poi_model.trim() || undefined,
      wire_api: wireApiForSearchModel(form.poi_model)
    })
    poiTestMessage.value = copy.value.testConnectionSuccess.replace("{latency}", String(result.latency_ms))
  } catch (error) {
    poiTestError.value = getErrorMessage(error, copy.value.testConnectionError)
  } finally {
    poiTestLoading.value = false
  }
}

async function save() {
  saveSuccess.value = null

  const payload: LlmSettingsInput = {
    agent: {
      provider_protocol: form.agent_provider_protocol,
      base_url: form.agent_base_url.trim(),
      model: form.agent_model.trim(),
      wire_api: form.agent_wire_api,
      agent_provider: form.agent_provider,
      poi_provider_protocol: form.poi_provider_protocol,
      poi_base_url: form.poi_base_url.trim(),
      poi_model: form.poi_model.trim(),
      weather_model: form.weather_model.trim(),
      hotel_model: form.hotel_model.trim(),
      transport_model: form.transport_model.trim(),
      poi_wire_api: wireApiForSearchModel(form.poi_model)
    },
    search: {
      provider: form.search_provider,
      transport: form.search_provider === "groksearch" ? "mcp" : form.search_provider === "tavily" ? "api" : form.search_transport,
      base_url: form.search_base_url.trim(),
      timeout_seconds: Number.isFinite(form.search_timeout_seconds) && form.search_timeout_seconds > 0 ? form.search_timeout_seconds : 30,
      ...(xhsAvailable.value ? { xhs_source_enabled: form.xhs_source_enabled } : {})
    },
    image: {
      base_url: form.image_base_url.trim(),
      model: form.image_model.trim(),
      provider: form.image_provider
    }
  }

  const nextAgentApiKey = form.agent_api_key.trim()
  if (nextAgentApiKey) {
    payload.agent = {
      ...payload.agent,
      api_key: nextAgentApiKey
    }
  }

  if (clearPoiKey.value) payload.agent = { ...payload.agent, poi_api_key: "" }

  const nextPoiApiKey = form.poi_api_key.trim()
  if (nextPoiApiKey) {
    payload.agent = {
      ...payload.agent,
      poi_api_key: nextPoiApiKey
    }
  }

  const nextSearchApiKey = form.search_api_key.trim()
  if (nextSearchApiKey) {
    payload.search = {
      ...payload.search,
      api_key: nextSearchApiKey
    }
  }

  const nextImageApiKey = form.image_api_key.trim()
  if (nextImageApiKey) {
    payload.image = {
      ...payload.image,
      api_key: nextImageApiKey
    }
  }

  try {
    await settingsStore.save(payload)
    form.agent_api_key = ""
    form.poi_api_key = ""
    form.search_api_key = ""
    form.image_api_key = ""
    agentTestMessage.value = null
    agentTestError.value = null
    poiTestMessage.value = null
    poiTestError.value = null
    saveSuccess.value = copy.value.saveSuccessMessage
  } catch {
    // The store already exposes a user-facing save error state.
  }
}

onBeforeUnmount(() => {
  stopXhsPolling()
})

function clearPoiOverride() {
  for (const field of ["poi_base_url", "poi_api_key", "poi_model", "weather_model", "hotel_model", "transport_model"] as const) {
    form[field] = ""
  }
  clearPoiKey.value = true
  poiModelOptions.value = []
  poiTestMessage.value = null
  poiTestError.value = null
}

watch(xhsAvailable, (available) => {
  if (available) {
    void refreshXhsStatus()
  } else {
    stopXhsPolling()
    xhsStatus.value = null
    xhsBinding.value = null
    xhsError.value = null
  }
}, { immediate: true })
</script>

<template>
  <section class="settings-page">
    <header class="settings-heading">
      <div>
        <p class="kicker">{{ copy.kicker }}</p>
        <h1>{{ copy.title }}</h1>
        <p class="muted">{{ copy.description }}</p>
      </div>
      <button type="button" :disabled="settingsStore.loading || settingsStore.pending" @click="refresh">{{ copy.refresh }}</button>
    </header>

    <StatePanel v-if="settingsStore.error" kind="error" :title="copy.loadErrorTitle" :message="settingsStore.error" compact />
    <StatePanel v-if="saveSuccess" kind="info" :title="copy.saveSuccessTitle" :message="saveSuccess" compact />
    <StatePanel v-if="settingsStore.saveError" kind="error" :title="copy.saveErrorTitle" :message="settingsStore.saveError" compact />
    <p v-if="settingsStore.loading && !settingsStore.loaded" role="status" class="muted">{{ simple.loading }}</p>

    <form class="settings-form" @submit.prevent="save">
      <fieldset class="settings-fields" :disabled="settingsStore.loading || settingsStore.pending || !settingsStore.settings">
        <section class="panel settings-card" aria-labelledby="main-model-title">
          <div class="settings-card-heading">
            <div>
              <h2 id="main-model-title">{{ copy.agentSection }}</h2>
              <p class="muted">{{ copy.agentSectionHint }}</p>
            </div>
            <span class="settings-badge" :class="{ 'settings-badge--saved': settingsStore.isConfigured }">{{ settingsStore.isConfigured ? simple.configured : simple.incomplete }}</span>
          </div>
          <div class="settings-grid">
            <div class="field settings-full">
              <label for="agent-base-url">{{ copy.baseUrlLabel }}</label>
              <input id="agent-base-url" v-model="form.agent_base_url" type="url" :placeholder="agentBaseUrlPlaceholder" autocomplete="url" />
            </div>
            <div class="field">
              <label for="agent-api-key">{{ copy.apiKeyLabel }}</label>
              <input id="agent-api-key" v-model="form.agent_api_key" type="password" autocomplete="new-password" :placeholder="copy.apiKeyPlaceholder" />
              <p class="settings-help">{{ settingsStore.hasStoredKey ? simple.savedKey : simple.newKey }}</p>
            </div>
            <div class="field">
              <label for="agent-model">{{ copy.modelLabel }}</label>
              <input id="agent-model" v-model="form.agent_model" list="agent-model-options" :placeholder="copy.modelPlaceholder" autocomplete="off" />
              <datalist id="agent-model-options"><option v-for="model in agentModelOptions" :key="model.id" :value="model.id">{{ model.name || model.id }}</option></datalist>
            </div>
          </div>
          <div class="settings-tools">
            <button type="button" :disabled="agentModelsLoading || agentTestLoading" @click="fetchAgentModels">{{ agentModelsLoading ? copy.fetchingModels : copy.fetchModels }}</button>
            <button type="button" :disabled="agentTestLoading || agentModelsLoading" @click="testAgentConnection">{{ agentTestLoading ? copy.testingConnection : copy.testConnection }}</button>
          </div>
          <p v-if="agentModelMissing" role="status" class="settings-help settings-model-warning">{{ simple.modelNotListed }}</p>
          <p class="settings-help">{{ simple.requestHint }}</p>
          <StatePanel v-if="agentModelsError" kind="error" :title="copy.modelFetchError" :message="agentModelsError" compact />
          <StatePanel v-if="agentTestMessage" kind="info" :title="copy.testConnectionSuccessTitle" :message="agentTestMessage" compact />
          <StatePanel v-if="agentTestError" kind="error" :title="copy.testConnectionError" :message="agentTestError" compact />

          <details class="settings-nested" data-testid="main-advanced">
            <summary>{{ simple.advanced }}</summary>
            <div class="settings-grid settings-details-body">
              <div class="field">
                <label for="agent-provider-protocol">{{ copy.protocolLabel }}</label>
                <select id="agent-provider-protocol" v-model="form.agent_provider_protocol"><option v-for="option in protocolOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select>
              </div>
              <div class="field">
                <label for="agent-wire-api">{{ copy.wireApiLabel }}</label>
                <select id="agent-wire-api" v-model="form.agent_wire_api" :disabled="openAiWireApiLocked"><option value="responses">{{ copy.wireApiResponses }}</option><option value="chat_completions">{{ copy.wireApiChat }}</option></select>
              </div>
              <div class="field">
                <label for="agent-provider">{{ copy.providerLabel }}</label>
                <select id="agent-provider" v-model="form.agent_provider"><option value="standard">{{ copy.providerStandard }}</option><option value="langgraph">{{ copy.providerLangGraph }}</option></select>
              </div>
              <p class="settings-help settings-full">{{ simple.endpointNote }}：<code>{{ agentEndpointPreview }}</code></p>
            </div>
          </details>
        </section>

        <details class="panel settings-card settings-disclosure" data-testid="research-model-settings">
          <summary>
            <span class="settings-summary-copy"><strong>{{ simple.poiTitle }}</strong><span>{{ simple.poiHint }}</span></span>
            <span class="settings-badge">{{ form.poi_base_url.trim() && form.poi_model.trim() ? simple.configured : simple.followMain }}</span>
          </summary>
          <div class="settings-details-body">
            <div class="settings-grid">
              <div class="field settings-full">
                <label for="poi-base-url">{{ copy.baseUrlLabel }}</label>
                <input id="poi-base-url" v-model="form.poi_base_url" type="url" :placeholder="poiBaseUrlPlaceholder" />
              </div>
              <div class="field">
                <label for="poi-api-key">{{ copy.apiKeyLabel }}</label>
                <input id="poi-api-key" v-model="form.poi_api_key" type="password" autocomplete="new-password" :placeholder="copy.apiKeyPlaceholder" />
                <p class="settings-help">{{ settingsStore.settings?.agent.poi_has_api_key ? simple.savedKey : simple.newKey }}</p>
              </div>
              <div class="field">
                <label for="poi-model">{{ simple.poiDefault }}</label>
                <input id="poi-model" v-model="form.poi_model" list="research-model-options" :placeholder="copy.modelPlaceholder" autocomplete="off" />
                <datalist id="research-model-options"><option v-for="model in poiModelOptions" :key="model.id" :value="model.id">{{ model.name || model.id }}</option></datalist>
              </div>
            </div>
            <div class="settings-tools">
              <button type="button" :disabled="poiModelsLoading || poiTestLoading" @click="fetchPoiModels">{{ poiModelsLoading ? copy.fetchingModels : copy.fetchModels }}</button>
              <button type="button" :disabled="poiTestLoading || poiModelsLoading" @click="testPoiConnection">{{ poiTestLoading ? copy.testingConnection : copy.testConnection }}</button>
            </div>
            <p v-if="poiModelMissing" role="status" class="settings-help settings-model-warning">{{ simple.modelNotListed }}</p>
            <StatePanel v-if="poiModelsError" kind="error" :title="copy.modelFetchError" :message="poiModelsError" compact />
            <StatePanel v-if="poiTestMessage" kind="info" :title="copy.testConnectionSuccessTitle" :message="poiTestMessage" compact />
            <StatePanel v-if="poiTestError" kind="error" :title="copy.testConnectionError" :message="poiTestError" compact />
            <details class="settings-nested" data-testid="research-roles">
              <summary>{{ simple.roleModels }}</summary>
              <div class="settings-details-body">
                <p class="settings-help">{{ simple.roleModelsHint }}</p>
                <div class="settings-grid">
                  <div v-for="role in researchRoles" :key="role.key" class="field">
                    <label :for="role.key">{{ role.label }}</label>
                    <input :id="role.key" v-model="form[role.key]" list="research-model-options" :placeholder="simple.followResearch" autocomplete="off" />
                  </div>
                </div>
              </div>
            </details>
            <details class="settings-nested">
              <summary>{{ simple.connectionSummary }}</summary>
              <div class="settings-grid settings-details-body">
                <div class="field"><label for="poi-provider-protocol">{{ copy.protocolLabel }}</label><select id="poi-provider-protocol" v-model="form.poi_provider_protocol"><option v-for="option in protocolOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></div>
                <div class="field"><label for="poi-wire-api">{{ copy.wireApiLabel }}</label><select id="poi-wire-api" v-model="form.poi_wire_api" :disabled="openAiPoiWireApiLocked"><option value="responses">{{ copy.wireApiResponses }}</option><option value="chat_completions">{{ copy.wireApiChat }}</option></select></div>
                <p class="settings-help settings-full">{{ simple.endpointNote }}：<code>{{ poiEndpointPreview }}</code></p>
              </div>
            </details>
            <div class="settings-reset"><button type="button" @click="clearPoiOverride">{{ simple.resetPoi }}</button><span class="settings-help">{{ simple.resetPoiHint }}</span></div>
          </div>
        </details>
        <details class="panel settings-card settings-disclosure" data-testid="search-service-settings">
          <summary>
            <span class="settings-summary-copy"><strong>{{ copy.searchSection }}</strong><span>{{ simple.searchHint }}</span></span>
            <span class="settings-badge">{{ form.search_base_url.trim() ? simple.customSearch : simple.serverDefault }}</span>
          </summary>
          <div class="settings-details-body">
            <div class="settings-grid">
              <div class="field settings-full">
                <label for="search-provider">{{ copy.searchProviderLabel }}</label>
                <select id="search-provider" v-model="form.search_provider"><option value="groksearch">{{ copy.searchProviderGrokSearch }}</option><option value="tavily">{{ copy.searchProviderTavily }}</option></select>
              </div>
              <div class="field settings-full">
                <label for="search-base-url">{{ copy.searchBaseUrlLabel }}</label>
                <input id="search-base-url" v-model="form.search_base_url" type="url" :placeholder="searchBaseUrlPlaceholder" />
              </div>
              <div class="field settings-full">
                <label for="search-api-key">{{ copy.apiKeyLabel }}</label>
                <input id="search-api-key" v-model="form.search_api_key" type="password" autocomplete="new-password" :placeholder="copy.apiKeyPlaceholder" />
                <p class="settings-help">{{ settingsStore.settings?.search.has_api_key ? simple.savedKey : simple.newKey }}</p>
              </div>
            </div>
            <details class="settings-nested">
              <summary>{{ simple.searchConnection }}</summary>
              <div class="settings-grid settings-details-body">
                <div class="field"><label for="search-timeout">{{ copy.searchTimeoutLabel }}</label><input id="search-timeout" v-model.number="form.search_timeout_seconds" type="number" min="1" step="1" /></div>
                <p class="settings-help settings-full">{{ copy.searchProviderHint }}</p>
              </div>
            </details>

            <section v-if="xhsAvailable" class="settings-source" data-testid="xhs-settings" aria-labelledby="xhs-settings-title">
              <h3 id="xhs-settings-title">{{ xhsCopy.section }}</h3>
              <p class="settings-help">{{ xhsCopy.hint }}</p>
              <label class="settings-checkbox"><input v-model="form.xhs_source_enabled" type="checkbox" /><span>{{ copy.xhsToggleLabel }}</span></label>
              <p class="settings-help">{{ xhsCopy.statusLabel }}：{{ xhsStatusLabel }}</p>
              <p v-if="xhsBindingMessage" class="settings-help">{{ xhsBindingMessage }}</p>
              <p v-if="xhsStatus?.xhs_display_name" class="settings-help">{{ xhsCopy.boundAs }}：{{ xhsStatus.xhs_display_name }}</p>
              <p v-if="formatStamp(xhsStatus?.xhs_last_bound_at)" class="settings-help">{{ xhsCopy.lastBound }}：{{ formatStamp(xhsStatus?.xhs_last_bound_at) }}</p>
              <StatePanel v-if="xhsError" kind="error" :title="xhsCopy.section" :message="xhsError" compact />
              <div class="settings-tools">
                <button type="button" :disabled="xhsPending" @click="startXhsBinding">{{ xhsPending ? xhsCopy.binding : xhsActionLabel }}</button>
                <button v-if="xhsStatus?.xhs_bound || xhsBinding" type="button" :disabled="xhsPending" @click="deleteXhsBinding">{{ xhsCopy.unbind }}</button>
              </div>
              <div v-if="xhsBinding?.status === 'pending'" class="settings-binding">
                <p><strong>{{ xhsCopy.pendingTitle }}</strong></p>
                <img v-if="xhsBinding.qr_image_data_url" :src="xhsBinding.qr_image_data_url" alt="Xiaohongshu bind QR" />
                <p v-if="xhsBinding.verification_url"><a :href="xhsBinding.verification_url" target="_blank" rel="noreferrer">{{ xhsCopy.openLink }}</a></p>
                <p v-if="xhsBinding.verification_code">{{ xhsCopy.codeLabel }}：{{ xhsBinding.verification_code }}</p>
              </div>
            </section>
          </div>
        </details>
      </fieldset>

      <footer class="settings-save">
        <p class="settings-help">{{ simple.statusHint }}</p>
        <button class="primary" type="submit" :disabled="settingsStore.pending || settingsStore.loading || !settingsStore.settings">{{ settingsStore.pending ? copy.saving : copy.save }}</button>
      </footer>
    </form>
  </section>
</template>

<style scoped>
.settings-page {
  width: 100%;
  max-width: 880px;
  margin: 0 auto;
  display: grid;
  gap: 20px;
}
.settings-heading, .settings-card-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.settings-heading h1 { margin: 4px 0 8px; }
.settings-heading p, .settings-card-heading p { margin: 0; }
.settings-heading > button { flex-shrink: 0; }
.settings-form, .settings-fields { display: grid; gap: 18px; }
.settings-fields { min-width: 0; border: 0; margin: 0; padding: 0; }
.settings-card { min-width: 0; padding: 26px; }
.settings-card h2 { margin: 0 0 6px; font-size: 1.16rem; }
.settings-card-heading { margin-bottom: 22px; }
.settings-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.settings-full { grid-column: 1 / -1; }
.settings-grid .field { min-width: 0; display: flex; flex-direction: column; gap: 8px; }
.settings-grid input, .settings-grid select { min-height: 48px; }
.settings-model-warning { color: #8c4d15; }
.settings-help { margin: 6px 0 0; color: var(--tm-muted); font-size: .87rem; line-height: 1.65; overflow-wrap: anywhere; }
.settings-tools { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }
.settings-tools button { padding: 10px 17px; font-size: .9rem; }
.settings-badge {
  flex-shrink: 0;
  display: inline-flex;
  padding: 5px 11px;
  border-radius: 999px;
  background: rgba(255, 255, 255, .55);
  color: var(--tm-muted);
  font-size: .78rem;
  font-weight: 600;
  line-height: 1.4;
}
.settings-badge--saved { color: #23663c; background: #d9eddf; }
.settings-disclosure > summary { display: flex; align-items: center; gap: 18px; padding-right: 28px; position: relative; }
.settings-disclosure > summary::after { position: absolute; right: 0; top: 4px; }
.settings-summary-copy { flex: 1; display: grid; gap: 6px; min-width: 0; }
.settings-summary-copy > strong { font-size: 1rem; }
.settings-summary-copy > span { color: var(--tm-muted); font-size: .86rem; line-height: 1.65; }
summary { cursor: pointer; list-style: none; }
summary::-webkit-details-marker { display: none; }
summary::after { content: "+"; font-size: 1.15rem; font-weight: 400; color: var(--tm-muted); }
details[open] > summary::after { content: "−"; }
summary:focus-visible { outline: 2px solid var(--tm-accent); outline-offset: 7px; border-radius: 4px; }
.settings-nested { margin-top: 20px; border-top: 1px solid rgba(95, 99, 104, .15); padding-top: 16px; }
.settings-nested > summary { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: var(--tm-muted); font-size: .88rem; font-weight: 600; }
.settings-details-body { padding-top: 22px; }
.settings-card > :deep(.state-panel) { margin-top: 14px; }
.settings-reset { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin-top: 24px; }
.settings-reset button { font-size: .84rem; padding: 8px 14px; }
.settings-reset .settings-help { margin: 0; }
.settings-source { border-top: 1px solid rgba(95, 99, 104, .15); padding-top: 18px; margin-top: 22px; }
.settings-source h3 { margin: 0; font-size: 1rem; }
.settings-checkbox { display: flex; align-items: center; gap: 10px; margin-top: 16px; font-size: .9rem; }
.settings-checkbox input { width: auto; margin: 0; }
.settings-binding img { max-width: 220px; width: 100%; border-radius: 12px; }
.settings-save { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 4px 0 12px; }
.settings-save .settings-help { margin: 0; }
.settings-save button { flex-shrink: 0; min-width: 140px; }
code { font-size: .82rem; overflow-wrap: anywhere; }
@media (max-width: 640px) {
  .settings-page { gap: 16px; }
  .settings-card { padding: 20px; }
  .settings-grid { grid-template-columns: minmax(0, 1fr); }
  .settings-card-heading { gap: 10px; }
  .settings-disclosure > summary { align-items: flex-start; flex-wrap: wrap; gap: 10px; }
  .settings-summary-copy { flex-basis: 100%; }
  .settings-save { align-items: stretch; flex-direction: column; gap: 12px; }
  .settings-save button { width: 100%; }
}
</style>
