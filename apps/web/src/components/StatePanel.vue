<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "@/lib/useI18n"

const props = withDefaults(
  defineProps<{
    kind?: "loading" | "error" | "empty" | "info"
    title: string
    message: string
    actionLabel?: string
    compact?: boolean
  }>(),
  {
    kind: "info",
    actionLabel: undefined,
    compact: false
  }
)

const emit = defineEmits<{
  action: []
}>()

const { t } = useI18n()
const kindLabel = computed(() => t(`state.kind.${props.kind}`))
</script>

<template>
  <article :class="['state-panel', `state-panel--${props.kind}`, { 'state-panel--compact': props.compact }]">
    <div class="state-panel__header">
      <span v-if="props.kind === 'loading'" class="state-panel__spinner" aria-hidden="true"></span>
      <p class="kicker">{{ kindLabel }}</p>
    </div>
    <h3>{{ props.title }}</h3>
    <p class="state-panel__message">{{ props.message }}</p>
    <div v-if="props.actionLabel || $slots.actions" class="inline-actions">
      <button v-if="props.actionLabel" class="primary" type="button" @click="emit('action')">{{ props.actionLabel }}</button>
      <slot name="actions" />
    </div>
    <slot />
  </article>
</template>