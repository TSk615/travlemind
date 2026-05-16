<script setup lang="ts">
withDefaults(
  defineProps<{
    active?: boolean
    completed?: boolean
  }>(),
  {
    active: false,
    completed: false
  }
)
</script>

<template>
  <div
    :class="[
      'tm-aurora-panel',
      { 'tm-aurora-panel--active': active, 'tm-aurora-panel--completed': completed }
    ]"
    :aria-live="active ? 'polite' : undefined"
  >
    <slot />
  </div>
</template>

<style scoped>
.tm-aurora-panel {
  position: relative;
  padding: var(--tm-space-6);
  border-radius: var(--tm-radius-xl);
  background-color: var(--tm-snow);
  border: 1px solid rgba(43, 42, 40, 0.08);
  box-shadow: var(--tm-shadow-card);
  transition:
    border-color var(--tm-duration-normal) var(--tm-ease-in-out),
    box-shadow var(--tm-duration-normal) var(--tm-ease-in-out);
}

/* Active state — AI is working */
.tm-aurora-panel--active {
  border-color: transparent;
  background-image: none;
  box-shadow:
    var(--tm-shadow-card),
    0 0 0 1px var(--tm-aurora-cyan),
    0 0 16px rgba(127, 228, 227, 0.1);
  animation: tm-aurora-border 3s linear infinite;
}

.tm-aurora-panel--active::before {
  content: "";
  position: absolute;
  inset: -1px;
  border-radius: inherit;
  padding: 1px;
  background: linear-gradient(
    135deg,
    var(--tm-aurora-cyan),
    var(--tm-aurora-lilac),
    var(--tm-aurora-rose),
    var(--tm-aurora-cyan)
  );
  background-size: 300% 300%;
  animation: tm-aurora-gradient 3s linear infinite;
  mask:
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  mask-composite: exclude;
  -webkit-mask:
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  pointer-events: none;
}

/* Completed state — brief success flash */
.tm-aurora-panel--completed {
  border-color: var(--tm-success);
  box-shadow:
    var(--tm-shadow-card),
    0 0 0 1px var(--tm-success),
    0 0 12px rgba(93, 122, 99, 0.15);
  animation: tm-aurora-complete 0.5s var(--tm-ease-out) forwards;
}

@keyframes tm-aurora-gradient {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}

@keyframes tm-aurora-border {
  0%, 100% { box-shadow: var(--tm-shadow-card), 0 0 0 1px var(--tm-aurora-cyan), 0 0 16px rgba(127, 228, 227, 0.1); }
  33% { box-shadow: var(--tm-shadow-card), 0 0 0 1px var(--tm-aurora-lilac), 0 0 16px rgba(198, 183, 255, 0.1); }
  66% { box-shadow: var(--tm-shadow-card), 0 0 0 1px var(--tm-aurora-rose), 0 0 16px rgba(244, 194, 215, 0.1); }
}

@keyframes tm-aurora-complete {
  0% { box-shadow: var(--tm-shadow-card), 0 0 0 2px var(--tm-success), 0 0 20px rgba(93, 122, 99, 0.2); }
  100% { box-shadow: var(--tm-shadow-card), 0 0 0 1px rgba(93, 122, 99, 0.2), 0 0 0 rgba(93, 122, 99, 0); }
}

@media (prefers-reduced-motion: reduce) {
  .tm-aurora-panel--active,
  .tm-aurora-panel--active::before,
  .tm-aurora-panel--completed {
    animation: none;
  }
  .tm-aurora-panel--active {
    border-color: var(--tm-aurora-cyan);
  }
}
</style>
