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
  loadingMessage: "Checking which provider and model configuration are active for future generation and refinement requests.",
  helloConfiguredTitle: "Current provider configuration: HelloAgents",
  helloConfiguredMessage:
    "Future trip generation requests will attempt the backend HelloAgents PoC workflow. This card reflects saved settings, not the latest execution result. Refinement still uses the browser relay with your saved model settings.",
  standardConfiguredTitle: "Current provider configuration: Standard",
  standardConfiguredMessage:
    "Future generation and refinement requests will use the saved third-party model configuration. This card reflects saved settings, not the latest execution result.",
  configuredDetailPrefix: "Saved model",
  fallbackTitle: "Model settings are incomplete",
  fallbackMessage: "Add base URL, API key, model, and API format before running generation or refinement.",
  action: "Model settings"
}

const zhCopy = {
  loadingTitle: "正在读取模型配置",
  loadingMessage: "正在确认后续生成与润色将使用的服务提供方和模型配置。",
  helloConfiguredTitle: "当前提供方配置：HelloAgents",
  helloConfiguredMessage:
    "后续行程生成会尝试走后端 HelloAgents PoC 工作流。此卡片只展示你保存的配置，不代表最近一次实际执行结果。润色仍会通过浏览器中转，并使用你保存的模型设置。",
  standardConfiguredTitle: "当前提供方配置：标准模式",
  standardConfiguredMessage:
    "后续生成与润色会使用你保存的第三方模型配置。此卡片只展示你保存的配置，不代表最近一次实际执行结果。",
  configuredDetailPrefix: "已保存模型",
  fallbackTitle: "模型配置不完整",
  fallbackMessage: "请先填写接口地址、API 密钥、模型和接口格式，再执行生成或润色。",
  action: "模型设置"
}

const copy = computed(() => (locale.value === "zh-CN" ? zhCopy : enCopy))
const usesHelloAgents = computed(() => settingsStore.usesHelloAgents)
const title = computed(() => {
  if (!settingsStore.isConfigured) {
    return copy.value.fallbackTitle
  }
  return usesHelloAgents.value ? copy.value.helloConfiguredTitle : copy.value.standardConfiguredTitle
})
const message = computed(() => {
  if (!settingsStore.isConfigured) {
    return copy.value.fallbackMessage
  }

  const model = settingsStore.settings?.agent.model?.trim()
  const wireApi = settingsStore.settings?.agent.wire_api ?? "responses"
  const prefix = usesHelloAgents.value ? copy.value.helloConfiguredMessage : copy.value.standardConfiguredMessage
  return model ? `${prefix} ${copy.value.configuredDetailPrefix}: ${model} (${wireApi}).` : prefix
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
