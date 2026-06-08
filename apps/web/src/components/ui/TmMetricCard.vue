<script setup lang="ts">
defineProps<{
  label: string
  value: string | number
  unit?: string
  trend?: "up" | "down" | "neutral"
}>()
</script>

<template>
  <article class="tm-metric-card">
    <p class="tm-metric-card__label">{{ label }}</p>
    <p class="tm-metric-card__value">
      <span class="tm-metric-card__number">{{ value }}</span>
      <span v-if="unit" class="tm-metric-card__unit">{{ unit }}</span>
    </p>
    <slot />
  </article>
</template>

<style scoped>
.tm-metric-card {
  display: flex;
  flex-direction: column;
  gap: var(--tm-space-2);
  padding: var(--tm-space-4) var(--tm-space-6);
  border-radius: var(--tm-radius-lg);
  background-color: var(--tm-snow);
  border: var(--tm-border-hairline);
  box-shadow: var(--tm-shadow-card);
}

.tm-metric-card__label {
  font-size: var(--tm-text-xs);
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--tm-clay);
  margin: 0;
}

.tm-metric-card__value {
  display: flex;
  align-items: baseline;
  gap: var(--tm-space-1);
  margin: 0;
}

.tm-metric-card__number {
  font-family: var(--tm-font-mono);
  font-size: var(--tm-text-xl);
  font-weight: 700;
  color: var(--tm-tea);
}

.tm-metric-card__unit {
  font-size: var(--tm-text-sm);
  color: var(--tm-stone);
}
</style>
