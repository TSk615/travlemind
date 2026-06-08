<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    label: string
    size?: "sm" | "md" | "lg"
    disabled?: boolean
  }>(),
  {
    size: "md",
    disabled: false
  }
)

const emit = defineEmits<{
  click: [event: MouseEvent]
}>()
</script>

<template>
  <button
    type="button"
    :class="['tm-icon-btn', `tm-icon-btn--${props.size}`]"
    :disabled="props.disabled"
    :aria-label="props.label"
    :title="props.label"
    @click="emit('click', $event)"
  >
    <slot />
  </button>
</template>

<style scoped>
.tm-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--tm-radius-md);
  background-color: transparent;
  color: var(--tm-stone);
  cursor: pointer;
  transition:
    background-color var(--tm-duration-fast) var(--tm-ease-out),
    color var(--tm-duration-fast) var(--tm-ease-out),
    box-shadow var(--tm-duration-fast) var(--tm-ease-out);
}

.tm-icon-btn--sm {
  width: 32px;
  height: 32px;
  font-size: var(--tm-text-sm);
}

.tm-icon-btn--md {
  width: 44px;
  height: 44px;
  font-size: var(--tm-text-base);
}

.tm-icon-btn--lg {
  width: 52px;
  height: 52px;
  font-size: var(--tm-text-lg);
}

.tm-icon-btn:hover:not(:disabled) {
  background-color: var(--tm-mist);
  color: var(--tm-tea);
  box-shadow: var(--tm-shadow-raised-sm);
}

.tm-icon-btn:active:not(:disabled) {
  box-shadow: var(--tm-shadow-inset-sm);
}

.tm-icon-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.tm-icon-btn:focus-visible {
  outline: 2px solid var(--tm-moss);
  outline-offset: 2px;
}
</style>
