import { defineStore } from "pinia"
import type { LlmSettings, LlmSettingsInput, LlmWireApi } from "@travelmind/shared-types"
import { getErrorMessage } from "@/lib/api"

const STORAGE_KEY = "travelmind.llm.settings"
const DEMO_STORAGE_KEY = "travelmind.llm.demo"

export interface RuntimeLlmConfig {
  base_url: string
  api_key: string
  model: string
  wire_api: LlmWireApi
}

interface LlmSettingsState {
  settings: LlmSettings | null
  runtimeConfig: RuntimeLlmConfig | null
  loaded: boolean
  loading: boolean
  pending: boolean
  error: string | null
  saveError: string | null
}

function maskApiKey(apiKey: string | null): string | null {
  if (!apiKey) {
    return null
  }
  if (apiKey.length <= 8) {
    return `${apiKey.slice(0, 2)}${"*".repeat(Math.max(apiKey.length - 2, 2))}`
  }
  return `${apiKey.slice(0, 4)}${"*".repeat(apiKey.length - 8)}${apiKey.slice(-4)}`
}

function normalizeWireApi(value: string | null | undefined): LlmWireApi {
  return value === "chat_completions" ? "chat_completions" : "responses"
}

function buildPublicSettings(config: RuntimeLlmConfig | null): LlmSettings {
  return {
    base_url: config?.base_url ?? null,
    model: config?.model ?? null,
    api_key_masked: maskApiKey(config?.api_key ?? null),
    has_api_key: Boolean(config?.api_key),
    wire_api: config?.wire_api ?? "responses",
    configured: Boolean(config?.base_url && config?.api_key && config?.model)
  }
}

function readStoredConfig(): RuntimeLlmConfig | null {
  if (typeof window === "undefined") {
    return null
  }

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) {
      return null
    }
    const parsed = JSON.parse(raw) as Partial<RuntimeLlmConfig>
    const base_url = String(parsed.base_url ?? "").trim()
    const api_key = String(parsed.api_key ?? "").trim()
    const model = String(parsed.model ?? "").trim()
    const wire_api = normalizeWireApi(parsed.wire_api)

    if (!base_url && !api_key && !model) {
      return null
    }

    return {
      base_url,
      api_key,
      model,
      wire_api
    }
  } catch {
    return null
  }
}

function writeStoredConfig(config: RuntimeLlmConfig | null): void {
  if (typeof window === "undefined") {
    return
  }

  try {
    if (config === null) {
      window.localStorage.removeItem(STORAGE_KEY)
      return
    }
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
  } catch {
    // Ignore storage failures in restricted contexts.
  }
}

function mergePayload(current: RuntimeLlmConfig | null, payload: LlmSettingsInput): RuntimeLlmConfig {
  const base_url = payload.base_url.trim()
  const model = payload.model.trim()
  const api_key = payload.api_key?.trim() ? payload.api_key.trim() : current?.api_key ?? ""
  const wire_api = normalizeWireApi(payload.wire_api)

  return {
    base_url,
    api_key,
    model,
    wire_api
  }
}

export const useLlmSettingsStore = defineStore("llm-settings", {
  state: (): LlmSettingsState => ({
    settings: null,
    runtimeConfig: null,
    loaded: false,
    loading: false,
    pending: false,
    error: null,
    saveError: null
  }),
  getters: {
    isConfigured: (state) => Boolean(state.settings?.configured),
    hasStoredKey: (state) => Boolean(state.settings?.has_api_key || state.settings?.api_key_masked),
    resolvedConfig: (state) => state.runtimeConfig
  },
  actions: {
    reset() {
      this.settings = null
      this.runtimeConfig = null
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
        this.runtimeConfig = readStoredConfig()
        this.settings = buildPublicSettings(this.runtimeConfig)
      } catch (error) {
        this.runtimeConfig = null
        this.settings = buildPublicSettings(null)
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
        const nextConfig = mergePayload(this.runtimeConfig, payload)
        writeStoredConfig(nextConfig)
        this.runtimeConfig = nextConfig
        this.settings = buildPublicSettings(nextConfig)
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
