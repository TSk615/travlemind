<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: "info" | "action" | "highlight"
    hoverable?: boolean
  }>(),
  {
    variant: "info",
    hoverable: false
  }
)
</script>

<template>
  <article :class="['tm-card', `tm-card--${variant}`, { 'tm-card--hoverable': hoverable }]">
    <slot />
  </article>
</template>

<style scoped>
.tm-card {
  border-radius: var(--tm-radius-lg);
  padding: var(--tm-space-6);
  transition:
    transform var(--tm-duration-fast) var(--tm-ease-out),
    box-shadow var(--tm-duration-fast) var(--tm-ease-out),
    background-color var(--tm-duration-fast) var(--tm-ease-out);
}

/* Info card */
.tm-card--info {
  background-color: var(--tm-snow);
  border: var(--tm-border-hairline);
  box-shadow: var(--tm-shadow-card);
}

/* Action card */
.tm-card--action {
  background-color: var(--tm-mist);
  border: var(--tm-border-subtle);
}

/* Highlight card (AI results) */
.tm-card--highlight {
  background: linear-gradient(135deg, rgba(93, 122, 99, 0.08), rgba(201, 143, 107, 0.06));
  border: var(--tm-border-subtle);
}

/* Hoverable */
.tm-card--hoverable:hover {
  transform: translateY(-2px);
  box-shadow: var(--tm-shadow-float);
}

.tm-card--action.tm-card--hoverable:hover {
  background-color: var(--tm-snow);
  box-shadow: var(--tm-shadow-raised-sm);
}

@media (max-width: 768px) {
  .tm-card {
    padding: var(--tm-space-4);
  }
}
</style>
