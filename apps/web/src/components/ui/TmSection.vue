<script setup lang="ts">
withDefaults(
  defineProps<{
    title?: string
    kicker?: string
    padded?: boolean
  }>(),
  {
    title: "",
    kicker: "",
    padded: true
  }
)
</script>

<template>
  <section :class="['tm-section', { 'tm-section--padded': padded }]">
    <header v-if="kicker || title" class="tm-section__header">
      <p v-if="kicker" class="tm-section__kicker">{{ kicker }}</p>
      <h2 v-if="title" class="tm-section__title">{{ title }}</h2>
    </header>
    <div class="tm-section__body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.tm-section {
  margin-bottom: var(--tm-space-12);
}

.tm-section--padded {
  padding: var(--tm-space-6);
}

.tm-section__header {
  margin-bottom: var(--tm-space-6);
}

.tm-section__kicker {
  font-size: var(--tm-text-xs);
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  color: var(--tm-clay);
  margin-bottom: var(--tm-space-1);
}

.tm-section__title {
  font-size: var(--tm-text-xl);
  font-weight: 700;
  color: var(--tm-tea);
}

.tm-section__body {
  display: grid;
  gap: var(--tm-space-4);
}
</style>
