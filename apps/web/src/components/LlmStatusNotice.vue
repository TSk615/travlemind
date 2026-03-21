<script setup lang="ts">
import { computed } from "vue"
import { RouterLink } from "vue-router"
import StatePanel from "@/components/StatePanel.vue"
import { useI18n } from "@/lib/useI18n"
import { useLlmSettingsStore } from "@/stores/llmSettings"

withDefaults(
  defineProps<{
    compact?: boolean
  }>(),
  {
    compact: false
  }
)

const settingsStore = useLlmSettingsStore()
const { locale } = useI18n()
void settingsStore.bootstrap()

const enCopy = {
  loadingTitle: "Loading model status",
  loadingMessage: "Checking whether trip generation will use a real model or the current fallback pipeline.",
  configuredTitle: "Browser-side model is configured",
  configuredMessage: "Generation and refinement will call the third-party model directly from this browser.",
  configuredDetailPrefix: "Current model",
  fallbackTitle: "Local model config is missing",
  fallbackMessage: "Add base URL, API key, model, and API format before running generation directly from the browser.",
  action: "Model settings"
}

const zhCopy = {
  loadingTitle: "正在读取模型状态",
  loadingMessage: "正在确认当前浏览器是否已经配置好可直接调用的第三方模型。",
  configuredTitle: "浏览器端真实模型已配置",
  configuredMessage: "生成和 refine 会直接由当前浏览器调用第三方模型接口。",
  configuredDetailPrefix: "当前模型",
  fallbackTitle: "本地模型配置缺失",
  fallbackMessage: "请先填写 base URL、API Key、model 和接口格式，浏览器才会直接调用第三方模型。",
  action: "模型设置"
}

const copy = computed(() => (locale.value === "zh-CN" ? zhCopy : enCopy))

const title = computed(() => (settingsStore.isConfigured ? copy.value.configuredTitle : copy.value.fallbackTitle))
const message = computed(() => {
  if (settingsStore.isConfigured) {
    const model = settingsStore.settings?.model?.trim()
    const wireApi = settingsStore.settings?.wire_api ?? "responses"
    return model
      ? `${copy.value.configuredMessage} ${copy.value.configuredDetailPrefix}: ${model} (${wireApi}).`
      : copy.value.configuredMessage
  }

  return copy.value.fallbackMessage
})
</script>

<template>
  <StatePanel
    v-if="settingsStore.loading && !settingsStore.loaded"
    kind="loading"
    :title="copy.loadingTitle"
    :message="copy.loadingMessage"
    :compact="compact"
  />

  <StatePanel
    v-else
    :kind="settingsStore.isConfigured ? 'info' : 'empty'"
    :title="title"
    :message="message"
    :compact="compact"
  >
    <template #actions>
      <RouterLink class="button-link" to="/settings">{{ copy.action }}</RouterLink>
    </template>
  </StatePanel>
</template>