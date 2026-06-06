<script setup lang="ts">
import { computed } from "vue"

const props = withDefaults(
  defineProps<{
    value: number
    max?: number
    label?: string
    showPercentage?: boolean
    variant?: "default" | "aurora"
  }>(),
  {
    max: 100,
    label: "",
    showPercentage: true,
    variant: "default"
  }
)

const percentage = computed(() => Math.min(100, Math.max(0, (props.value / props.max) * 100)))
</script>

<template>
  <div class="tm-progress" role="progressbar" :aria-valuenow="props.value" :aria-valuemin="0" :aria-valuemax="props.max" :aria-label="props.label">
    <div v-if="props.label || props.showPercentage" class="tm-progress__header">
      <span v-if="props.label" class="tm-progress__label">{{ props.label }}</span>
      <span v-if="props.showPercentage" class="tm-progress__percentage">{{ Math.round(percentage) }}%</span>
    </div>
    <div class="tm-progress__track">
      <div
        :class="['tm-progress__fill', `tm-progress__fill--${props.variant}`]"
        :style="{ width: `${percentage}%` }"
      />
    </div>
  </div>
</template>

<style scoped>
.tm-progress {
  display: flex;
  flex-direction: column;
  gap: var(--tm-space-2);
}

.tm-progress__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.tm-progress__label {
  font-size: var(--tm-text-sm);
  font-weight: 600;
  color: var(--tm-tea);
}

.tm-progress__percentage {
  font-family: var(--tm-font-mono);
  font-size: var(--tm-text-sm);
  color: var(--tm-stone);
}

.tm-progress__track {
  width: 100%;
  height: 10px;
  border-radius: var(--tm-radius-full);
  background-color: var(--tm-mist);
  box-shadow: var(--tm-shadow-inset-sm);
  overflow: hidden;
}

.tm-progress__fill {
  height: 100%;
  border-radius: var(--tm-radius-full);
  transition: width var(--tm-duration-normal) var(--tm-ease-out);
}

.tm-progress__fill--default {
  background: linear-gradient(90deg, #5a9bff, var(--tm-moss), var(--tm-success));
}

.tm-progress__fill--aurora {
  background: linear-gradient(
    90deg,
    var(--tm-aurora-cyan),
    var(--tm-aurora-lilac),
    var(--tm-aurora-rose)
  );
  background-size: 200% 100%;
  animation: tm-progress-shimmer 2s linear infinite;
}

@keyframes tm-progress-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

@media (prefers-reduced-motion: reduce) {
  .tm-progress__fill--aurora {
    animation: none;
    background-size: 100% 100%;
  }
}
</style>
