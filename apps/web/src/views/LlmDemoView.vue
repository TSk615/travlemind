<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue"
import type { LlmProviderProtocol, LlmWireApi, SearchServiceProvider, SearchServiceTransport } from "@travelmind/shared-types"
import { apiFetch, handleUnauthorizedStatus } from "@/lib/api"
import { useI18n } from "@/lib/useI18n"
import { useLlmSettingsStore } from "@/stores/llmSettings"

interface ChatMessage {
  role: "user" | "assistant" | "error"
  content: string
}

interface DemoConfig {
  provider_protocol: LlmProviderProtocol
  base_url: string
  api_key: string
  model: string
  wire_api: LlmWireApi
  system_prompt: string
  stream: boolean
}

interface SearchProbeConfig {
  provider: SearchServiceProvider
  transport: SearchServiceTransport
  base_url: string
  api_key: string
  timeout_seconds: number
  query: string
}

interface SearchProbeHit {
  title: string
  url: string
  snippet: string
  published_at?: string | null
}

interface SearchProbeResult {
  provider: string
  transport: string
  base_url: string
  available_tools: string[]
  operation: string
  arguments: Record<string, unknown>
  result: Record<string, unknown>
  hits: SearchProbeHit[]
}

interface SearchImageProbeResult extends SearchProbeResult {
  strategy: string
  image_urls: string[]
  fetch_payloads: Array<{ url: string; payload: Record<string, unknown> }>
}

interface XhsImageFieldDebug {
  path: string
  value: unknown
}

interface XhsParsedPost {
  post_id: string
  title: string
  url: string
  author: string
  published_at?: string | null
  excerpt: string
  engagement_hint?: string | null
  tags: string[]
  image_urls: string[]
  raw_destination_hint?: string | null
}

interface XhsImageDebugRecord {
  record_index: number
  note_ref?: string | null
  detail_applied: boolean
  detail_error?: string | null
  included_in_posts: boolean
  dedupe_reason?: string | null
  record_summary: {
    post_id?: string | null
    title?: string | null
    url?: string | null
    author?: string | null
    note_type?: string | null
    raw_excerpt?: string | null
    merged_excerpt?: string | null
  }
  raw_image_fields: XhsImageFieldDebug[]
  merged_image_fields: XhsImageFieldDebug[]
  raw_image_candidates: string[]
  merged_image_candidates: string[]
  parsed_post?: XhsParsedPost | null
}

interface XhsImageProbeResult {
  base_url: string
  destination: string
  queries: string[]
  limit_per_query: number
  record_count: number
  post_count: number
  posts: XhsParsedPost[]
  records: XhsImageDebugRecord[]
}

interface EnvelopeError {
  error?: { message?: string } | string
  message?: string
}

interface SearchProbeEnvelope {
  data?: SearchProbeResult | null
}

interface SearchImageProbeEnvelope {
  data?: SearchImageProbeResult | null
}

interface TavilyImageItem {
  url?: string
  title?: string | null
  source_domain?: string | null
  description?: string | null
}

interface TavilyResultImageItem {
  result_title: string
  result_url: string
  source_domain?: string | null
  url: string
  description?: string | null
}

interface TavilyImageCandidateItem {
  source: "top_level" | "result" | string
  source_domain?: string | null
  url: string
  title?: string | null
  result_title?: string | null
  result_url?: string | null
  description?: string | null
}

interface TavilyImagesProbeResult {
  provider: string
  base_url: string
  request: Record<string, unknown>
  raw_result: Record<string, unknown>
  image_candidates?: TavilyImageCandidateItem[]
  image_candidates_total?: number
  image_candidates_truncated?: boolean
  top_level_images: TavilyImageItem[]
  top_level_images_total?: number
  top_level_images_truncated?: boolean
  result_images: TavilyResultImageItem[]
  result_images_total?: number
  result_images_truncated?: boolean
}

interface TavilyImagesProbeEnvelope {
  data?: TavilyImagesProbeResult | null
}

interface PoiSpecialistProbeResult {
  prompt_version: string
  system_prompt: string
  model: string
  provider_protocol: string
  wire_api: string
  latency_ms: number
  payload_bytes: number
  input_snapshot: Record<string, unknown>
  prompt_payload: Record<string, unknown>
  search: Record<string, unknown>
  warnings: string[]
  citations: string[]
  raw_text: string
  parsed_json?: Record<string, unknown> | null
  parse_error?: string | null
}

interface PoiSpecialistProbeEnvelope {
  data?: PoiSpecialistProbeResult | null
}

interface XhsImageProbeEnvelope {
  data?: XhsImageProbeResult | null
}

const settingsStore = useLlmSettingsStore()
const { locale } = useI18n()
void settingsStore.bootstrap()

const enCopy = {
  kicker: "LLM demo",
  title: "Third-party model test bench",
  description: "Use this page to test the model relay and the configured search service without going through the trip workflow.",
  baseUrlLabel: "Base URL",
  modelLabel: "Model",
  apiFormatLabel: "API format",
  apiKeyLabel: "API key",
  systemPromptLabel: "System prompt",
  streamLabel: "Use streaming",
  send: "Send",
  sending: "Streaming...",
  clear: "Clear chat",
  searchSectionTitle: "Search smoke test",
  searchDescription: "Run a direct search probe against the configured provider and inspect the raw payload.",
  searchProviderLabel: "Search provider",
  searchTransportLabel: "Transport",
  searchBaseUrlLabel: "Search base URL",
  searchApiKeyLabel: "Search API key",
  searchTimeoutLabel: "Timeout (seconds)",
  searchQueryLabel: "Search query",
  searchPlaceholder: "Kyoto coffee shops near Kyoto Station",
  probeSearch: "Probe search",
  probingSearch: "Probing...",
  clearSearch: "Clear search",
  poiSectionTitle: "POI specialist probe",
  poiDescription: "Run only the prompt-only HelloAgents POI specialist and inspect the payload and returned JSON.",
  poiDestinationLabel: "Destination",
  poiOriginLabel: "Origin",
  poiStartDateLabel: "Start date",
  poiEndDateLabel: "End date",
  poiBudgetLabel: "Budget",
  poiTravelersLabel: "Travelers",
  poiPaceLabel: "Pace",
  poiTransportLabel: "Transport",
  poiAccommodationLabel: "Stay preference",
  poiInterestsLabel: "Interests (one per line)",
  poiUserInputLabel: "User request",
  poiUseSearchLabel: "Show prompt-only search skip metadata",
  probePoi: "Run POI specialist",
  probingPoi: "Running POI...",
  clearPoi: "Clear POI probe",
  poiResultsTitle: "POI specialist result",
  poiResultsEmpty: "No POI specialist probe yet.",
  poiFeaturedPoisTitle: "featured_pois",
  poiFeaturedPoisEmpty: "No featured_pois were parsed.",
  poiParsedJsonTitle: "Parsed JSON",
  poiSystemPromptTitle: "System prompt",
  poiPromptPayloadTitle: "Prompt payload",
  poiRawTextTitle: "Model raw text",
  poiSearchTitle: "Search status",
  poiRequestTitle: "POI request",
  poiRequestEmpty: "No POI request yet.",
  poiResponseTitle: "POI response",
  poiResponseEmpty: "No POI response yet.",
  imageSectionTitle: "Image capability test",
  imageDescription: "Test whether the configured search service returns images directly or only after page fetch extraction.",
  imageToolLabel: "Preferred tool",
  imageToolPlaceholder: "Leave blank to auto-pick",
  probeImages: "Probe images",
  probingImages: "Probing images...",
  clearImages: "Clear image probe",
  imageResultsTitle: "Image probe results",
  imageResultsEmpty: "No image probe yet.",
  imageUrlsEmpty: "No image URLs were extracted.",
  imageRequestTitle: "Image probe request",
  imageRequestEmpty: "No image probe request yet.",
  imageResponseTitle: "Image probe response",
  imageResponseEmpty: "No image probe response yet.",
  imageStrategyLabel: "Strategy",
  xhsSectionTitle: "XHS image debug",
  xhsDescription: "Run the internal Xiaohongshu crawler with your bound account and compare raw image fields with parsed image_urls.",
  xhsBoundHint: "Requires a bound Xiaohongshu account in Settings.",
  xhsDestinationLabel: "Destination",
  xhsQueriesLabel: "Queries (one per line)",
  xhsLimitLabel: "Limit per query",
  probeXhs: "Probe XHS images",
  probingXhs: "Probing XHS...",
  clearXhs: "Clear XHS probe",
  xhsResultsTitle: "XHS image debug results",
  xhsResultsEmpty: "No XHS image probe yet.",
  xhsRecordsCount: "Raw records: {count}",
  xhsPostsCount: "Parsed posts: {count}",
  xhsRawCandidatesLabel: "Raw image candidates",
  xhsMergedCandidatesLabel: "Merged image candidates",
  xhsParsedCandidatesLabel: "Parsed image URLs",
  xhsFieldDetailsLabel: "Image field details",
  xhsRawFieldsLabel: "Raw image fields",
  xhsMergedFieldsLabel: "Merged image fields",
  xhsRequestTitle: "XHS request",
  xhsRequestEmpty: "No XHS request yet.",
  xhsResponseTitle: "XHS response",
  xhsResponseEmpty: "No XHS response yet.",
  tavilySectionTitle: "Tavily image search",
  tavilyDescription: "Call Tavily /search directly with include_images enabled and inspect the returned image structures.",
  tavilyBaseUrlLabel: "Tavily base URL",
  tavilyApiKeyLabel: "Tavily API key",
  tavilySavedKeyHint: "Leave blank to reuse your saved Tavily search key.",
  tavilyDepthLabel: "Search depth",
  tavilyMaxResultsLabel: "Max results",
  tavilyIncludeDescriptionsLabel: "Include image descriptions",
  probeTavily: "Probe Tavily",
  probingTavily: "Probing Tavily...",
  clearTavily: "Clear Tavily probe",
  tavilyResultsTitle: "Tavily image results",
  tavilyResultsEmpty: "No Tavily probe yet.",
  tavilyCandidatesTitle: "Usable image candidates",
  tavilyCandidatesCount: "Candidates: {count}",
  tavilyTopImagesTitle: "Top-level images",
  tavilyResultImagesTitle: "Result images",
  tavilyImagesEmpty: "No image URLs returned by Tavily.",
  tavilyTopImagesCount: "Top-level images: {count}",
  tavilyResultImagesCount: "Result images: {count}",
  openImageLabel: "Open image",
  openSourceLabel: "Open source",
  tavilyRequestTitle: "Tavily request",
  tavilyRequestEmpty: "No Tavily request yet.",
  tavilyResponseTitle: "Tavily response",
  tavilyResponseEmpty: "No Tavily response yet.",
  chatTitle: "Chat",
  chatEmpty: "No messages yet.",
  userRole: "User",
  assistantRole: "Assistant",
  errorRole: "Error",
  composerPlaceholder: "Say hello and ask the model to confirm it can respond.",
  rawRequestTitle: "LLM request",
  rawRequestEmpty: "No request yet.",
  rawResponseTitle: "LLM response",
  rawResponseEmpty: "No response yet.",
  searchResultsTitle: "Search results",
  searchResultsEmpty: "No search probe yet.",
  searchRequestTitle: "Search request",
  searchRequestEmpty: "No search request yet.",
  searchResponseTitle: "Search response",
  searchResponseEmpty: "No search response yet.",
  searchHitsEmpty: "The probe succeeded but returned no extractable hits.",
  availableToolsLabel: "Available tools",
  operationLabel: "Selected operation",
  endpointLabel: "Endpoint",
  defaultSystemPrompt: "You are a helpful travel planning assistant. Reply briefly and clearly.",
  defaultInput: "Hello, please say hi and confirm you can respond normally.",
  defaultSearchQuery: "Kyoto coffee shops near Kyoto Station",
  defaultXhsDestination: "Shantou",
  defaultXhsQueries: "Shantou hotels\nShantou where to stay",
  unknownRequestFailure: "Unknown request failure",
  requestFailedWithStatus: "Request failed with status {status}",
  responsesNoText: "Responses API did not return text output",
  responsesStreamNoText: "Responses API stream did not contain assistant text",
  chatNoText: "Chat Completions API did not return message content",
  chatStreamNoText: "Chat Completions API stream did not contain assistant text",
  invalidSearchEnvelope: "Search probe did not return a valid envelope",
  noStoredSearchKey: "Leave blank to reuse the saved search key."
}

