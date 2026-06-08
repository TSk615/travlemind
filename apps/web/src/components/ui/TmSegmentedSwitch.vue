<script setup lang="ts">
interface SegmentOption {
  value: string
  label: string
  icon?: string
}

const props = defineProps<{
  options: SegmentOption[]
  modelValue: string
}>()

const emit = defineEmits<{
  "update:modelValue": [value: string]
}>()

function select(value: string) {
  emit("update:modelValue", value)
}
</script>

<template>
  <div class="tm-segmented" role="radiogroup">
    <button
      v-for="option in props.options"
      :key="option.value"
      type="button"
      role="radio"
      :aria-checked="props.modelValue === option.value"
      :class="['tm-segmented__item', { 'tm-segmented__item--active': props.modelValue === option.value }]"
      @click="select(option.value)"
    >
      <span v-if="option.icon" class="tm-segmented__icon">{{ option.icon }}</span>
      <span class="tm-segmented__label">{{ option.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.tm-segmented {
  display: inline-flex;
  gap: 2px;
  padding: 4px;
  border-radius: var(--tm-radius-lg);
  background-color: var(--tm-mist);
  box-shadow: var(--tm-shadow-inset-sm);
}

.tm-segmented__item {
  display: inline-flex;
  align-items: center;
  gap: var(--tm-space-2);
  padding: var(--tm-space-2) var(--tm-space-4);
  border: none;
  border-radius: var(--tm-radius-md);
  background: transparent;
  color: var(--tm-stone);
  font-family: var(--tm-font-body);
  font-size: var(--tm-text-sm);
  font-weight: 600;
  cursor: pointer;
  transition:
    background-color var(--tm-duration-normal) var(--tm-ease-in-out),
    color var(--tm-duration-normal) var(--tm-ease-in-out),
    box-shadow var(--tm-duration-normal) var(--tm-ease-in-out);
  min-height: 36px;
}

.tm-segmented__item:hover:not(.tm-segmented__item--active) {
  color: var(--tm-tea);
  background-color: var(--tm-snow);
  box-shadow: var(--tm-shadow-raised-sm);
}

.tm-segmented__item--active {
  background-color: var(--tm-snow);
  color: var(--tm-moss);
  box-shadow: var(--tm-shadow-raised-sm);
}

.tm-segmented__item:focus-visible {
  outline: 0;
  box-shadow: var(--tm-shadow-raised-sm), var(--tm-focus-ring);
}

.tm-segmented__icon {
  font-size: var(--tm-text-base);
}

.tm-segmented__label {
  white-space: nowrap;
}
</style>
