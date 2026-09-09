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
import LlmStatusNotice from "@/components/LlmStatusNotice.vue"
import StatePanel from "@/components/StatePanel.vue"
import { api, getErrorMessage } from "@/lib/api"
import { useI18n } from "@/lib/useI18n"
import { useLlmSettingsStore } from "@/stores/llmSettings"

const settingsStore = useLlmSettingsStore()
const saveSuccess = ref<string | null>(null)
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
  title: "Agent and Search Settings",
  description:
    "Configure the agent model and search service used for itinerary planning.",
  refresh: "Reload",
  save: "Save settings",
  saving: "Saving...",
  saveSuccessTitle: "Settings saved",
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
  providerHelloAgents: "HelloAgents (PoC)",
  baseUrlLabel: "Base URL",
  baseUrlPlaceholder: "https://api.example.com/v1",
  modelLabel: "Model",
  modelPlaceholder: "gpt-5.4",
  fetchModels: "Fetch models",
  fetchingModels: "Fetching...",
  modelFetchSuccess: "Models loaded. Choose one from the model field.",
  modelFetchEmpty: "The provider returned no selectable models.",
  modelFetchError: "Unable to fetch models",
  fetchedModelsLabel: "Fetched models",
  fetchedModelsHint: "Pick a fetched model to fill the model field, or keep typing a custom model name.",
  fetchedModelsPlaceholder: "Select a fetched model",
  currentModelOption: "current value",
  testConnection: "Test connection",
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
    "Controls the search grounding service used by backend search and HelloAgents. You can switch between MCP access and direct API access.",
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
  title: "模型与搜索设置",
  description:
    "模型配置与搜索服务配置分开管理。后端会使用已保存的搜索服务执行搜索与 HelloAgents 工具调用。",
  refresh: "重新加载",
  save: "保存设置",
  saving: "保存中...",
  saveSuccessTitle: "设置已保存",
  saveSuccessMessage: "模型配置与搜索服务配置已更新。",
  loadErrorTitle: "无法加载设置",
  saveErrorTitle: "无法保存设置",
  agentSection: "模型配置",
  agentSectionHint: "控制生成和润色时使用的模型接口。",
  protocolLabel: "模型协议",
  protocolOpenAI: "OpenAI",
  protocolNewApi: "New API",
  protocolGemini: "Gemini",
  protocolClaude: "Claude",
  protocolNeiApi: "NEI API",
  providerLabel: "规划提供方",
  providerStandard: "标准模式",
  providerHelloAgents: "HelloAgents（PoC）",
  baseUrlLabel: "接口地址",
  baseUrlPlaceholder: "https://api.example.com/v1",
  modelLabel: "模型",
  modelPlaceholder: "gpt-5.4",
  fetchModels: "获取模型列表",
  fetchingModels: "正在获取...",
  modelFetchSuccess: "模型列表已加载，请从模型字段中选择。",
  modelFetchEmpty: "服务商没有返回可选择的模型。",
  modelFetchError: "无法获取模型列表",
  fetchedModelsLabel: "可用模型",
  fetchedModelsHint: "可选择已获取的模型，也可以继续输入自定义模型名称。",
  fetchedModelsPlaceholder: "请选择模型",
  currentModelOption: "当前值",
  testConnection: "测试连接",
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
    "控制后端搜索与 HelloAgents 使用的搜索服务。你可以在 MCP 访问和直接 API 访问之间切换。",
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

const { locale } = useI18n()
const copy = computed<typeof enCopy>(() => (locale.value === "zh-CN" ? ({ ...enCopy, ...zhCopy } as typeof enCopy) : enCopy))
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
const agentStoredKeyText = computed(() => settingsStore.settings?.agent.api_key_masked?.trim() || copy.value.noStoredKey)
const poiStoredKeyText = computed(() => settingsStore.settings?.agent.poi_api_key_masked?.trim() || copy.value.noStoredKey)
const searchStoredKeyText = computed(() => settingsStore.settings?.search.api_key_masked?.trim() || copy.value.noStoredKey)
const isGrokSearchProvider = computed(() => form.search_provider === "groksearch")
const isTavilyProvider = computed(() => form.search_provider === "tavily")
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