const zhCopy = {
  kicker: "模型测试",
  title: "第三方模型测试台",
  description: "这个页面不经过行程流程，直接测试模型中转层和搜索服务是否可用。",
  baseUrlLabel: "接口地址",
  modelLabel: "模型",
  apiFormatLabel: "接口格式",
  apiKeyLabel: "API 密钥",
  systemPromptLabel: "系统提示词",
  streamLabel: "启用流式",
  send: "发送测试消息",
  sending: "流式接收中...",
  clear: "清空对话",
  searchSectionTitle: "GrokSearch 快速探测",
  searchDescription: "直接打到当前搜索服务，快速确认 bridge、MCP 工具和返回结果是否正常。",
  searchProviderLabel: "搜索提供方",
  searchTransportLabel: "传输方式",
  searchBaseUrlLabel: "搜索接口地址",
  searchApiKeyLabel: "搜索 API 密钥",
  searchTimeoutLabel: "超时（秒）",
  searchQueryLabel: "搜索词",
  searchPlaceholder: "京都站附近安静咖啡店",
  probeSearch: "测试搜索",
  probingSearch: "搜索中...",
  clearSearch: "清空搜索",
  poiSectionTitle: "POI 专家测试",
  poiDescription: "只运行 prompt-only 的 HelloAgents POI 专家，直接查看提示词 payload 和返回 JSON。",
  poiDestinationLabel: "目的地",
  poiOriginLabel: "出发地",
  poiStartDateLabel: "开始日期",
  poiEndDateLabel: "结束日期",
  poiBudgetLabel: "预算",
  poiTravelersLabel: "人数",
  poiPaceLabel: "节奏",
  poiTransportLabel: "交通方式",
  poiAccommodationLabel: "住宿偏好",
  poiInterestsLabel: "兴趣点（每行一个）",
  poiUserInputLabel: "用户原始需求",
  poiUseSearchLabel: "显示 prompt-only 搜索跳过信息",
  probePoi: "运行 POI 专家",
  probingPoi: "POI 运行中...",
  clearPoi: "清空 POI 测试",
  poiResultsTitle: "POI 专家结果",
  poiResultsEmpty: "还没有 POI 专家测试。",
  poiFeaturedPoisTitle: "featured_pois",
  poiFeaturedPoisEmpty: "没有解析出 featured_pois。",
  poiParsedJsonTitle: "解析后的 JSON",
  poiSystemPromptTitle: "系统提示词",
  poiPromptPayloadTitle: "实际调用 payload",
  poiRawTextTitle: "模型原文",
  poiSearchTitle: "搜索状态",
  poiRequestTitle: "POI 请求",
  poiRequestEmpty: "还没有 POI 请求。",
  poiResponseTitle: "POI 响应",
  poiResponseEmpty: "还没有 POI 响应。",
  imageSectionTitle: "图片能力测试",
  imageDescription: "单独验证搜索服务是直接返回图片，还是需要页面抓取后才能提取图片 URL。",
  imageToolLabel: "指定工具",
  imageToolPlaceholder: "留空则自动选择",
  probeImages: "测试图片",
  probingImages: "图片测试中...",
  clearImages: "清空图片测试",
  imageResultsTitle: "图片测试结果",
  imageResultsEmpty: "还没有图片探测。",
  imageUrlsEmpty: "没有提取到图片 URL。",
  imageRequestTitle: "图片测试请求",
  imageRequestEmpty: "还没有图片测试请求。",
  imageResponseTitle: "图片测试响应",
  imageResponseEmpty: "还没有图片测试响应。",
  imageStrategyLabel: "探测策略",
  xhsSectionTitle: "\u5c0f\u7ea2\u4e66\u56fe\u7247\u8c03\u8bd5",
  xhsDescription: "\u76f4\u63a5\u8c03\u7528\u5185\u90e8\u5c0f\u7ea2\u4e66 crawler\uff0c\u5bf9\u7167\u539f\u59cb\u56fe\u7247\u5b57\u6bb5\u4e0e\u89e3\u6790\u540e\u7684 image_urls\u3002",
  xhsBoundHint: "\u9700\u8981\u5148\u5728 Settings \u9875\u7ed1\u5b9a\u5c0f\u7ea2\u4e66\u8d26\u53f7\u3002",
  xhsDestinationLabel: "\u76ee\u7684\u5730",
  xhsQueriesLabel: "\u67e5\u8be2\u8bcd\uff08\u6bcf\u884c\u4e00\u6761\uff09",
  xhsLimitLabel: "\u6bcf\u4e2a query \u7684\u8fd4\u56de\u4e0a\u9650",
  probeXhs: "\u6d4b\u8bd5 XHS \u56fe\u7247",
  probingXhs: "XHS \u6d4b\u8bd5\u4e2d...",
  clearXhs: "\u6e05\u7a7a XHS \u6d4b\u8bd5",
  xhsResultsTitle: "XHS \u56fe\u7247\u8c03\u8bd5\u7ed3\u679c",
  xhsResultsEmpty: "\u8fd8\u6ca1\u6709 XHS \u8c03\u8bd5\u7ed3\u679c\u3002",
  xhsRecordsCount: "\u539f\u59cb records\uff1a{count}",
  xhsPostsCount: "\u89e3\u6790 posts\uff1a{count}",
  xhsRawCandidatesLabel: "\u539f\u59cb\u56fe\u7247 candidates",
  xhsMergedCandidatesLabel: "\u5408\u5e76\u8be6\u60c5\u540e candidates",
  xhsParsedCandidatesLabel: "\u89e3\u6790\u540e image_urls",
  xhsFieldDetailsLabel: "\u56fe\u7247\u5b57\u6bb5\u8be6\u60c5",
  xhsRawFieldsLabel: "\u539f\u59cb\u56fe\u7247\u5b57\u6bb5",
  xhsMergedFieldsLabel: "\u5408\u5e76\u540e\u56fe\u7247\u5b57\u6bb5",
  xhsRequestTitle: "XHS \u8bf7\u6c42",
  xhsRequestEmpty: "\u8fd8\u6ca1\u6709 XHS \u8bf7\u6c42\u3002",
  xhsResponseTitle: "XHS \u54cd\u5e94",
  xhsResponseEmpty: "\u8fd8\u6ca1\u6709 XHS \u54cd\u5e94\u3002",
  tavilySectionTitle: "Tavily 图片搜索",
  tavilyDescription: "直接调用 Tavily /search 并开启 include_images，检查它返回的图片结构。",
  tavilyBaseUrlLabel: "Tavily 地址",
  tavilyApiKeyLabel: "Tavily API Key",
  tavilySavedKeyHint: "留空会复用已保存的 Tavily 搜索密钥。",
  tavilyDepthLabel: "搜索深度",
  tavilyMaxResultsLabel: "返回上限",
  tavilyIncludeDescriptionsLabel: "返回图片描述",
  probeTavily: "测试 Tavily",
  probingTavily: "Tavily 测试中...",
  clearTavily: "清空 Tavily 测试",
  tavilyResultsTitle: "Tavily 图片结果",
  tavilyResultsEmpty: "还没有 Tavily 探测。",
  tavilyCandidatesTitle: "可用图片候选",
  tavilyCandidatesCount: "候选图片：{count}",
  tavilyTopImagesTitle: "顶层 images",
  tavilyResultImagesTitle: "results[].images",
  tavilyImagesEmpty: "Tavily 没有返回图片 URL。",
  tavilyTopImagesCount: "顶层 images：{count}",
  tavilyResultImagesCount: "results[].images：{count}",
  openImageLabel: "打开图片",
  openSourceLabel: "打开来源",
  tavilyRequestTitle: "Tavily 请求",
  tavilyRequestEmpty: "还没有 Tavily 请求。",
  tavilyResponseTitle: "Tavily 响应",
  tavilyResponseEmpty: "还没有 Tavily 响应。",
  chatTitle: "对话",
  chatEmpty: "还没有消息。",
  userRole: "用户",
  assistantRole: "助手",
  errorRole: "错误",
  composerPlaceholder: "例如：请打个招呼，并确认你可以正常回复。",
  rawRequestTitle: "LLM 原始请求",
  rawRequestEmpty: "还没有请求。",
  rawResponseTitle: "LLM 原始响应",
  rawResponseEmpty: "还没有响应。",
  searchResultsTitle: "搜索结果",
  searchResultsEmpty: "还没有执行搜索探测。",
  searchRequestTitle: "搜索原始请求",
  searchRequestEmpty: "还没有搜索请求。",
  searchResponseTitle: "搜索原始响应",
  searchResponseEmpty: "还没有搜索响应。",
  searchHitsEmpty: "探测成功，但没有提取出可展示的结果。",
  availableToolsLabel: "可用工具",
  operationLabel: "本次调用",
  endpointLabel: "当前地址",
  defaultSystemPrompt: "你是一个有帮助的旅行规划助手，请简短清晰地回复。",
  defaultInput: "你好，请打个招呼，并确认你可以正常回复。",
  defaultSearchQuery: "京都站附近安静咖啡店",
  defaultXhsDestination: "\u6c55\u5934",
  defaultXhsQueries: "\u6c55\u5934 \u9152\u5e97\n\u6c55\u5934 \u4f4f\u54ea\u91cc",
  unknownRequestFailure: "未知请求错误",
  requestFailedWithStatus: "请求失败，状态码 {status}",
  responsesNoText: "Responses API 没有返回文本内容",
  responsesStreamNoText: "Responses API 流式响应中没有助手文本",
  chatNoText: "Chat Completions API 没有返回消息内容",
  chatStreamNoText: "Chat Completions API 流式响应中没有助手文本",
  invalidSearchEnvelope: "搜索探测没有返回有效 envelope",
  noStoredSearchKey: "留空会继续使用已保存的搜索密钥。"
}

