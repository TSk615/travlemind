import { defineStore } from "pinia"
import type {
  ImageProvider,
  LlmAgentProvider,
  LlmProviderProtocol,
  LlmSettings,
  LlmSettingsInput,
  LlmWireApi,
  SearchServiceProvider,
  SearchServiceTransport
} from "@travelmind/shared-types"
import { api, getErrorMessage } from "@/lib/api"

export interface RuntimeLlmConfig {
  provider_protocol: LlmProviderProtocol
  base_url: string
  model: string
  wire_api: LlmWireApi
  agent_provider: LlmAgentProvider
}

export interface RuntimeImageConfig {
  base_url: string
  model: string
  provider: ImageProvider
}

interface LlmSettingsState {
  settings: LlmSettings | null
  runtimeConfig: RuntimeLlmConfig | null
  imageRuntimeConfig: RuntimeImageConfig | null
  loaded: boolean
  loading: boolean
  pending: boolean
  error: string | null
  saveError: string | null
}

function normalizeWireApi(value: string | null | undefined): LlmWireApi {
  return value === "chat_completions" ? "chat_completions" : "responses"
}

function normalizeProviderProtocol(value: string | null | undefined): LlmProviderProtocol {
  if (value === "newapi") {
    return "newapi"
  }
  if (value === "gemini") {
    return "gemini"
  }
  if (value === "claude") {
    return "claude"
  }
  if (value === "neiapi") {
    return "neiapi"
  }
  return "openai"
}

function normalizeAgentProvider(value: string | null | undefined): LlmAgentProvider {
  if (value === "helloagents" || value === "langgraph") {
    return "langgraph"
  }
  return "standard"
}

function normalizeSearchTransport(value: string | null | undefined): SearchServiceTransport {
  return value === "api" ? "api" : "mcp"
}

function normalizeSearchProvider(value: string | null | undefined): SearchServiceProvider {
  if (value === "tavily") {
    return "tavily"
  }
  return "groksearch"
}

function normalizeImageProvider(value: string | null | undefined): ImageProvider {
  if (value === "huggingface") {
    return "huggingface"
  }
  if (value === "gitee_ai") {
    return "gitee_ai"
  }
  if (value === "modelscope") {
    return "modelscope"
  }
  if (value === "a4f") {
    return "a4f"
  }
  return "openai_compatible"
}

function normalizeSettings(settings: LlmSettings): LlmSettings {
  return {
    agent: {
      ...settings.agent,
      provider_protocol: normalizeProviderProtocol(settings.agent.provider_protocol),
      wire_api: normalizeWireApi(settings.agent.wire_api),
      agent_provider: normalizeAgentProvider(settings.agent.agent_provider)
    },
    search: {
      ...settings.search,
      provider: normalizeSearchProvider(settings.search.provider),
      transport: normalizeSearchTransport(settings.search.transport),
      xhs_source_enabled: Boolean(settings.search.xhs_source_enabled)
    },
    image: {
      ...settings.image,
      provider: normalizeImageProvider(settings.image.provider)
    }
  }
}

function buildRuntimeConfig(settings: LlmSettings | null): RuntimeLlmConfig | null {
  const base_url = settings?.agent.base_url?.trim() ?? ""
  const model = settings?.agent.model?.trim() ?? ""
  if (!base_url || !model) {
    return null
  }

  return {
    provider_protocol: normalizeProviderProtocol(settings?.agent.provider_protocol),
    base_url,
    model,
    wire_api: normalizeWireApi(settings?.agent.wire_api),
    agent_provider: normalizeAgentProvider(settings?.agent.agent_provider)
  }
}

function buildImageRuntimeConfig(settings: LlmSettings | null): RuntimeImageConfig | null {
  const base_url = settings?.image.base_url?.trim() ?? ""
  const model = settings?.image.model?.trim() ?? ""
  if (!base_url || !model) {
    return null
  }
  return {
    base_url,
    model,
    provider: normalizeImageProvider(settings?.image.provider)
  }
}

export const useLlmSettingsStore = defineStore("llm-settings", {
  state: (): LlmSettingsState => ({
    settings: null,
    runtimeConfig: null,
    imageRuntimeConfig: null,
    loaded: false,
    loading: false,
    pending: false,
    error: null,
    saveError: null
  }),
  getters: {
    isConfigured: (state) => Boolean(state.settings?.agent.configured),
    isImageConfigured: (state) => Boolean(state.settings?.image.configured),
    hasStoredKey: (state) => Boolean(state.settings?.agent.has_api_key || state.settings?.agent.api_key_masked),
    resolvedConfig: (state) => state.runtimeConfig,
    resolvedImageConfig: (state) => state.imageRuntimeConfig,
    agentProvider: (state) => normalizeAgentProvider(state.settings?.agent.agent_provider),
    providerProtocol: (state) => normalizeProviderProtocol(state.settings?.agent.provider_protocol),
    usesLangGraph: (state) => normalizeAgentProvider(state.settings?.agent.agent_provider) === "langgraph"
  },
  actions: {
    reset() {
      this.settings = null
      this.runtimeConfig = null
      this.imageRuntimeConfig = null
      this.loaded = false
      this.loading = false
      this.pending = false
      this.error = null
      this.saveError = null
    },
    async bootstrap() {
      if (this.loaded || this.loading) {
        return
      }
      await this.fetch()
    },
    async fetch(force = false) {
      if (this.loading || (!force && this.loaded)) {
        return
      }

      this.loading = true
      this.error = null
      try {
        const settings = normalizeSettings(await api.getLlmSettings())
        this.settings = settings
        this.runtimeConfig = buildRuntimeConfig(settings)
        this.imageRuntimeConfig = buildImageRuntimeConfig(settings)
      } catch (error) {
        this.runtimeConfig = null
        this.imageRuntimeConfig = null
        this.settings = null
        this.error = getErrorMessage(error, "Unable to load model settings")
      } finally {
        this.loaded = true
        this.loading = false
      }
    },
    async save(payload: LlmSettingsInput) {
      this.pending = true
      this.saveError = null
      this.error = null

      try {
        const settings = normalizeSettings(await api.updateLlmSettings(payload))
        this.settings = settings
        this.runtimeConfig = buildRuntimeConfig(settings)
        this.imageRuntimeConfig = buildImageRuntimeConfig(settings)
        this.loaded = true
        return this.settings
      } catch (error) {
        this.saveError = getErrorMessage(error, "Unable to save model settings")
        throw error
      } finally {
        this.pending = false
      }
    }
  }
})
