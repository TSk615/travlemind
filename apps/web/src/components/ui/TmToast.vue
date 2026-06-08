<script setup lang="ts">
withDefaults(
  defineProps<{
    message: string
    actionLabel?: string
    variant?: "info" | "success" | "warning"
    visible?: boolean
  }>(),
  {
    actionLabel: "",
    variant: "info",
    visible: true
  }
)

const emit = defineEmits<{
  action: []
  dismiss: []
}>()
</script>

<template>
  <Transition name="tm-toast">
    <div v-if="visible" :class="['tm-toast', `tm-toast--${variant}`]" role="status" aria-live="polite">
      <span class="tm-toast__message">{{ message }}</span>
      <div class="tm-toast__actions">
        <button v-if="actionLabel" type="button" class="tm-toast__action" @click="emit('action')">
          {{ actionLabel }}
        </button>
        <button type="button" class="tm-toast__dismiss" aria-label="Dismiss" @click="emit('dismiss')">
          &times;
        </button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.tm-toast {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--tm-space-4);
  padding: var(--tm-space-3) var(--tm-space-6);
  border-radius: var(--tm-radius-lg);
  font-size: var(--tm-text-sm);
  max-height: 48px;
  overflow: hidden;
}

.tm-toast--info {
  background-color: var(--tm-info-bg);
  border: 1px solid var(--tm-info-border);
  color: var(--tm-info);
}

.tm-toast--success {
  background-color: var(--tm-success-bg);
  border: 1px solid var(--tm-success-border);
  color: var(--tm-success);
}

.tm-toast--warning {
  background-color: var(--tm-warning-bg);
  border: 1px solid var(--tm-warning-border);
  color: var(--tm-warning);
}

.tm-toast__message {
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tm-toast__actions {
  display: flex;
  align-items: center;
  gap: var(--tm-space-2);
  flex-shrink: 0;
}

.tm-toast__action {
  padding: var(--tm-space-1) var(--tm-space-3);
  border: none;
  border-radius: var(--tm-radius-sm);
  background: currentColor;
  color: white;
  font-size: var(--tm-text-xs);
  font-weight: 700;
  cursor: pointer;
  opacity: 0.9;
}

.tm-toast__action:hover {
  opacity: 1;
}

.tm-toast__dismiss {
  padding: 0;
  border: none;
  background: transparent;
  color: currentColor;
  font-size: var(--tm-text-lg);
  cursor: pointer;
  opacity: 0.6;
  line-height: 1;
}

.tm-toast__dismiss:hover {
  opacity: 1;
}

/* Transition */
.tm-toast-enter-active,
.tm-toast-leave-active {
  transition:
    opacity var(--tm-duration-normal) var(--tm-ease-in-out),
    transform var(--tm-duration-normal) var(--tm-ease-in-out);
}

.tm-toast-enter-from,
.tm-toast-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