const copy = computed(() => (locale.value === "zh-CN" ? zhCopy : enCopy))

const form = reactive<DemoConfig>({
  provider_protocol: "openai",
  base_url: "",
  api_key: "",
  model: "",
  wire_api: "responses",
  system_prompt: "",
  stream: true
})

const searchForm = reactive<SearchProbeConfig>({
  provider: "groksearch",
  transport: "mcp",
  base_url: "",
  api_key: "",
  timeout_seconds: 30,
  query: ""
})
const poiProbeForm = reactive({
  destination: "大理",
  origin: "",
  start_date: "",
  end_date: "",
  budget: 3000,
  travelers: 2,
  interests_text: "",
  accommodation_preference: "",
  pace: "balanced",
  transport_mode: "public_transport",
  user_input: "我要去大理旅行，请结合全网的旅游攻略以及网络信息给我一些值得去的 POI",
  use_search: false
})
const imageProbeForm = reactive({
  preferred_tool: "",
  query: ""
})
const xhsImageForm = reactive({
  destination: "",
  queries_text: "",
  limit_per_query: 5
})
const tavilyForm = reactive({
  base_url: "https://api.tavily.com/search",
  api_key: "",
  query: "",
  search_depth: "basic",
  max_results: 8,
  include_image_descriptions: true
})

const input = ref("")
const sending = ref(false)
const errorText = ref("")
const rawRequest = ref("")
const rawResponse = ref("")
const messages = ref<ChatMessage[]>([])

const searchPending = ref(false)
const searchErrorText = ref("")
const searchRawRequest = ref("")
const searchRawResponse = ref("")
const searchResult = ref<SearchProbeResult | null>(null)
const poiProbePending = ref(false)
const poiProbeErrorText = ref("")
const poiProbeRawRequest = ref("")
const poiProbeRawResponse = ref("")
const poiProbeResult = ref<PoiSpecialistProbeResult | null>(null)
const imageProbePending = ref(false)
const imageProbeErrorText = ref("")
const imageProbeRawRequest = ref("")
const imageProbeRawResponse = ref("")
const imageProbeResult = ref<SearchImageProbeResult | null>(null)
const xhsImagePending = ref(false)
const xhsImageErrorText = ref("")
const xhsImageRawRequest = ref("")
const xhsImageRawResponse = ref("")
const xhsImageProbeResult = ref<XhsImageProbeResult | null>(null)
const tavilyPending = ref(false)
const tavilyErrorText = ref("")
const tavilyRawRequest = ref("")
const tavilyRawResponse = ref("")
const tavilyResult = ref<TavilyImagesProbeResult | null>(null)
const llmFormHydrated = ref(false)
const searchFormHydrated = ref(false)

const llmProtocolDefaultBaseUrls: Record<LlmProviderProtocol, string> = {
  openai: "https://api.openai.com/v1",
  newapi: "http://localhost:3000/v1",
  gemini: "https://generativelanguage.googleapis.com/v1beta",
  claude: "https://api.anthropic.com/v1",
  neiapi: "https://api.neiapi.com/v1"
}

function defaultWireApiForProtocol(protocol: LlmProviderProtocol): LlmWireApi {
  return protocol === "newapi" || protocol === "neiapi" ? "chat_completions" : "responses"
}

watch(
  () => locale.value,
  () => {
    if (!form.system_prompt.trim()) {
      form.system_prompt = copy.value.defaultSystemPrompt
    }
    if (!input.value.trim()) {
      input.value = copy.value.defaultInput
    }
    if (!searchForm.query.trim()) {
      searchForm.query = copy.value.defaultSearchQuery
    }
    if (!imageProbeForm.query.trim()) {
      imageProbeForm.query = copy.value.defaultSearchQuery
    }
    if (!xhsImageForm.destination.trim()) {
      xhsImageForm.destination = copy.value.defaultXhsDestination
    }
    if (!xhsImageForm.queries_text.trim()) {
      xhsImageForm.queries_text = copy.value.defaultXhsQueries
    }
    if (!tavilyForm.query.trim()) {
      tavilyForm.query = copy.value.defaultSearchQuery
    }
  },
  { immediate: true }
)

watch(
  () => settingsStore.settings,
  (settings) => {
    if (settings && !llmFormHydrated.value) {
      form.provider_protocol = settings.agent.provider_protocol ?? form.provider_protocol
      form.base_url = settings.agent.base_url ?? form.base_url
      form.model = settings.agent.model ?? form.model
      form.wire_api = settings.agent.wire_api ?? form.wire_api
      llmFormHydrated.value = true
    }
    form.api_key = ""

    if (settings && !searchFormHydrated.value) {
      searchForm.provider = settings.search.provider ?? searchForm.provider
      searchForm.transport =
        settings.search.provider === "groksearch"
          ? "mcp"
          : settings.search.provider === "tavily"
            ? "api"
            : (settings.search.transport ?? searchForm.transport)
      searchForm.base_url = settings.search.base_url ?? searchForm.base_url
      searchForm.timeout_seconds = Number(settings.search.timeout_seconds ?? searchForm.timeout_seconds)
      if (settings.search.provider === "tavily" && settings.search.base_url) {
        tavilyForm.base_url = settings.search.base_url
      }
      searchFormHydrated.value = true
    }
    searchForm.api_key = ""
  },
  { immediate: true }
)

watch(
  () => form.provider_protocol,
  (protocol, previousProtocol) => {
    const previousDefaultBaseUrl = previousProtocol ? llmProtocolDefaultBaseUrls[previousProtocol] : ""
    if (!form.base_url.trim() || form.base_url.trim() === previousDefaultBaseUrl) {
      form.base_url = llmProtocolDefaultBaseUrls[protocol]
    }
    const previousDefaultWireApi = previousProtocol ? defaultWireApiForProtocol(previousProtocol) : null
    if (protocol === "openai" || !form.wire_api || form.wire_api === previousDefaultWireApi) {
      form.wire_api = defaultWireApiForProtocol(protocol)
    }
  }
)

watch(
  () => searchForm.provider,
  (provider) => {
    if (provider === "groksearch") {
      searchForm.transport = "mcp"
    } else if (provider === "tavily") {
      searchForm.transport = "api"
    }
  }
)

const hasStoredSearchConfig = computed(() => Boolean(settingsStore.settings?.search.configured))
const hasStoredTavilyConfig = computed(() => Boolean(settingsStore.settings?.search.provider === "tavily" && settingsStore.settings.search.configured))

const canSend = computed(() => {
  return Boolean(!sending.value && form.base_url.trim() && form.model.trim() && input.value.trim())
})

const canProbeSearch = computed(() => {
  return Boolean(
    !searchPending.value &&
      searchForm.query.trim() &&
      (searchForm.base_url.trim() || hasStoredSearchConfig.value)
  )
})

const canProbePoi = computed(() => {
  return Boolean(
    !poiProbePending.value &&
      form.base_url.trim() &&
      form.model.trim() &&
      poiProbeForm.destination.trim() &&
      poiProbeForm.user_input.trim()
  )
})

const canProbeImages = computed(() => {
  return Boolean(
    !imageProbePending.value &&
      imageProbeForm.query.trim() &&
      (searchForm.base_url.trim() || hasStoredSearchConfig.value)
  )
})

const canProbeXhsImages = computed(() => {
  return Boolean(!xhsImagePending.value && xhsImageForm.destination.trim() && xhsImageForm.queries_text.trim())
})

const canProbeTavily = computed(() => {
  return Boolean(!tavilyPending.value && tavilyForm.base_url.trim() && (tavilyForm.api_key.trim() || hasStoredTavilyConfig.value) && tavilyForm.query.trim())
})
const openAiWireApiLocked = computed(() => form.provider_protocol === "openai")

const tavilyImageCandidates = computed<TavilyImageCandidateItem[]>(() => {
  const result = tavilyResult.value
  if (!result) {
    return []
  }
  if (Array.isArray(result.image_candidates) && result.image_candidates.length) {
    return result.image_candidates
  }

  const seen = new Set<string>()
  const candidates: TavilyImageCandidateItem[] = []
  const record = (candidate: TavilyImageCandidateItem) => {
    const url = String(candidate.url || "").trim()
    if (!url || seen.has(url.toLowerCase())) {
      return
    }
    seen.add(url.toLowerCase())
    candidates.push({ ...candidate, url })
  }

  result.top_level_images.forEach((image) => {
    record({
      source: "top_level",
      source_domain: image.source_domain ?? null,
      url: String(image.url || ""),
      title: image.title ?? null,
      description: image.description ?? null,
      result_title: null,
      result_url: null
    })
  })

  result.result_images.forEach((image) => {
    record({
      source: "result",
      source_domain: image.source_domain ?? null,
      url: image.url,
      title: null,
      description: image.description ?? null,
      result_title: image.result_title,
      result_url: image.result_url
    })
  })

  return candidates
})

function formatLimitedCount(displayed: number, total?: number, truncated?: boolean): string {
  const normalizedTotal = Number(total ?? displayed)
  if (truncated || normalizedTotal > displayed) {
    return `${displayed}/${normalizedTotal}`
  }
  return String(displayed)
}

const tavilyCandidateCountText = computed(() =>
  formatLimitedCount(tavilyImageCandidates.value.length, tavilyResult.value?.image_candidates_total, tavilyResult.value?.image_candidates_truncated)
)

const tavilyTopImagesCountText = computed(() =>
  formatLimitedCount(tavilyResult.value?.top_level_images.length ?? 0, tavilyResult.value?.top_level_images_total, tavilyResult.value?.top_level_images_truncated)
)

const tavilyResultImagesCountText = computed(() =>
  formatLimitedCount(tavilyResult.value?.result_images.length ?? 0, tavilyResult.value?.result_images_total, tavilyResult.value?.result_images_truncated)
)

const poiFeaturedPois = computed<Record<string, any>[]>(() => {
  const featured = poiProbeResult.value?.parsed_json?.featured_pois
  return Array.isArray(featured) ? featured.filter((item): item is Record<string, any> => item && typeof item === "object" && !Array.isArray(item)) : []
})

function clearChat() {
  messages.value = []
  errorText.value = ""
  rawRequest.value = ""
  rawResponse.value = ""
}

function clearSearch() {
  searchErrorText.value = ""
  searchRawRequest.value = ""
  searchRawResponse.value = ""
  searchResult.value = null
}

function clearPoiProbe() {
  poiProbeErrorText.value = ""
  poiProbeRawRequest.value = ""
  poiProbeRawResponse.value = ""
  poiProbeResult.value = null
}

function clearImageProbe() {
  imageProbeErrorText.value = ""
  imageProbeRawRequest.value = ""
  imageProbeRawResponse.value = ""
  imageProbeResult.value = null
}

function clearXhsProbe() {
  xhsImageErrorText.value = ""
  xhsImageRawRequest.value = ""
  xhsImageRawResponse.value = ""
  xhsImageProbeResult.value = null
}

