<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue"
import type { LlmSettingsInput, LlmWireApi } from "@travelmind/shared-types"
import LlmStatusNotice from "@/components/LlmStatusNotice.vue"
import StatePanel from "@/components/StatePanel.vue"
import { useI18n } from "@/lib/useI18n"
import { useLlmSettingsStore } from "@/stores/llmSettings"

const settingsStore = useLlmSettingsStore()
const saveSuccess = ref<string | null>(null)
void settingsStore.bootstrap()

const form = reactive<{
  base_url: string
  api_key: string
  model: string
  wire_api: LlmWireApi
}>({
  base_url: "",
  api_key: "",
  model: "",
  wire_api: "responses"
})

const enCopy = {
  kicker: "Settings",
  title: "Browser-side model configuration",
  description: "These values are stored only in your current browser. Generation and refinement will call the third-party model directly from the frontend.",
  baseUrlLabel: "Base URL",
  baseUrlPlaceholder: "https://api.example.com/v1",
  modelLabel: "Model",
  modelPlaceholder: "gpt-5.4",
  wireApiLabel: "API format",
  wireApiResponses: "Responses API",
  wireApiChat: "Chat Completions API",
  apiKeyLabel: "API key",
  apiKeyPlaceholder: "Enter a new key to save or replace",
  savedKeyLabel: "Stored key",
  noStoredKey: "No API key is stored yet.",
  keyHelp: "Leave the API key blank to keep the currently stored key unchanged in this browser.",
  save: "Save settings",
  saving: "Saving...",
  refresh: "Reload",
  saveSuccessTitle: "Settings saved locally",
  saveSuccessMessage: "The browser will use this configuration for direct third-party model calls.",
  loadErrorTitle: "Unable to load local settings",
  saveErrorTitle: "Unable to save local settings",
  statusHint: "Use Responses API when the provider exposes /responses. Use Chat Completions API when it exposes /chat/completions."
}

const zhCopy = {
  kicker: "设置",
  title: "浏览器端模型配置",
  description: "这些配置只保存在当前浏览器中。生成和 refine 会由前端直接调用第三方模型接口。",
  baseUrlLabel: "Base URL",
  baseUrlPlaceholder: "https://api.example.com/v1",
  modelLabel: "Model",
  modelPlaceholder: "gpt-5.4",
  wireApiLabel: "接口格式",
  wireApiResponses: "Responses API",
  wireApiChat: "Chat Completions API",
  apiKeyLabel: "API Key",
  apiKeyPlaceholder: "输入新的 key 以保存或替换",
  savedKeyLabel: "已保存的 Key",
  noStoredKey: "当前还没有保存 API Key。",
  keyHelp: "如果不想替换当前 key，可以把 API Key 输入框留空。",
  save: "保存设置",
  saving: "保存中...",
  refresh: "重新加载",
  saveSuccessTitle: "设置已保存到浏览器",
  saveSuccessMessage: "当前浏览器会用这组配置直接调用第三方模型接口。",
  loadErrorTitle: "读取本地设置失败",
  saveErrorTitle: "保存本地设置失败",
  statusHint: "如果第三方提供的是 /responses，请选择 Responses API；如果提供的是 /chat/completions，请选择 Chat Completions API。"
}

const { locale } = useI18n()
const copy = computed(() => (locale.value === "zh-CN" ? zhCopy : enCopy))
const storedKeyText = computed(() => settingsStore.settings?.api_key_masked?.trim() || copy.value.noStoredKey)

watch(
  () => settingsStore.settings,
  (settings) => {
    form.base_url = settings?.base_url ?? ""
    form.model = settings?.model ?? ""
    form.api_key = ""
    form.wire_api = settings?.wire_api ?? "responses"
  },
  { immediate: true }
)

async function refresh() {
  saveSuccess.value = null
  await settingsStore.fetch(true)
}

async function save() {
  saveSuccess.value = null

  const payload: LlmSettingsInput = {
    base_url: form.base_url.trim(),
    model: form.model.trim(),
    wire_api: form.wire_api
  }

  const nextApiKey = form.api_key.trim()
  if (nextApiKey) {
    payload.api_key = nextApiKey
  }

  try {
    await settingsStore.save(payload)
    form.api_key = ""
    saveSuccess.value = copy.value.saveSuccessMessage
  } catch {
    // The store already exposes a user-facing save error state.
  }
}
</script>

<template>
  <section class="page-grid" style="max-width: 960px; margin: 0 auto;">
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
        <div class="field field--full">
          <label for="base-url">{{ copy.baseUrlLabel }}</label>
          <input id="base-url" v-model="form.base_url" :placeholder="copy.baseUrlPlaceholder" />
        </div>

        <div class="field">
          <label for="model">{{ copy.modelLabel }}</label>
          <input id="model" v-model="form.model" :placeholder="copy.modelPlaceholder" />
        </div>

        <div class="field">
          <label for="wire-api">{{ copy.wireApiLabel }}</label>
          <select id="wire-api" v-model="form.wire_api">
            <option value="responses">{{ copy.wireApiResponses }}</option>
            <option value="chat_completions">{{ copy.wireApiChat }}</option>
          </select>
        </div>

        <div class="field field--full">
          <label for="api-key">{{ copy.apiKeyLabel }}</label>
          <input id="api-key" v-model="form.api_key" type="password" autocomplete="new-password" :placeholder="copy.apiKeyPlaceholder" />
        </div>

        <div class="field field--full">
          <p class="muted"><strong>{{ copy.savedKeyLabel }}:</strong> {{ storedKeyText }}</p>
          <p class="muted">{{ copy.keyHelp }}</p>
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