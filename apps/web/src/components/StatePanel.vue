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
  <article :class="['state-panel', `state-panel--${props.kind}`, { 'state-panel--compact': props.compact }]" :aria-live="props.kind === 'loading' ? 'polite' : undefined">
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

<style scoped>
.state-panel {
  display: grid;
  gap: var(--tm-space-3, 12px);
  padding: var(--tm-space-6, 22px);
  border-radius: var(--tm-radius-xl, 24px);
  background-color: var(--tm-snow, rgba(255, 255, 255, 0.4));
  border: var(--tm-border-subtle, 1px solid rgba(43, 42, 40, 0.10));
  box-shadow: var(--tm-shadow-card, none);
}

.state-panel--compact {
  padding: var(--tm-space-4, 18px);
}

.state-panel--error {
  border-color: var(--tm-error-border, rgba(199, 91, 74, 0.12));
  background-color: var(--tm-error-bg, rgba(199, 91, 74, 0.08));
}

.state-panel--loading {
  border-color: var(--tm-info-border, rgba(107, 157, 173, 0.12));
}

.state-panel--empty {
  border-style: dashed;
  border-color: var(--tm-border-visible, rgba(43, 42, 40, 0.16));
}

.state-panel__header {
  display: flex;
  align-items: center;
  gap: var(--tm-space-2, 10px);
}

.state-panel__spinner {
  width: 12px;
  height: 12px;
  border-radius: 999px;
  border: 2px solid var(--tm-info-border, rgba(107, 157, 173, 0.18));
  border-top-color: var(--tm-moss, #5D7A63);
  animation: tm-spin 0.9s linear infinite;
}

.state-panel__message {
  margin: 0;
  color: var(--tm-stone, #8A8580);
  font-size: var(--tm-text-sm, 0.875rem);
  line-height: var(--tm-leading-normal, 1.6);
}

.state-panel h3 {
  margin: 0;
  font-size: var(--tm-text-lg, 1.125rem);
}

.state-panel .kicker {
  font-size: var(--tm-text-xs, 0.75rem);
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  color: var(--tm-clay, #C98F6B);
  margin: 0;
}

.state-panel .inline-actions {
  display: flex;
  gap: var(--tm-space-2, 10px);
  flex-wrap: wrap;
  margin-top: var(--tm-space-2, 8px);
}

@keyframes tm-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .state-panel__spinner {
    animation: none;
    border-top-color: var(--tm-moss, #5D7A63);
    opacity: 0.6;
  }
}
</style>