function clearTavilyProbe() {
  tavilyErrorText.value = ""
  tavilyRawRequest.value = ""
  tavilyRawResponse.value = ""
  tavilyResult.value = null
}

function formatMessageRole(role: ChatMessage["role"]) {
  if (role === "user") return copy.value.userRole
  if (role === "assistant") return copy.value.assistantRole
  return copy.value.errorRole
}

function setMessageContent(index: number, content: string) {
  const next = messages.value[index]
  if (!next) {
    return
  }
  messages.value[index] = { ...next, content }
}

function buildUpstreamPayload(userText: string) {
  if (form.wire_api === "responses") {
    return {
      model: form.model.trim(),
      stream: form.stream,
      input: [
        {
          role: "system",
          content: [{ type: "input_text", text: form.system_prompt.trim() }]
        },
        {
          role: "user",
          content: [{ type: "input_text", text: userText }]
        }
      ]
    }
  }

  return {
    model: form.model.trim(),
    stream: form.stream,
    messages: [
      { role: "system", content: form.system_prompt.trim() },
      { role: "user", content: userText }
    ]
  }
}

async function send() {
  if (!canSend.value) {
    return
  }

  const userText = input.value.trim()
  let assistantIndex = -1

  sending.value = true
  errorText.value = ""
  rawResponse.value = ""
  messages.value.push({ role: "user", content: userText })

  try {
    const upstreamPayload = buildUpstreamPayload(userText)
    const requestPayload = {
      provider_protocol: form.provider_protocol,
      base_url: form.base_url.trim(),
      api_key: form.api_key.trim() || undefined,
      wire_api: form.wire_api,
      payload: upstreamPayload
    }
    rawRequest.value = JSON.stringify({ url: "/api/v1/llm/proxy", payload: requestPayload }, null, 2)

    const response = await apiFetch("/api/v1/llm/proxy", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(requestPayload)
    })

    if (!response.ok) {
      const rawBody = await response.text()
      rawResponse.value = rawBody
      handleUnauthorizedStatus(response.status)
      throw new Error(extractErrorMessage(rawBody, response.status))
    }

    assistantIndex = messages.value.push({ role: "assistant", content: "" }) - 1
    const assistantText = await consumeAssistantResponse(response, assistantIndex)
    setMessageContent(assistantIndex, assistantText)
    input.value = ""
    form.api_key = ""
  } catch (error) {
    if (assistantIndex >= 0 && !messages.value[assistantIndex]?.content.trim()) {
      messages.value.splice(assistantIndex, 1)
    }
    const message = error instanceof Error ? error.message : copy.value.unknownRequestFailure
    errorText.value = message
    messages.value.push({ role: "error", content: message })
  } finally {
    sending.value = false
  }
}

async function probeSearch() {
  if (!canProbeSearch.value) {
    return
  }

  searchPending.value = true
  searchErrorText.value = ""
  searchResult.value = null
  searchRawResponse.value = ""

  try {
    const payload = {
      provider: searchForm.provider,
      transport: searchForm.provider === "groksearch" ? "mcp" : searchForm.provider === "tavily" ? "api" : searchForm.transport,
      base_url: searchForm.base_url.trim() || undefined,
      api_key: searchForm.api_key.trim() || undefined,
      timeout_seconds: Number.isFinite(searchForm.timeout_seconds) && searchForm.timeout_seconds > 0 ? searchForm.timeout_seconds : 30,
      query: searchForm.query.trim()
    }

    searchRawRequest.value = JSON.stringify({ url: "/api/v1/llm/search-proxy", payload }, null, 2)

    const response = await apiFetch("/api/v1/llm/search-proxy", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    })

    const rawBody = await response.text()
    searchRawResponse.value = rawBody

    if (!response.ok) {
      handleUnauthorizedStatus(response.status)
      throw new Error(extractErrorMessage(rawBody, response.status))
    }

    const parsed = JSON.parse(rawBody) as SearchProbeEnvelope
    if (!parsed.data) {
      throw new Error(copy.value.invalidSearchEnvelope)
    }

    searchResult.value = parsed.data
    searchForm.api_key = ""
  } catch (error) {
    searchErrorText.value = error instanceof Error ? error.message : copy.value.unknownRequestFailure
  } finally {
    searchPending.value = false
  }
}

async function probePoiSpecialist() {
  if (!canProbePoi.value) {
    return
  }

  poiProbePending.value = true
  poiProbeErrorText.value = ""
  poiProbeResult.value = null
  poiProbeRawResponse.value = ""

  try {
    const payload = {
      provider_protocol: form.provider_protocol,
      base_url: form.base_url.trim() || undefined,
      api_key: form.api_key.trim() || undefined,
      wire_api: form.wire_api,
      payload: {
        model: form.model.trim(),
        temperature: 0.2,
        max_tokens: 6000
      },
      search_provider: searchForm.provider,
      search_transport: searchForm.provider === "groksearch" ? "mcp" : searchForm.provider === "tavily" ? "api" : searchForm.transport,
      search_base_url: searchForm.base_url.trim() || undefined,
      search_api_key: searchForm.api_key.trim() || undefined,
      search_timeout_seconds: Number.isFinite(searchForm.timeout_seconds) && searchForm.timeout_seconds > 0 ? searchForm.timeout_seconds : 30,
      destination: poiProbeForm.destination.trim(),
      origin: poiProbeForm.origin.trim() || undefined,
      start_date: poiProbeForm.start_date.trim() || undefined,
      end_date: poiProbeForm.end_date.trim() || undefined,
      budget: Number.isFinite(poiProbeForm.budget) && poiProbeForm.budget > 0 ? poiProbeForm.budget : undefined,
      travelers: Number.isFinite(poiProbeForm.travelers) && poiProbeForm.travelers > 0 ? poiProbeForm.travelers : 2,
      interests: splitProbeLines(poiProbeForm.interests_text),
      accommodation_preference: poiProbeForm.accommodation_preference.trim() || undefined,
      pace: poiProbeForm.pace.trim() || "balanced",
      transport_mode: poiProbeForm.transport_mode.trim() || undefined,
      user_input: poiProbeForm.user_input.trim(),
      use_search: poiProbeForm.use_search
    }

    poiProbeRawRequest.value = JSON.stringify({ url: "/api/v1/llm/poi-specialist-probe", payload }, null, 2)

    const response = await apiFetch("/api/v1/llm/poi-specialist-probe", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    })

    const rawBody = await response.text()
    poiProbeRawResponse.value = rawBody

    if (!response.ok) {
      handleUnauthorizedStatus(response.status)
      throw new Error(extractErrorMessage(rawBody, response.status))
    }

    const parsed = JSON.parse(rawBody) as PoiSpecialistProbeEnvelope
    if (!parsed.data) {
      throw new Error(copy.value.invalidSearchEnvelope)
    }

    poiProbeResult.value = parsed.data
    form.api_key = ""
    searchForm.api_key = ""
  } catch (error) {
    poiProbeErrorText.value = error instanceof Error ? error.message : copy.value.unknownRequestFailure
  } finally {
    poiProbePending.value = false
  }
}

async function probeImages() {
  if (!canProbeImages.value) {
    return
  }

  imageProbePending.value = true
  imageProbeErrorText.value = ""
  imageProbeResult.value = null
  imageProbeRawResponse.value = ""

  try {
    const payload = {
      provider: searchForm.provider,
      transport: searchForm.provider === "groksearch" ? "mcp" : searchForm.provider === "tavily" ? "api" : searchForm.transport,
      base_url: searchForm.base_url.trim() || undefined,
      api_key: searchForm.api_key.trim() || undefined,
      timeout_seconds: Number.isFinite(searchForm.timeout_seconds) && searchForm.timeout_seconds > 0 ? searchForm.timeout_seconds : 30,
      query: imageProbeForm.query.trim(),
      preferred_tool: imageProbeForm.preferred_tool.trim() || undefined
    }

    imageProbeRawRequest.value = JSON.stringify({ url: "/api/v1/llm/search-images-proxy", payload }, null, 2)

    const response = await apiFetch("/api/v1/llm/search-images-proxy", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    })

    const rawBody = await response.text()
    imageProbeRawResponse.value = rawBody

    if (!response.ok) {
      handleUnauthorizedStatus(response.status)
      throw new Error(extractErrorMessage(rawBody, response.status))
    }

    const parsed = JSON.parse(rawBody) as SearchImageProbeEnvelope
    if (!parsed.data) {
      throw new Error(copy.value.invalidSearchEnvelope)
    }

    imageProbeResult.value = parsed.data
    searchForm.api_key = ""
  } catch (error) {
    imageProbeErrorText.value = error instanceof Error ? error.message : copy.value.unknownRequestFailure
  } finally {
    imageProbePending.value = false
  }
}

function splitProbeLines(value: string): string[] {
  const results: string[] = []
  const seen = new Set<string>()
  for (const line of value.split(/\r?\n/)) {
    const candidate = line.trim()
    const key = candidate.toLowerCase()
    if (!candidate || seen.has(key)) {
      continue
    }
    seen.add(key)
    results.push(candidate)
  }
  return results.slice(0, 4)
}

async function probeXhsImages() {
  if (!canProbeXhsImages.value) {
    return
  }

  xhsImagePending.value = true
  xhsImageErrorText.value = ""
  xhsImageProbeResult.value = null
  xhsImageRawResponse.value = ""

  try {
    const payload = {
      destination: xhsImageForm.destination.trim(),
      queries: splitProbeLines(xhsImageForm.queries_text),
      limit_per_query: Number.isFinite(xhsImageForm.limit_per_query) && xhsImageForm.limit_per_query > 0 ? xhsImageForm.limit_per_query : 5
    }

    xhsImageRawRequest.value = JSON.stringify({ url: "/api/v1/llm/xhs-images-proxy", payload }, null, 2)

    const response = await apiFetch("/api/v1/llm/xhs-images-proxy", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    })

    const rawBody = await response.text()
    xhsImageRawResponse.value = rawBody

    if (!response.ok) {
      handleUnauthorizedStatus(response.status)
      throw new Error(extractErrorMessage(rawBody, response.status))
    }

    const parsed = JSON.parse(rawBody) as XhsImageProbeEnvelope
    if (!parsed.data) {
      throw new Error(copy.value.invalidSearchEnvelope)
    }

    xhsImageProbeResult.value = parsed.data
  } catch (error) {
    xhsImageErrorText.value = error instanceof Error ? error.message : copy.value.unknownRequestFailure
  } finally {
    xhsImagePending.value = false
  }
}

