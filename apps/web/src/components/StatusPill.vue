<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "@/lib/useI18n"

const props = defineProps<{
  status: string
}>()

const { t } = useI18n()
const statusLabel = computed(() => {
  const key = `status.${props.status}`
  const translated = t(key)
  return translated === key ? props.status : translated
})
</script>

<template>
  <span :class="['status-pill', `status-pill--${props.status}`]">{{ statusLabel }}</span>
</template>

<style scoped>
.status-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 4px 10px;
  border-radius: var(--tm-radius-sm, 8px);
  font-size: var(--tm-text-xs, 0.75rem);
  font-weight: 700;
  text-transform: capitalize;
  line-height: 1.4;
}

.status-pill--queued {
  background-color: var(--tm-warning-bg, rgba(212, 160, 84, 0.08));
  border: 1px solid var(--tm-warning-border, rgba(212, 160, 84, 0.12));
  color: var(--tm-warning, #D4A054);
}

.status-pill--running {
  background-color: var(--tm-info-bg, rgba(107, 157, 173, 0.08));
  border: 1px solid var(--tm-info-border, rgba(107, 157, 173, 0.12));
  color: var(--tm-info, #6B9DAD);
}

.status-pill--completed {
  background-color: var(--tm-success-bg, rgba(93, 122, 99, 0.08));
  border: 1px solid var(--tm-success-border, rgba(93, 122, 99, 0.12));
  color: var(--tm-success, #5D7A63);
}

.status-pill--draft {
  background-color: rgba(198, 183, 255, 0.08);
  border: 1px solid rgba(198, 183, 255, 0.12);
  color: #7B68AE;
}

.status-pill--failed {
  background-color: var(--tm-error-bg, rgba(199, 91, 74, 0.08));
  border: 1px solid var(--tm-error-border, rgba(199, 91, 74, 0.12));
  color: var(--tm-error, #C75B4A);
}
</style>