<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    message: string
    variant?: "hint" | "error" | "success"
  }>(),
  {
    variant: "hint"
  }
)
</script>

<template>
  <p :class="['tm-inline-hint', `tm-inline-hint--${props.variant}`]" :role="props.variant === 'error' ? 'alert' : undefined">
    {{ props.message }}
  </p>
</template>

<style scoped>
.tm-inline-hint {
  font-size: var(--tm-text-sm);
  line-height: var(--tm-leading-normal);
  margin-top: var(--tm-space-1);
}

.tm-inline-hint--hint {
  color: var(--tm-stone);
}

.tm-inline-hint--error {
  color: var(--tm-error);
}

.tm-inline-hint--success {
  color: var(--tm-success);
}
</style>