async function probeTavily() {
  if (!canProbeTavily.value) {
    return
  }

  tavilyPending.value = true
  tavilyErrorText.value = ""
  tavilyResult.value = null
  tavilyRawResponse.value = ""

  try {
    const payload = {
      base_url: tavilyForm.base_url.trim(),
      api_key: tavilyForm.api_key.trim() || undefined,
      query: tavilyForm.query.trim(),
      search_depth: tavilyForm.search_depth,
      max_results: tavilyForm.max_results,
      include_image_descriptions: tavilyForm.include_image_descriptions
    }

    tavilyRawRequest.value = JSON.stringify({ url: "/api/v1/llm/tavily-images-proxy", payload }, null, 2)
    const response = await apiFetch("/api/v1/llm/tavily-images-proxy", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    })

    const rawBody = await response.text()
    tavilyRawResponse.value = rawBody

    if (!response.ok) {
      handleUnauthorizedStatus(response.status)
      throw new Error(extractErrorMessage(rawBody, response.status))
    }

    const parsed = JSON.parse(rawBody) as TavilyImagesProbeEnvelope
    if (!parsed.data) {
      throw new Error(copy.value.invalidSearchEnvelope)
    }
    tavilyResult.value = parsed.data
    tavilyForm.api_key = ""
  } catch (error) {
    tavilyErrorText.value = error instanceof Error ? error.message : copy.value.unknownRequestFailure
  } finally {
    tavilyPending.value = false
  }
}

async function consumeAssistantResponse(response: Response, assistantIndex: number): Promise<string> {
  const contentType = response.headers.get("content-type") ?? ""
  const useStreaming = Boolean(response.body && (form.stream || contentType.includes("text/event-stream")))

  if (!useStreaming) {
    const rawBody = await response.text()
    rawResponse.value = rawBody
    return extractAssistantText(rawBody, contentType)
  }

  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  const responsesState = { delta: "", completed: "" }
  const chatState = { delta: "", completed: "" }
  let rawBody = ""
  let buffer = ""

  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      break
    }

    const chunk = decoder.decode(value, { stream: true })
    rawBody += chunk
    rawResponse.value = rawBody
    buffer += chunk
    buffer = consumeSseBuffer(buffer, (line) => {
      if (!line.startsWith("data: ")) {
        return
      }
      const data = line.slice(6)
      const nextText = form.wire_api === "responses" ? consumeResponsesEvent(data, responsesState) : consumeChatEvent(data, chatState)
      if (nextText !== null) {
        setMessageContent(assistantIndex, nextText)
      }
    })
  }

  const flush = decoder.decode()
  if (flush) {
    rawBody += flush
    rawResponse.value = rawBody
    buffer += flush
  }

  if (buffer.trim()) {
    consumeSseBuffer(`${buffer}\n`, (line) => {
      if (!line.startsWith("data: ")) {
        return
      }
      const data = line.slice(6)
      const nextText = form.wire_api === "responses" ? consumeResponsesEvent(data, responsesState) : consumeChatEvent(data, chatState)
      if (nextText !== null) {
        setMessageContent(assistantIndex, nextText)
      }
    })
  }

  const streamedText = form.wire_api === "responses" ? responsesState.completed || responsesState.delta : chatState.completed || chatState.delta
  if (streamedText.trim()) {
    return streamedText
  }

  return extractAssistantText(rawBody, contentType)
}

function consumeSseBuffer(buffer: string, onLine: (line: string) => void): string {
  let nextBuffer = buffer
  while (true) {
    const newlineIndex = nextBuffer.indexOf("\n")
    if (newlineIndex === -1) {
      return nextBuffer
    }
    let line = nextBuffer.slice(0, newlineIndex)
    nextBuffer = nextBuffer.slice(newlineIndex + 1)
    if (line.endsWith("\r")) {
      line = line.slice(0, -1)
    }
    onLine(line)
  }
}

function consumeResponsesEvent(data: string, state: { delta: string; completed: string }): string | null {
  if (!data || data === "[DONE]") {
    return null
  }

  let parsed: any
  try {
    parsed = JSON.parse(data)
  } catch {
    return null
  }

  if (parsed.type === "response.output_text.delta" && typeof parsed.delta === "string") {
    state.delta += parsed.delta
    return state.delta
  }

  if (parsed.type === "response.output_text.done" && typeof parsed.text === "string") {
    state.completed = parsed.text
    return state.completed
  }

  if (parsed.type === "response.completed") {
    const completed = extractResponsesOutputText(parsed.response ?? parsed)
    if (completed) {
      state.completed = completed
      return state.completed
    }
  }

  return null
}

function consumeChatEvent(data: string, state: { delta: string; completed: string }): string | null {
  if (!data || data === "[DONE]") {
    return null
  }

  let parsed: any
  try {
    parsed = JSON.parse(data)
  } catch {
    return null
  }

  const delta = extractChatDeltaText(parsed?.choices?.[0]?.delta?.content)
  if (delta) {
    state.delta += delta
    return state.delta
  }

  const completed = extractChatMessageText(parsed?.choices?.[0]?.message?.content)
  if (completed) {
    state.completed = completed
    return state.completed
  }

  return null
}

function extractAssistantText(rawBody: string, contentType: string): string {
  const isEventStream = looksLikeEventStream(contentType, rawBody)
  if (form.wire_api === "responses") {
    return isEventStream ? extractResponsesTextFromSse(rawBody) : extractResponsesTextFromJson(rawBody)
  }
  return isEventStream ? extractChatTextFromSse(rawBody) : extractChatTextFromJson(rawBody)
}

function looksLikeEventStream(contentType: string, rawBody: string): boolean {
  return contentType.includes("text/event-stream") || rawBody.trimStart().startsWith("data:")
}

function extractErrorMessage(rawBody: string, status: number): string {
  try {
    const parsed = JSON.parse(rawBody) as EnvelopeError
    if (typeof parsed.error === "string") return parsed.error
    if (typeof parsed.error?.message === "string") return parsed.error.message
    if (typeof parsed.message === "string") return parsed.message
  } catch {
    // Ignore parse errors.
  }
  return rawBody.trim() || copy.value.requestFailedWithStatus.replace("{status}", String(status))
}

function extractResponsesTextFromJson(rawBody: string): string {
  const body = JSON.parse(rawBody) as any
  if (typeof body.output_text === "string" && body.output_text.trim()) {
    return body.output_text
  }
  const text = extractResponsesOutputText(body)
  if (text) {
    return text
  }
  throw new Error(copy.value.responsesNoText)
}

function extractResponsesTextFromSse(rawBody: string): string {
  const state = { delta: "", completed: "" }
  for (const line of rawBody.split(/\r?\n/)) {
    if (!line.startsWith("data: ")) {
      continue
    }
    const nextText = consumeResponsesEvent(line.slice(6), state)
    if (nextText) {
      state.completed = nextText
    }
  }
  const finalText = state.completed || state.delta
  if (!finalText.trim()) {
    throw new Error(copy.value.responsesStreamNoText)
  }
  return finalText
}

function extractResponsesOutputText(body: any): string {
  const blocks = Array.isArray(body?.output)
    ? body.output.flatMap((item: any) => extractTextBlocks(item?.content))
    : []
  return blocks.filter(Boolean).join("\n").trim()
}

function extractChatTextFromJson(rawBody: string): string {
  const body = JSON.parse(rawBody) as any
  const content = extractChatMessageText(body?.choices?.[0]?.message?.content)
  if (content) {
    return content
  }
  throw new Error(copy.value.chatNoText)
}

function extractChatTextFromSse(rawBody: string): string {
  const state = { delta: "", completed: "" }
  for (const line of rawBody.split(/\r?\n/)) {
    if (!line.startsWith("data: ")) {
      continue
    }
    const nextText = consumeChatEvent(line.slice(6), state)
    if (nextText) {
      state.completed = nextText
    }
  }
  const finalText = state.completed || state.delta
  if (!finalText.trim()) {
    throw new Error(copy.value.chatStreamNoText)
  }
  return finalText
}

function extractChatMessageText(content: unknown): string {
  if (typeof content === "string" && content.trim()) {
    return content
  }
  const blocks = extractTextBlocks(content)
  return blocks.join("\n").trim()
}

function extractChatDeltaText(content: unknown): string {
  if (typeof content === "string") {
    return content
  }
  return extractTextBlocks(content).join("")
}

function extractTextBlocks(content: unknown): string[] {
  if (typeof content === "string" && content.trim()) {
    return [content]
  }
  if (!Array.isArray(content)) {
    return []
  }
  return content
    .map((item: any) => item?.text)
    .filter((value: unknown): value is string => typeof value === "string" && value.trim().length > 0)
}

function formatHostLabel(value?: string | null): string {
  const raw = String(value || "").trim()
  if (!raw) {
    return ""
  }
  try {
    return new URL(raw).hostname
  } catch {
    return raw
  }
}

function summarizeText(value?: string | null, maxLength = 96): string {
  const text = String(value || "").trim()
  if (!text) {
    return ""
  }
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text
}

function formatPoiMeta(poi: Record<string, any>): string {
  return [poi.kind, poi.category, poi.area, poi.confidence].map((value) => String(value || "").trim()).filter(Boolean).join(" / ")
}

function formatPoiEvidence(poi: Record<string, any>): string {
  return [poi.price_hint, poi.review_score, poi.review_count, poi.queue_hint].map((value) => String(value || "").trim()).filter(Boolean).join(" / ")
}

function formatStringList(value: unknown): string {
  if (Array.isArray(value)) {
    return value.map((item) => String(item || "").trim()).filter(Boolean).join(", ")
  }
  return String(value || "").trim()
}

function formatPrettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value ?? "")
  }
}
</script>

