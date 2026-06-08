<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    variant?: "primary" | "secondary" | "ghost" | "ai" | "danger"
    size?: "sm" | "md" | "lg"
    disabled?: boolean
    loading?: boolean
    type?: "button" | "submit" | "reset"
  }>(),
  {
    variant: "primary",
    size: "md",
    disabled: false,
    loading: false,
    type: "button"
  }
)

const emit = defineEmits<{
  click: [event: MouseEvent]
}>()

function handleClick(event: MouseEvent) {
  if (!props.disabled && !props.loading) {
    emit("click", event)
  }
}
</script>

<template>
  <button
    :type="props.type"
    :class="[
      'tm-btn',
      `tm-btn--${props.variant}`,
      `tm-btn--${props.size}`,
      { 'tm-btn--loading': props.loading }
    ]"
    :disabled="props.disabled || props.loading"
    @click="handleClick"
  >
    <span v-if="props.loading" class="tm-btn__spinner" aria-hidden="true"></span>
    <span class="tm-btn__content" :class="{ 'tm-btn__content--hidden': props.loading }">
      <slot />
    </span>
  </button>
</template>

<style scoped>
.tm-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--tm-space-2);
  border: none;
  border-radius: var(--tm-radius-md);
  font-family: var(--tm-font-body);
  font-weight: 600;
  cursor: pointer;
  transition:
    transform var(--tm-duration-fast) var(--tm-ease-out),
    box-shadow var(--tm-duration-fast) var(--tm-ease-out),
    background-color var(--tm-duration-fast) var(--tm-ease-out);
  position: relative;
  white-space: nowrap;
  min-height: 44px;
}

/* Sizes */
.tm-btn--sm {
  padding: var(--tm-space-2) var(--tm-space-3);
  font-size: var(--tm-text-sm);
  min-height: 36px;
}

.tm-btn--md {
  padding: var(--tm-space-3) var(--tm-space-6);
  font-size: var(--tm-text-base);
}

.tm-btn--lg {
  padding: var(--tm-space-4) var(--tm-space-8);
  font-size: var(--tm-text-lg);
}

/* Primary */
.tm-btn--primary {
  background: linear-gradient(135deg, #5a9bff 0%, var(--tm-moss) 100%);
  color: white;
  box-shadow: var(--tm-shadow-primary);
}

.tm-btn--primary:hover:not(:disabled) {
  transform: translateY(-1px);
  background: linear-gradient(135deg, #6ca6ff 0%, var(--tm-moss) 100%);
  color: white;
  filter: brightness(1.08);
  box-shadow: var(--tm-shadow-raised-md);
}

.tm-btn--primary:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: var(--tm-shadow-inset-sm);
}

/* Secondary */
.tm-btn--secondary {
  background-color: var(--tm-snow);
  color: var(--tm-tea);
  border: var(--tm-border-subtle);
  box-shadow: var(--tm-shadow-raised-sm);
}

.tm-btn--secondary:hover:not(:disabled) {
  transform: translateY(-1px);
  background-color: #ffffff;
  box-shadow: var(--tm-shadow-raised-md);
}

.tm-btn--secondary:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: var(--tm-shadow-inset-sm);
}

/* Ghost */
.tm-btn--ghost {
  background-color: transparent;
  color: var(--tm-tea);
}

.tm-btn--ghost:hover:not(:disabled) {
  background-color: var(--tm-snow);
  box-shadow: var(--tm-shadow-raised-sm);
}

.tm-btn--ghost:active:not(:disabled) {
  background-color: var(--tm-paper);
  box-shadow: var(--tm-shadow-inset-sm);
}

/* AI CTA */
.tm-btn--ai {
  background: linear-gradient(135deg, #5a9bff 0%, var(--tm-moss) 55%, var(--tm-clay) 100%);
  color: white;
  box-shadow:
    var(--tm-shadow-raised-sm),
    0 0 0 1px rgba(127, 228, 227, 0.3),
    0 0 12px rgba(127, 228, 227, 0.15);
}

.tm-btn--ai:hover:not(:disabled) {
  transform: translateY(-1px);
  background: linear-gradient(135deg, #6ca6ff 0%, var(--tm-moss) 55%, var(--tm-clay) 100%);
  color: white;
  filter: brightness(1.08);
  box-shadow:
    var(--tm-shadow-raised-md),
    0 0 0 1px rgba(127, 228, 227, 0.5),
    0 0 20px rgba(127, 228, 227, 0.2);
}

.tm-btn--ai:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: var(--tm-shadow-inset-sm);
}

/* Danger */
.tm-btn--danger {
  background-color: var(--tm-error);
  color: white;
  box-shadow: var(--tm-shadow-raised-sm);
}

.tm-btn--danger:hover:not(:disabled) {
  transform: translateY(-1px);
  background-color: var(--tm-error);
  color: white;
  filter: brightness(1.08);
  box-shadow: var(--tm-shadow-raised-md);
}

.tm-btn--danger:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: var(--tm-shadow-inset-sm);
}

/* Disabled */
.tm-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

/* Focus */
.tm-btn:focus-visible {
  outline: 0;
  box-shadow: var(--tm-shadow-primary), var(--tm-focus-ring);
}

/* Loading */
.tm-btn__spinner {
  position: absolute;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: currentColor;
  animation: tm-btn-spin 0.7s linear infinite;
}

.tm-btn__content--hidden {
  visibility: hidden;
}

@keyframes tm-btn-spin {
  to { transform: rotate(360deg); }
}
</style>