const agentEndpointPreview = computed(() =>
  buildEndpointPreview(form.agent_provider_protocol, form.agent_base_url, agentBaseUrlPlaceholder.value, form.agent_model, form.agent_wire_api)
)
const poiEndpointPreview = computed(() =>
  buildEndpointPreview(form.poi_provider_protocol, form.poi_base_url, poiBaseUrlPlaceholder.value, form.poi_model, form.poi_wire_api)
)
const agentModelValue = computed(() => form.agent_model.trim())
const agentModelValueInOptions = computed(() =>
  agentModelOptions.value.some((model) => model.id === agentModelValue.value)
)
const poiModelValue = computed(() => form.poi_model.trim())
const poiModelValueInOptions = computed(() =>
  poiModelOptions.value.some((model) => model.id === poiModelValue.value)
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
    form.poi_model = settings?.agent.poi_model ?? ""
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
  },
  { immediate: true }
)

watch(
  () => form.agent_provider_protocol,
  (provider, previousProvider) => {
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
  }
)

watch(
  () => form.poi_provider_protocol,
  (provider, previousProvider) => {
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
  }
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
  await refreshXhsStatus()
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

function handleAgentModelSelection(event: Event) {
  form.agent_model = (event.target as HTMLSelectElement).value
}

function handlePoiModelSelection(event: Event) {
  form.poi_model = (event.target as HTMLSelectElement).value
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
    if (result.models.length > 0 && !form.poi_model.trim()) {
      form.poi_model = result.models[0].id
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
      wire_api: form.poi_wire_api
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
      poi_wire_api: form.poi_wire_api
    },
    search: {
      provider: form.search_provider,
      transport: form.search_provider === "groksearch" ? "mcp" : form.search_provider === "tavily" ? "api" : form.search_transport,
      base_url: form.search_base_url.trim(),
      timeout_seconds: Number.isFinite(form.search_timeout_seconds) && form.search_timeout_seconds > 0 ? form.search_timeout_seconds : 30,
      xhs_source_enabled: form.xhs_source_enabled
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

void refreshXhsStatus()
</script>

<template>
  <section class="page-grid" style="max-width: 1040px; margin: 0 auto;">
    <article class="panel panel-stack">
      <div class="form-toolbar">
        <div>
          <p class="kicker">{{ copy.kicker }}</p>
          <h1>{{ copy.title }}</h1>
          <p class="muted">{{ copy.description }}</p>
        </div>
        <div class="inline-actions">
          <button type="button" :disabled="settingsStore.loading || settingsStore.pending" @click="refresh">{{ copy.refresh }}</button>
        </div>
      </div>

      <LlmStatusNotice compact />

      <StatePanel
        v-if="settingsStore.error"
        kind="error"
        :title="copy.loadErrorTitle"
        :message="settingsStore.error"
        compact
      />

      <StatePanel
        v-if="saveSuccess"
        kind="info"
        :title="copy.saveSuccessTitle"
        :message="saveSuccess"
        compact
      />

      <StatePanel
        v-if="settingsStore.saveError"
        kind="error"
        :title="copy.saveErrorTitle"
        :message="settingsStore.saveError"
        compact
      />

      <form class="form-grid" @submit.prevent="save">
        <div class="field field--full panel-subsection">
          <p class="kicker">{{ copy.agentSection }}</p>
          <p class="muted">{{ copy.agentSectionHint }}</p>
        </div>

        <div class="field">
          <label for="agent-provider-protocol">{{ copy.protocolLabel }}</label>
          <select id="agent-provider-protocol" v-model="form.agent_provider_protocol">
            <option value="openai">{{ copy.protocolOpenAI }}</option>
            <option value="newapi">{{ copy.protocolNewApi }}</option>
            <option value="gemini">{{ copy.protocolGemini }}</option>
            <option value="claude">{{ copy.protocolClaude }}</option>
            <option value="neiapi">{{ copy.protocolNeiApi }}</option>
          </select>
        </div>

        <div class="field">
          <label for="agent-provider">{{ copy.providerLabel }}</label>
          <select id="agent-provider" v-model="form.agent_provider">
            <option value="standard">{{ copy.providerStandard }}</option>
            <option value="helloagents">{{ copy.providerHelloAgents }}</option>
          </select>
        </div>

        <div class="field field--full">
          <label for="agent-base-url">{{ copy.baseUrlLabel }}</label>
          <input id="agent-base-url" v-model="form.agent_base_url" :placeholder="agentBaseUrlPlaceholder" />
          <p class="muted"><strong>{{ copy.endpointPreviewLabel }}:</strong> {{ agentEndpointPreview }}</p>
        </div>

        <StatePanel
          v-if="agentModelsError"
          class="field field--full"
          kind="error"
          :title="copy.modelFetchError"
          :message="agentModelsError"
          compact
        />
        <StatePanel
          v-if="agentTestMessage"
          class="field field--full"
          kind="info"
          :title="copy.testConnectionSuccessTitle"
          :message="agentTestMessage"
          compact
        />
        <StatePanel
          v-if="agentTestError"
          class="field field--full"
          kind="error"
          :title="copy.testConnectionError"
          :message="agentTestError"
          compact
        />

        <div class="field">
          <label for="agent-model">{{ copy.modelLabel }}</label>
          <input
            id="agent-model"
            v-model="form.agent_model"
            :placeholder="copy.modelPlaceholder"
          />
          <select
            v-if="agentModelOptions.length > 0"
            :value="agentModelValue"
            :aria-label="copy.fetchedModelsLabel"
            @change="handleAgentModelSelection"
          >
            <option value="">{{ copy.fetchedModelsPlaceholder }}</option>
            <option v-if="agentModelValue && !agentModelValueInOptions" :value="agentModelValue">
              {{ agentModelValue }} ({{ copy.currentModelOption }})
            </option>
            <option v-for="model in agentModelOptions" :key="model.id" :value="model.id">
              {{ model.name && model.name !== model.id ? `${model.name} (${model.id})` : model.id }}
            </option>
          </select>
          <p v-if="agentModelOptions.length > 0" class="muted">{{ copy.fetchedModelsHint }}</p>
        </div>

        <div class="field">
          <label>&nbsp;</label>
          <button type="button" :disabled="agentModelsLoading || settingsStore.pending" @click="fetchAgentModels">
            {{ agentModelsLoading ? copy.fetchingModels : copy.fetchModels }}
          </button>
        </div>

        <div class="field">
          <label>&nbsp;</label>
          <button type="button" :disabled="agentTestLoading || settingsStore.pending" @click="testAgentConnection">
            {{ agentTestLoading ? copy.testingConnection : copy.testConnection }}
          </button>
        </div>

        <div class="field">
          <label for="agent-wire-api">{{ copy.wireApiLabel }}</label>
          <select id="agent-wire-api" v-model="form.agent_wire_api" :disabled="openAiWireApiLocked">
            <option value="responses">{{ copy.wireApiResponses }}</option>
            <option value="chat_completions">{{ copy.wireApiChat }}</option>
          </select>
        </div>

        <div class="field field--full">
          <label for="agent-api-key">{{ copy.apiKeyLabel }}</label>
          <input id="agent-api-key" v-model="form.agent_api_key" type="password" autocomplete="new-password" :placeholder="copy.apiKeyPlaceholder" />
        </div>

        <div class="field field--full">
          <p class="muted"><strong>{{ copy.storedKeyLabel }}:</strong> {{ agentStoredKeyText }}</p>
          <p class="muted">{{ copy.keyHelp }}</p>
        </div>

        <div class="field field--full panel-subsection">
          <p class="kicker">搜索专用模型</p>
          <p class="muted">统一用于 POI、天气、酒店和交通专家的联网检索。当前推荐使用 Web/grok-chat-fast。</p>
        </div>

        <div class="field">
          <label for="poi-provider-protocol">{{ copy.protocolLabel }}</label>
          <select id="poi-provider-protocol" v-model="form.poi_provider_protocol">
            <option value="openai">{{ copy.protocolOpenAI }}</option>
            <option value="newapi">{{ copy.protocolNewApi }}</option>
            <option value="gemini">{{ copy.protocolGemini }}</option>
            <option value="claude">{{ copy.protocolClaude }}</option>
            <option value="neiapi">{{ copy.protocolNeiApi }}</option>
          </select>
        </div>

        <div class="field">
          <label for="poi-wire-api">{{ copy.wireApiLabel }}</label>
          <select id="poi-wire-api" v-model="form.poi_wire_api" :disabled="openAiPoiWireApiLocked">
            <option value="responses">{{ copy.wireApiResponses }}</option>
            <option value="chat_completions">{{ copy.wireApiChat }}</option>
          </select>
        </div>

        <div class="field field--full">
          <label for="poi-base-url">{{ copy.baseUrlLabel }}</label>
          <input id="poi-base-url" v-model="form.poi_base_url" :placeholder="poiBaseUrlPlaceholder" />
          <p class="muted"><strong>{{ copy.endpointPreviewLabel }}:</strong> {{ poiEndpointPreview }}</p>
        </div>

        <StatePanel
          v-if="poiModelsError"
          class="field field--full"
          kind="error"
          :title="copy.modelFetchError"
          :message="poiModelsError"
          compact
        />
        <StatePanel
          v-if="poiTestMessage"
          class="field field--full"
          kind="info"
          :title="copy.testConnectionSuccessTitle"
          :message="poiTestMessage"
          compact
        />
        <StatePanel
          v-if="poiTestError"
          class="field field--full"
          kind="error"
          :title="copy.testConnectionError"
          :message="poiTestError"
          compact
        />

        <div class="field">
          <label for="poi-model">{{ copy.modelLabel }}</label>
          <input id="poi-model" v-model="form.poi_model" :placeholder="'Web/grok-chat-fast'" />
          <select
            v-if="poiModelOptions.length > 0"
            :value="poiModelValue"
            :aria-label="copy.fetchedModelsLabel"
            @change="handlePoiModelSelection"
          >
            <option value="">{{ copy.fetchedModelsPlaceholder }}</option>
            <option v-if="poiModelValue && !poiModelValueInOptions" :value="poiModelValue">
              {{ poiModelValue }} ({{ copy.currentModelOption }})
            </option>
            <option v-for="model in poiModelOptions" :key="model.id" :value="model.id">
              {{ model.name && model.name !== model.id ? `${model.name} (${model.id})` : model.id }}
            </option>
          </select>
          <p v-if="poiModelOptions.length > 0" class="muted">{{ copy.fetchedModelsHint }}</p>
        </div>

        <div class="field">
          <label>&nbsp;</label>
          <button type="button" :disabled="poiModelsLoading || settingsStore.pending" @click="fetchPoiModels">
            {{ poiModelsLoading ? copy.fetchingModels : copy.fetchModels }}
          </button>
        </div>

        <div class="field">
          <label>&nbsp;</label>
          <button type="button" :disabled="poiTestLoading || settingsStore.pending" @click="testPoiConnection">
            {{ poiTestLoading ? copy.testingConnection : copy.testConnection }}
          </button>
        </div>

        <div class="field">
          <label for="poi-api-key">{{ copy.apiKeyLabel }}</label>
          <input id="poi-api-key" v-model="form.poi_api_key" type="password" autocomplete="new-password" :placeholder="copy.apiKeyPlaceholder" />
        </div>

        <div class="field field--full">
          <p class="muted">
            <strong>{{ copy.storedKeyLabel }}:</strong>
            {{ poiStoredKeyText }}
          </p>
          <p class="muted">如果希望所有搜索角色使用主模型，请将本区域所有字段留空。</p>
        </div>

        <div class="field field--full panel-subsection">
          <p class="kicker">{{ copy.searchSection }}</p>
          <p class="muted">{{ copy.searchSectionHint }}</p>
        </div>

        <div class="field">
          <label for="search-provider">{{ copy.searchProviderLabel }}</label>
          <select id="search-provider" v-model="form.search_provider">
            <option value="groksearch">{{ copy.searchProviderGrokSearch }}</option>
            <option value="tavily">{{ copy.searchProviderTavily }}</option>
          </select>
        </div>

        <div class="field">
          <label for="search-transport">{{ copy.searchTransportLabel }}</label>
          <select id="search-transport" v-model="form.search_transport" :disabled="isGrokSearchProvider || isTavilyProvider">
            <option value="mcp">{{ copy.searchTransportMcp }}</option>
            <option value="api" :disabled="isGrokSearchProvider">{{ copy.searchTransportApi }}</option>
          </select>
        </div>

        <div class="field">
          <label for="search-timeout">{{ copy.searchTimeoutLabel }}</label>
          <input id="search-timeout" v-model.number="form.search_timeout_seconds" type="number" min="1" step="1" />
        </div>

        <div class="field field--full" v-if="isGrokSearchProvider || isTavilyProvider">
          <p class="muted">{{ copy.searchProviderHint }}</p>
        </div>

        <div class="field field--full">
          <label for="search-base-url">{{ copy.searchBaseUrlLabel }}</label>
          <input id="search-base-url" v-model="form.search_base_url" :placeholder="searchBaseUrlPlaceholder" />
        </div>

        <div class="field field--full">
          <label for="search-api-key">{{ copy.apiKeyLabel }}</label>
          <input id="search-api-key" v-model="form.search_api_key" type="password" autocomplete="new-password" :placeholder="copy.apiKeyPlaceholder" />
        </div>

        <div class="field field--full">
          <label class="checkbox-row">
            <input v-model="form.xhs_source_enabled" type="checkbox" />
            <span>{{ copy.xhsToggleLabel }}</span>
          </label>
          <p class="muted">{{ copy.xhsToggleHint }}</p>
        </div>

        <div class="field field--full">
          <p class="muted"><strong>{{ copy.searchStoredKeyLabel }}:</strong> {{ searchStoredKeyText }}</p>
          <p class="muted">{{ copy.keyHelp }}</p>
        </div>

        <div class="field field--full panel-subsection">
          <p class="kicker">{{ xhsCopy.section }}</p>
          <p class="muted">{{ xhsCopy.hint }}</p>
        </div>

        <div class="field field--full">
          <p class="muted"><strong>{{ xhsCopy.statusLabel }}:</strong> {{ xhsStatusLabel }}</p>
          <p v-if="xhsStatus?.xhs_message" class="muted">{{ xhsStatus.xhs_message }}</p>
          <p v-if="xhsBindingMessage" class="muted">{{ xhsBindingMessage }}</p>
          <p v-if="xhsStatus?.xhs_display_name" class="muted"><strong>{{ xhsCopy.boundAs }}:</strong> {{ xhsStatus.xhs_display_name }}</p>
          <p v-if="formatStamp(xhsStatus?.xhs_last_bound_at)" class="muted"><strong>{{ xhsCopy.lastBound }}:</strong> {{ formatStamp(xhsStatus?.xhs_last_bound_at) }}</p>
          <p v-if="formatStamp(xhsStatus?.xhs_last_available_at)" class="muted"><strong>{{ xhsCopy.lastAvailable }}:</strong> {{ formatStamp(xhsStatus?.xhs_last_available_at) }}</p>
        </div>

        <StatePanel
          v-if="xhsError"
          class="field field--full"
          kind="error"
          :title="xhsCopy.section"
          :message="xhsError"
          compact
        />

        <div class="field field--full inline-actions">
          <button type="button" :disabled="xhsPending" @click="startXhsBinding">
            {{ xhsPending ? xhsCopy.binding : xhsActionLabel }}
          </button>
          <button
            v-if="xhsStatus?.xhs_bound || xhsBinding"
            type="button"
            class="ghost-button"
            :disabled="xhsPending"
            @click="deleteXhsBinding"
          >
            {{ xhsCopy.unbind }}
          </button>
        </div>

        <div v-if="xhsBinding?.status === 'pending'" class="field field--full">
          <p><strong>{{ xhsCopy.pendingTitle }}</strong></p>
          <div v-if="xhsBinding.qr_image_data_url" style="margin: 0.75rem 0;">
            <img :src="xhsBinding.qr_image_data_url" alt="Xiaohongshu bind QR" style="max-width: 240px; border-radius: 16px;" />
          </div>
          <p v-if="xhsBinding.verification_url" class="muted">
            <a :href="xhsBinding.verification_url" target="_blank" rel="noreferrer">{{ xhsCopy.openLink }}</a>
          </p>
          <p v-if="xhsBinding.verification_code" class="muted"><strong>{{ xhsCopy.codeLabel }}:</strong> {{ xhsBinding.verification_code }}</p>
        </div>

        <div class="field field--full inline-actions">
          <button class="primary" type="submit" :disabled="settingsStore.pending">
            {{ settingsStore.pending ? copy.saving : copy.save }}
          </button>
          <p class="muted">{{ copy.statusHint }}</p>
        </div>
      </form>
    </article>
  </section>
</template>