<template>
  <div class="llm-demo-page">
    <section class="llm-demo-shell">
      <aside class="llm-demo-sidebar">
        <div>
          <p class="llm-demo-kicker">{{ copy.kicker }}</p>
          <h1>{{ copy.title }}</h1>
          <p class="llm-demo-muted">{{ copy.description }}</p>
        </div>

        <div class="llm-demo-form">
          <p class="llm-demo-section-title">LLM</p>
          <label>
            Protocol
            <select v-model="form.provider_protocol">
              <option value="openai">OpenAI</option>
              <option value="newapi">New API</option>
              <option value="gemini">Gemini</option>
              <option value="claude">Claude</option>
              <option value="neiapi">NEI API</option>
            </select>
          </label>
          <label>
            {{ copy.baseUrlLabel }}
            <input v-model="form.base_url" placeholder="https://api.example.com/v1" />
          </label>
          <label>
            {{ copy.modelLabel }}
            <input v-model="form.model" placeholder="gpt-5.4" />
          </label>
          <label>
            {{ copy.apiFormatLabel }}
            <select v-model="form.wire_api" :disabled="openAiWireApiLocked">
              <option value="responses">Responses API</option>
              <option value="chat_completions">Chat Completions API</option>
            </select>
          </label>
          <label>
            {{ copy.apiKeyLabel }}
            <input v-model="form.api_key" type="password" autocomplete="off" placeholder="sk-..." />
          </label>
          <label class="llm-demo-toggle">
            <input v-model="form.stream" type="checkbox" />
            <span>{{ copy.streamLabel }}</span>
          </label>
          <label>
            {{ copy.systemPromptLabel }}
            <textarea v-model="form.system_prompt"></textarea>
          </label>
        </div>

        <div class="llm-demo-actions">
          <button class="primary" type="button" :disabled="!canSend" @click="send">
            {{ sending ? copy.sending : copy.send }}
          </button>
          <button type="button" @click="clearChat">{{ copy.clear }}</button>
        </div>

        <p v-if="errorText" class="llm-demo-error">{{ errorText }}</p>

        <div class="llm-demo-divider"></div>

        <div class="llm-demo-form">
          <p class="llm-demo-section-title">{{ copy.searchSectionTitle }}</p>
          <p class="llm-demo-muted">{{ copy.searchDescription }}</p>
          <label>
            {{ copy.searchProviderLabel }}
            <select v-model="searchForm.provider">
              <option value="groksearch">GrokSearch</option>
              <option value="tavily">Tavily</option>
            </select>
          </label>
          <label>
            {{ copy.searchTransportLabel }}
            <select v-model="searchForm.transport" :disabled="searchForm.provider === 'groksearch' || searchForm.provider === 'tavily'">
              <option value="mcp">MCP</option>
              <option value="api">API</option>
            </select>
          </label>
          <label>
            {{ copy.searchBaseUrlLabel }}
            <input v-model="searchForm.base_url" placeholder="http://127.0.0.1:8085/mcp" />
          </label>
          <label>
            {{ copy.searchApiKeyLabel }}
            <input v-model="searchForm.api_key" type="password" autocomplete="off" placeholder="grok-bridge-key" />
            <small class="llm-demo-help">{{ copy.noStoredSearchKey }}</small>
          </label>
          <label>
            {{ copy.searchTimeoutLabel }}
            <input v-model.number="searchForm.timeout_seconds" type="number" min="1" step="1" />
          </label>
          <label>
            {{ copy.searchQueryLabel }}
            <textarea v-model="searchForm.query" :placeholder="copy.searchPlaceholder"></textarea>
          </label>
        </div>

        <div class="llm-demo-actions">
          <button class="primary" type="button" :disabled="!canProbeSearch" @click="probeSearch">
            {{ searchPending ? copy.probingSearch : copy.probeSearch }}
          </button>
          <button type="button" @click="clearSearch">{{ copy.clearSearch }}</button>
        </div>

        <p v-if="searchErrorText" class="llm-demo-error">{{ searchErrorText }}</p>

        <div class="llm-demo-divider"></div>

        <div class="llm-demo-form">
          <p class="llm-demo-section-title">{{ copy.poiSectionTitle }}</p>
          <p class="llm-demo-muted">{{ copy.poiDescription }}</p>
          <label>
            {{ copy.poiDestinationLabel }}
            <input v-model="poiProbeForm.destination" placeholder="大理" />
          </label>
          <label>
            {{ copy.poiOriginLabel }}
            <input v-model="poiProbeForm.origin" placeholder="上海" />
          </label>
          <label>
            {{ copy.poiStartDateLabel }}
            <input v-model="poiProbeForm.start_date" type="date" />
          </label>
          <label>
            {{ copy.poiEndDateLabel }}
            <input v-model="poiProbeForm.end_date" type="date" />
          </label>
          <label>
            {{ copy.poiBudgetLabel }}
            <input v-model.number="poiProbeForm.budget" type="number" min="0" step="100" />
          </label>
          <label>
            {{ copy.poiTravelersLabel }}
            <input v-model.number="poiProbeForm.travelers" type="number" min="1" max="20" step="1" />
          </label>
          <label>
            {{ copy.poiPaceLabel }}
            <input v-model="poiProbeForm.pace" placeholder="balanced" />
          </label>
          <label>
            {{ copy.poiTransportLabel }}
            <input v-model="poiProbeForm.transport_mode" placeholder="public_transport" />
          </label>
          <label>
            {{ copy.poiAccommodationLabel }}
            <input v-model="poiProbeForm.accommodation_preference" placeholder="古城附近安静酒店" />
          </label>
          <label>
            {{ copy.poiInterestsLabel }}
            <textarea v-model="poiProbeForm.interests_text"></textarea>
          </label>
          <label>
            {{ copy.poiUserInputLabel }}
            <textarea v-model="poiProbeForm.user_input"></textarea>
          </label>
          <label class="llm-demo-toggle">
            <input v-model="poiProbeForm.use_search" type="checkbox" />
            <span>{{ copy.poiUseSearchLabel }}</span>
          </label>
        </div>

        <div class="llm-demo-actions">
          <button class="primary" type="button" :disabled="!canProbePoi" @click="probePoiSpecialist">
            {{ poiProbePending ? copy.probingPoi : copy.probePoi }}
          </button>
          <button type="button" @click="clearPoiProbe">{{ copy.clearPoi }}</button>
        </div>

        <p v-if="poiProbeErrorText" class="llm-demo-error">{{ poiProbeErrorText }}</p>

        <div class="llm-demo-divider"></div>

        <div class="llm-demo-form">
          <p class="llm-demo-section-title">{{ copy.imageSectionTitle }}</p>
          <p class="llm-demo-muted">{{ copy.imageDescription }}</p>
          <label>
            {{ copy.imageToolLabel }}
            <input v-model="imageProbeForm.preferred_tool" :placeholder="copy.imageToolPlaceholder" />
          </label>
          <label>
            {{ copy.searchQueryLabel }}
            <textarea v-model="imageProbeForm.query" :placeholder="copy.searchPlaceholder"></textarea>
          </label>
        </div>

        <div class="llm-demo-actions">
          <button class="primary" type="button" :disabled="!canProbeImages" @click="probeImages">
            {{ imageProbePending ? copy.probingImages : copy.probeImages }}
          </button>
          <button type="button" @click="clearImageProbe">{{ copy.clearImages }}</button>
        </div>

        <p v-if="imageProbeErrorText" class="llm-demo-error">{{ imageProbeErrorText }}</p>

        <div class="llm-demo-divider"></div>

        <div class="llm-demo-form">
          <p class="llm-demo-section-title">{{ copy.xhsSectionTitle }}</p>
          <p class="llm-demo-muted">{{ copy.xhsDescription }}</p>
          <p class="llm-demo-muted">{{ copy.xhsBoundHint }}</p>
          <label>
            {{ copy.xhsDestinationLabel }}
            <input v-model="xhsImageForm.destination" :placeholder="copy.defaultXhsDestination" />
          </label>
          <label>
            {{ copy.xhsQueriesLabel }}
            <textarea v-model="xhsImageForm.queries_text" :placeholder="copy.defaultXhsQueries"></textarea>
          </label>
          <label>
            {{ copy.xhsLimitLabel }}
            <input v-model.number="xhsImageForm.limit_per_query" type="number" min="1" max="10" step="1" />
          </label>
        </div>

        <div class="llm-demo-actions">
          <button class="primary" type="button" :disabled="!canProbeXhsImages" @click="probeXhsImages">
            {{ xhsImagePending ? copy.probingXhs : copy.probeXhs }}
          </button>
          <button type="button" @click="clearXhsProbe">{{ copy.clearXhs }}</button>
        </div>

        <p v-if="xhsImageErrorText" class="llm-demo-error">{{ xhsImageErrorText }}</p>

        <div class="llm-demo-divider"></div>

        <div class="llm-demo-form">
          <p class="llm-demo-section-title">{{ copy.tavilySectionTitle }}</p>
          <p class="llm-demo-muted">{{ copy.tavilyDescription }}</p>
          <label>
            {{ copy.tavilyBaseUrlLabel }}
            <input v-model="tavilyForm.base_url" placeholder="https://api.tavily.com/search" />
          </label>
          <label>
            {{ copy.tavilyApiKeyLabel }}
            <input v-model="tavilyForm.api_key" type="password" autocomplete="off" placeholder="tvly-..." />
            <small class="llm-demo-help">{{ copy.tavilySavedKeyHint }}</small>
          </label>
          <label>
            {{ copy.searchQueryLabel }}
            <textarea v-model="tavilyForm.query" :placeholder="copy.searchPlaceholder"></textarea>
          </label>
          <label>
            {{ copy.tavilyDepthLabel }}
            <select v-model="tavilyForm.search_depth">
              <option value="basic">基础</option>
              <option value="advanced">高级</option>
            </select>
          </label>
          <label>
            {{ copy.tavilyMaxResultsLabel }}
            <input v-model.number="tavilyForm.max_results" type="number" min="1" max="20" step="1" />
          </label>
          <label class="llm-demo-toggle">
            <input v-model="tavilyForm.include_image_descriptions" type="checkbox" />
            <span>{{ copy.tavilyIncludeDescriptionsLabel }}</span>
          </label>
        </div>

        <div class="llm-demo-actions">
          <button class="primary" type="button" :disabled="!canProbeTavily" @click="probeTavily">
            {{ tavilyPending ? copy.probingTavily : copy.probeTavily }}
          </button>
          <button type="button" @click="clearTavilyProbe">{{ copy.clearTavily }}</button>
        </div>

        <p v-if="tavilyErrorText" class="llm-demo-error">{{ tavilyErrorText }}</p>
      </aside>

      <main class="llm-demo-main">
        <section class="llm-demo-panel">
          <h2>{{ copy.chatTitle }}</h2>
          <div class="llm-demo-chat">
            <div v-if="messages.length === 0" class="llm-demo-empty">{{ copy.chatEmpty }}</div>
            <article v-for="(message, index) in messages" :key="`${message.role}-${index}`" :class="['llm-demo-message', `llm-demo-message--${message.role}`]">
              <header>{{ formatMessageRole(message.role) }}</header>
              <pre>{{ message.content }}</pre>
            </article>
          </div>
          <div class="llm-demo-composer">
            <textarea v-model="input" :placeholder="copy.composerPlaceholder"></textarea>
          </div>
        </section>

        <section class="llm-demo-panel">
          <h2>{{ copy.poiResultsTitle }}</h2>
          <div v-if="!poiProbeResult" class="llm-demo-empty">{{ copy.poiResultsEmpty }}</div>
          <div v-else class="llm-demo-results">
            <p class="llm-demo-meta">
              <strong>{{ copy.modelLabel }}:</strong> {{ poiProbeResult.model }} /
              {{ poiProbeResult.provider_protocol }} / {{ poiProbeResult.wire_api }}
            </p>
            <p class="llm-demo-meta">
              <strong>{{ copy.operationLabel }}:</strong> {{ poiProbeResult.prompt_version }} /
              {{ poiProbeResult.latency_ms }}ms / {{ poiProbeResult.payload_bytes }} bytes
            </p>
            <p v-if="poiProbeResult.parse_error" class="llm-demo-error">{{ poiProbeResult.parse_error }}</p>
            <p v-for="warning in poiProbeResult.warnings" :key="warning" class="llm-demo-error">{{ warning }}</p>

            <p class="llm-demo-section-title">{{ copy.poiSearchTitle }}</p>
            <pre>{{ formatPrettyJson(poiProbeResult.search) }}</pre>

            <p class="llm-demo-section-title">{{ copy.poiFeaturedPoisTitle }}</p>
            <div v-if="poiFeaturedPois.length === 0" class="llm-demo-empty">{{ copy.poiFeaturedPoisEmpty }}</div>
            <article v-for="poi in poiFeaturedPois" :key="`${poi.name || 'poi'}-${poi.area || ''}`" class="llm-demo-hit">
              <strong>{{ poi.name || "-" }}</strong>
              <p v-if="formatPoiMeta(poi)" class="llm-demo-meta">{{ formatPoiMeta(poi) }}</p>
              <p v-if="poi.reason">{{ poi.reason }}</p>
              <p v-if="formatPoiEvidence(poi)" class="llm-demo-meta">{{ formatPoiEvidence(poi) }}</p>
              <small v-if="formatStringList(poi.source_urls)">{{ formatStringList(poi.source_urls) }}</small>
            </article>

            <details>
              <summary>{{ copy.poiParsedJsonTitle }}</summary>
              <pre>{{ formatPrettyJson(poiProbeResult.parsed_json) }}</pre>
            </details>
            <details>
              <summary>{{ copy.poiSystemPromptTitle }}</summary>
              <pre>{{ poiProbeResult.system_prompt }}</pre>
            </details>
            <details>
              <summary>{{ copy.poiPromptPayloadTitle }}</summary>
              <pre>{{ formatPrettyJson(poiProbeResult.prompt_payload) }}</pre>
            </details>
            <details>
              <summary>{{ copy.poiRawTextTitle }}</summary>
              <pre>{{ poiProbeResult.raw_text }}</pre>
            </details>
          </div>
        </section>

        <section class="llm-demo-panel">
          <h2>{{ copy.searchResultsTitle }}</h2>
          <div v-if="!searchResult" class="llm-demo-empty">{{ copy.searchResultsEmpty }}</div>
          <div v-else class="llm-demo-results">
            <p class="llm-demo-meta"><strong>{{ copy.searchProviderLabel }}:</strong> {{ searchResult.provider }} / {{ searchResult.transport }}</p>
            <p class="llm-demo-meta"><strong>{{ copy.endpointLabel }}:</strong> {{ searchResult.base_url }}</p>
            <p class="llm-demo-meta"><strong>{{ copy.availableToolsLabel }}:</strong> {{ searchResult.available_tools.join(", ") || "-" }}</p>
            <p class="llm-demo-meta"><strong>{{ copy.operationLabel }}:</strong> {{ searchResult.operation }}</p>

            <div v-if="searchResult.hits.length === 0" class="llm-demo-empty">{{ copy.searchHitsEmpty }}</div>
            <article v-for="hit in searchResult.hits" :key="hit.url" class="llm-demo-hit">
              <a class="llm-demo-link" :href="hit.url" target="_blank" rel="noreferrer">{{ hit.title }}</a>
              <p v-if="hit.snippet">{{ hit.snippet }}</p>
              <small>{{ hit.url }}</small>
            </article>
          </div>
        </section>

        <section class="llm-demo-panel">
          <h2>{{ copy.imageResultsTitle }}</h2>
          <div v-if="!imageProbeResult" class="llm-demo-empty">{{ copy.imageResultsEmpty }}</div>
          <div v-else class="llm-demo-results">
            <p class="llm-demo-meta"><strong>{{ copy.searchProviderLabel }}:</strong> {{ imageProbeResult.provider }} / {{ imageProbeResult.transport }}</p>
            <p class="llm-demo-meta"><strong>{{ copy.endpointLabel }}:</strong> {{ imageProbeResult.base_url }}</p>
            <p class="llm-demo-meta"><strong>{{ copy.availableToolsLabel }}:</strong> {{ imageProbeResult.available_tools.join(", ") || "-" }}</p>
            <p class="llm-demo-meta"><strong>{{ copy.operationLabel }}:</strong> {{ imageProbeResult.operation }}</p>
            <p class="llm-demo-meta"><strong>{{ copy.imageStrategyLabel }}:</strong> {{ imageProbeResult.strategy }}</p>

            <div v-if="imageProbeResult.image_urls.length === 0" class="llm-demo-empty">{{ copy.imageUrlsEmpty }}</div>
            <div v-else class="llm-demo-image-grid">
              <article v-for="imageUrl in imageProbeResult.image_urls" :key="imageUrl" class="llm-demo-image-card">
                <img :src="imageUrl" :alt="imageUrl" loading="lazy" />
                <a class="llm-demo-link" :href="imageUrl" target="_blank" rel="noreferrer">{{ imageUrl }}</a>
              </article>
            </div>
          </div>
        </section>

        <section class="llm-demo-panel">
          <h2>{{ copy.xhsResultsTitle }}</h2>
          <div v-if="!xhsImageProbeResult" class="llm-demo-empty">{{ copy.xhsResultsEmpty }}</div>
          <div v-else class="llm-demo-results">
            <p class="llm-demo-meta"><strong>{{ copy.endpointLabel }}:</strong> {{ xhsImageProbeResult.base_url }}</p>
            <p class="llm-demo-meta"><strong>{{ copy.xhsDestinationLabel }}:</strong> {{ xhsImageProbeResult.destination }}</p>
            <p class="llm-demo-meta"><strong>{{ copy.xhsQueriesLabel }}:</strong> {{ xhsImageProbeResult.queries.join(" | ") }}</p>
            <p class="llm-demo-meta">
              {{ copy.xhsRecordsCount.replace("{count}", String(xhsImageProbeResult.record_count)) }} /
              {{ copy.xhsPostsCount.replace("{count}", String(xhsImageProbeResult.post_count)) }}
            </p>

            <article
              v-for="record in xhsImageProbeResult.records"
              :key="`${record.record_index}-${record.note_ref || record.record_summary.url || record.record_summary.post_id || 'record'}`"
              class="llm-demo-hit"
            >
              <a
                v-if="record.record_summary.url"
                class="llm-demo-link"
                :href="record.record_summary.url"
                target="_blank"
                rel="noreferrer"
              >
                {{ record.parsed_post?.title || record.record_summary.title || record.note_ref || `Record ${record.record_index + 1}` }}
              </a>
              <strong v-else>{{ record.parsed_post?.title || record.record_summary.title || record.note_ref || `Record ${record.record_index + 1}` }}</strong>
              <p class="llm-demo-meta">
                {{ [record.record_summary.author, record.record_summary.note_type, record.note_ref].filter(Boolean).join(" / ") }}
              </p>
              <p class="llm-demo-meta">
                {{ copy.xhsRawCandidatesLabel }}: {{ record.raw_image_candidates.length }} /
                {{ copy.xhsMergedCandidatesLabel }}: {{ record.merged_image_candidates.length }} /
                {{ copy.xhsParsedCandidatesLabel }}: {{ record.parsed_post?.image_urls?.length ?? 0 }}
              </p>
              <p v-if="record.detail_error" class="llm-demo-error">{{ record.detail_error }}</p>
              <p v-if="record.record_summary.raw_excerpt" class="llm-demo-image-description">{{ record.record_summary.raw_excerpt }}</p>

              <p v-if="record.raw_image_candidates.length" class="llm-demo-section-title">{{ copy.xhsRawCandidatesLabel }}</p>
              <div v-if="record.raw_image_candidates.length" class="llm-demo-image-grid">
                <article v-for="imageUrl in record.raw_image_candidates.slice(0, 6)" :key="`${record.record_index}-raw-${imageUrl}`" class="llm-demo-image-card">
                  <img :src="imageUrl" :alt="imageUrl" loading="lazy" />
                  <small class="llm-demo-image-meta">{{ formatHostLabel(imageUrl) }}</small>
                  <a class="llm-demo-link" :href="imageUrl" target="_blank" rel="noreferrer">{{ imageUrl }}</a>
                </article>
              </div>

              <p v-if="record.merged_image_candidates.length" class="llm-demo-section-title">{{ copy.xhsMergedCandidatesLabel }}</p>
              <div v-if="record.merged_image_candidates.length" class="llm-demo-image-grid">
                <article v-for="imageUrl in record.merged_image_candidates.slice(0, 6)" :key="`${record.record_index}-merged-${imageUrl}`" class="llm-demo-image-card">
                  <img :src="imageUrl" :alt="imageUrl" loading="lazy" />
                  <small class="llm-demo-image-meta">{{ formatHostLabel(imageUrl) }}</small>
                  <a class="llm-demo-link" :href="imageUrl" target="_blank" rel="noreferrer">{{ imageUrl }}</a>
                </article>
              </div>

              <p v-if="record.parsed_post?.image_urls?.length" class="llm-demo-section-title">{{ copy.xhsParsedCandidatesLabel }}</p>
              <div v-if="record.parsed_post?.image_urls?.length" class="llm-demo-image-grid">
                <article v-for="imageUrl in record.parsed_post.image_urls.slice(0, 6)" :key="`${record.record_index}-parsed-${imageUrl}`" class="llm-demo-image-card">
                  <img :src="imageUrl" :alt="imageUrl" loading="lazy" />
                  <small class="llm-demo-image-meta">{{ formatHostLabel(imageUrl) }}</small>
                  <a class="llm-demo-link" :href="imageUrl" target="_blank" rel="noreferrer">{{ imageUrl }}</a>
                </article>
              </div>

              <details v-if="record.raw_image_fields.length || record.merged_image_fields.length">
                <summary>{{ copy.xhsFieldDetailsLabel }}</summary>
                <p class="llm-demo-section-title">{{ copy.xhsRawFieldsLabel }}</p>
                <pre>{{ formatPrettyJson(record.raw_image_fields) }}</pre>
                <p class="llm-demo-section-title">{{ copy.xhsMergedFieldsLabel }}</p>
                <pre>{{ formatPrettyJson(record.merged_image_fields) }}</pre>
              </details>
            </article>
          </div>
        </section>

        <section class="llm-demo-panel">
          <h2>{{ copy.tavilyResultsTitle }}</h2>
          <div v-if="!tavilyResult" class="llm-demo-empty">{{ copy.tavilyResultsEmpty }}</div>
          <div v-else class="llm-demo-results">
            <p class="llm-demo-meta"><strong>{{ copy.searchProviderLabel }}:</strong> {{ tavilyResult.provider }}</p>
            <p class="llm-demo-meta"><strong>{{ copy.endpointLabel }}:</strong> {{ tavilyResult.base_url }}</p>

            <p class="llm-demo-section-title">{{ copy.tavilyCandidatesTitle }}</p>
            <p class="llm-demo-meta">{{ copy.tavilyCandidatesCount.replace("{count}", tavilyCandidateCountText) }}</p>
            <div v-if="tavilyImageCandidates.length === 0" class="llm-demo-empty">{{ copy.tavilyImagesEmpty }}</div>
            <div v-else class="llm-demo-image-grid">
              <article v-for="(image, index) in tavilyImageCandidates" :key="`${image.url}-${index}`" class="llm-demo-image-card">
                <img :src="image.url" :alt="image.description || image.title || image.result_title || image.url" loading="lazy" />
                <strong v-if="image.title || image.result_title" class="llm-demo-image-title">{{ summarizeText(image.title || image.result_title || "", 64) }}</strong>
                <p v-if="image.description" class="llm-demo-image-description">{{ summarizeText(image.description) }}</p>
                <small class="llm-demo-image-meta">{{ image.source_domain || image.source }} / {{ formatHostLabel(image.url) }}</small>
                <small v-if="image.result_url" class="llm-demo-image-meta">{{ formatHostLabel(image.result_url) }}</small>
                <div class="llm-demo-image-actions">
                  <a class="llm-demo-link llm-demo-link--button" :href="image.url" target="_blank" rel="noreferrer">{{ copy.openImageLabel }}</a>
                  <a v-if="image.result_url" class="llm-demo-link llm-demo-link--button llm-demo-link--soft" :href="image.result_url" target="_blank" rel="noreferrer">{{ copy.openSourceLabel }}</a>
                </div>
              </article>
            </div>

            <p class="llm-demo-section-title">{{ copy.tavilyTopImagesTitle }}</p>
            <p class="llm-demo-meta">{{ copy.tavilyTopImagesCount.replace("{count}", tavilyTopImagesCountText) }}</p>
            <div v-if="tavilyResult.top_level_images.length === 0" class="llm-demo-empty">{{ copy.tavilyImagesEmpty }}</div>
            <div v-else class="llm-demo-image-grid">
              <article v-for="(image, index) in tavilyResult.top_level_images" :key="`${image.url}-${index}`" class="llm-demo-image-card">
                <img v-if="image.url" :src="image.url" :alt="image.description || image.url" loading="lazy" />
                <p v-if="image.description" class="llm-demo-image-description">{{ summarizeText(image.description) }}</p>
                <small v-if="image.url" class="llm-demo-image-meta">{{ image.source_domain || formatHostLabel(image.url) }}</small>
                <div class="llm-demo-image-actions">
                  <a v-if="image.url" class="llm-demo-link llm-demo-link--button" :href="image.url" target="_blank" rel="noreferrer">{{ copy.openImageLabel }}</a>
                </div>
              </article>
            </div>

            <p class="llm-demo-section-title">{{ copy.tavilyResultImagesTitle }}</p>
            <p class="llm-demo-meta">{{ copy.tavilyResultImagesCount.replace("{count}", tavilyResultImagesCountText) }}</p>
            <div v-if="tavilyResult.result_images.length === 0" class="llm-demo-empty">{{ copy.tavilyImagesEmpty }}</div>
            <div v-else class="llm-demo-image-grid">
              <article v-for="(image, index) in tavilyResult.result_images" :key="`${image.url}-${index}`" class="llm-demo-image-card">
                <img :src="image.url" :alt="image.description || image.result_title || image.url" loading="lazy" />
                <strong v-if="image.result_title" class="llm-demo-image-title">{{ summarizeText(image.result_title, 64) }}</strong>
                <p v-if="image.description" class="llm-demo-image-description">{{ summarizeText(image.description) }}</p>
                <small class="llm-demo-image-meta">{{ image.source_domain || formatHostLabel(image.url) }}</small>
                <small v-if="image.result_url" class="llm-demo-image-meta">{{ formatHostLabel(image.result_url) }}</small>
                <div class="llm-demo-image-actions">
                  <a class="llm-demo-link llm-demo-link--button" :href="image.url" target="_blank" rel="noreferrer">{{ copy.openImageLabel }}</a>
                  <a v-if="image.result_url" class="llm-demo-link llm-demo-link--button llm-demo-link--soft" :href="image.result_url" target="_blank" rel="noreferrer">{{ copy.openSourceLabel }}</a>
                </div>
              </article>
            </div>
          </div>
        </section>

        <section class="llm-demo-panel">
          <h2>{{ copy.rawRequestTitle }}</h2>
          <pre>{{ rawRequest || copy.rawRequestEmpty }}</pre>
        </section>

        <section class="llm-demo-panel">
          <h2>{{ copy.rawResponseTitle }}</h2>
          <pre>{{ rawResponse || copy.rawResponseEmpty }}</pre>
        </section>

        <section class="llm-demo-panel">
          <h2>{{ copy.searchRequestTitle }}</h2>
          <pre>{{ searchRawRequest || copy.searchRequestEmpty }}</pre>
        </section>

        <section class="llm-demo-panel">
          <h2>{{ copy.searchResponseTitle }}</h2>
          <pre>{{ searchRawResponse || copy.searchResponseEmpty }}</pre>
        </section>

        <section class="llm-demo-panel">
          <h2>{{ copy.poiRequestTitle }}</h2>
          <pre>{{ poiProbeRawRequest || copy.poiRequestEmpty }}</pre>
        </section>

        <section class="llm-demo-panel">
          <h2>{{ copy.poiResponseTitle }}</h2>
          <pre>{{ poiProbeRawResponse || copy.poiResponseEmpty }}</pre>
        </section>

        <section class="llm-demo-panel">
          <h2>{{ copy.imageRequestTitle }}</h2>
          <pre>{{ imageProbeRawRequest || copy.imageRequestEmpty }}</pre>
        </section>

        <section class="llm-demo-panel">
          <h2>{{ copy.imageResponseTitle }}</h2>
          <pre>{{ imageProbeRawResponse || copy.imageResponseEmpty }}</pre>
        </section>

        <section class="llm-demo-panel">
          <h2>{{ copy.xhsRequestTitle }}</h2>
          <pre>{{ xhsImageRawRequest || copy.xhsRequestEmpty }}</pre>
        </section>

        <section class="llm-demo-panel">
          <h2>{{ copy.xhsResponseTitle }}</h2>
          <pre>{{ xhsImageRawResponse || copy.xhsResponseEmpty }}</pre>
        </section>

        <section class="llm-demo-panel">
          <h2>{{ copy.tavilyRequestTitle }}</h2>
          <pre>{{ tavilyRawRequest || copy.tavilyRequestEmpty }}</pre>
        </section>

        <section class="llm-demo-panel">
          <h2>{{ copy.tavilyResponseTitle }}</h2>
          <pre>{{ tavilyRawResponse || copy.tavilyResponseEmpty }}</pre>
        </section>
      </main>
    </section>
  </div>
</template>

<style scoped>
.llm-demo-page {
  min-height: 100vh;
  padding: 24px;
  background: linear-gradient(135deg, #f8f4ee 0%, #f4efe6 100%);
}

.llm-demo-shell {
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr);
  gap: 20px;
}

.llm-demo-sidebar,
.llm-demo-panel {
  background: rgba(255, 252, 247, 0.92);
  border: 1px solid rgba(30, 28, 23, 0.12);
  border-radius: 24px;
  box-shadow: 0 18px 40px rgba(54, 41, 20, 0.12);
  padding: 24px;
}

.llm-demo-kicker {
  margin: 0 0 8px;
  font-size: 0.8rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #c96d3b;
  font-weight: 800;
}

.llm-demo-muted {
  color: #60574b;
}

.llm-demo-section-title {
  margin: 0;
  font-size: 0.85rem;
  font-weight: 800;
  text-transform: uppercase;
  color: #8a4c2e;
}

.llm-demo-divider {
  height: 1px;
  margin: 24px 0;
  background: rgba(30, 28, 23, 0.08);
}

.llm-demo-form {
  display: grid;
  gap: 14px;
  margin-top: 24px;
}

.llm-demo-form label {
  display: grid;
  gap: 8px;
  font-weight: 700;
}

.llm-demo-form input,
.llm-demo-form select,
.llm-demo-form textarea,
.llm-demo-composer textarea {
  width: 100%;
  border: 1px solid rgba(30, 28, 23, 0.14);
  border-radius: 16px;
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.9);
  font: inherit;
}

.llm-demo-form textarea,
.llm-demo-composer textarea {
  min-height: 112px;
  resize: vertical;
}

.llm-demo-toggle {
  display: flex !important;
  align-items: center;
  gap: 10px;
}

.llm-demo-toggle input {
  width: 18px;
  height: 18px;
  margin: 0;
}

.llm-demo-help {
  color: #6f665a;
  font-weight: 500;
}

.llm-demo-actions {
  display: flex;
  gap: 10px;
  margin-top: 20px;
  flex-wrap: wrap;
}

.llm-demo-actions button {
  border-radius: 999px;
  padding: 10px 16px;
  border: 1px solid rgba(30, 28, 23, 0.14);
  background: rgba(255, 255, 255, 0.7);
  cursor: pointer;
}

.llm-demo-actions button.primary {
  background: #1e1c17;
  color: white;
}

.llm-demo-actions button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.llm-demo-error {
  color: #8a2317;
  margin-top: 16px;
  font-weight: 700;
}

.llm-demo-main {
  display: grid;
  gap: 20px;
}

.llm-demo-chat,
.llm-demo-results {
  display: grid;
  gap: 12px;
}

.llm-demo-empty {
  color: #60574b;
}

.llm-demo-message,
.llm-demo-hit {
  border-radius: 18px;
  padding: 14px;
  border: 1px solid rgba(30, 28, 23, 0.12);
}

.llm-demo-message--user {
  background: rgba(13, 122, 111, 0.08);
}

.llm-demo-message--assistant,
.llm-demo-hit {
  background: rgba(255, 255, 255, 0.8);
}

.llm-demo-image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 14px;
  align-items: start;
}

.llm-demo-image-card {
  display: grid;
  gap: 8px;
  padding: 12px;
  border: 1px solid rgba(30, 28, 23, 0.08);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.82);
  min-width: 0;
  overflow: hidden;
}

.llm-demo-image-card img {
  width: 100%;
  aspect-ratio: 1 / 1;
  object-fit: cover;
  border-radius: 12px;
  border: 1px solid rgba(30, 28, 23, 0.08);
  background: rgba(247, 243, 236, 0.95);
}

.llm-demo-image-title,
.llm-demo-image-description,
.llm-demo-image-meta {
  margin: 0;
  min-width: 0;
}

.llm-demo-image-title {
  color: #1e1c17;
}

.llm-demo-image-description {
  color: #51493f;
  line-height: 1.45;
}

.llm-demo-image-meta {
  color: #7a7063;
  overflow-wrap: anywhere;
}

.llm-demo-image-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.llm-demo-message--error {
  background: rgba(255, 226, 223, 0.8);
  border-color: rgba(138, 35, 23, 0.25);
}

.llm-demo-message header {
  font-weight: 800;
  text-transform: uppercase;
  font-size: 0.75rem;
  margin-bottom: 8px;
}

.llm-demo-meta {
  margin: 0;
  color: #51493f;
}

.llm-demo-link {
  color: #1e1c17;
  font-weight: 800;
  text-decoration: none;
  overflow-wrap: anywhere;
}

.llm-demo-link:hover {
  text-decoration: underline;
}

.llm-demo-link--button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid rgba(30, 28, 23, 0.14);
  background: rgba(255, 255, 255, 0.92);
  text-decoration: none;
}

.llm-demo-link--button:hover {
  text-decoration: none;
  background: rgba(245, 240, 231, 0.98);
}

.llm-demo-link--soft {
  font-weight: 700;
}

.llm-demo-message pre,
.llm-demo-panel pre {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

@media (max-width: 980px) {
  .llm-demo-shell {
    grid-template-columns: 1fr;
  }
}
</style>
