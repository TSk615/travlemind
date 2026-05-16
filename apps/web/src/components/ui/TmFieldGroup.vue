<script setup lang="ts">
import { ref } from "vue"

const props = withDefaults(
  defineProps<{
    title: string
    collapsible?: boolean
    defaultOpen?: boolean
  }>(),
  {
    collapsible: true,
    defaultOpen: true
  }
)

const isOpen = ref(props.defaultOpen)

function toggle() {
  if (props.collapsible) {
    isOpen.value = !isOpen.value
  }
}
</script>

<template>
  <fieldset class="tm-field-group" :class="{ 'tm-field-group--collapsed': !isOpen }">
    <legend class="tm-field-group__legend" @click="toggle">
      <span class="tm-field-group__title">{{ props.title }}</span>
      <span v-if="props.collapsible" class="tm-field-group__chevron" aria-hidden="true">
        {{ isOpen ? '▾' : '▸' }}
      </span>
    </legend>
    <div v-show="isOpen" class="tm-field-group__content">
      <slot />
    </div>
  </fieldset>
</template>

<style scoped>
.tm-field-group {
  border: none;
  padding: 0;
  margin: 0 0 var(--tm-space-8) 0;
}

.tm-field-group__legend {
  display: flex;
  align-items: center;
  gap: var(--tm-space-2);
  width: 100%;
  padding: var(--tm-space-3) 0;
  border-bottom: var(--tm-border-subtle);
  cursor: pointer;
  user-select: none;
  margin-bottom: var(--tm-space-4);
}

.tm-field-group__title {
  font-size: var(--tm-text-sm);
  font-weight: 700;
  color: var(--tm-moss);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.tm-field-group__chevron {
  color: var(--tm-stone);
  font-size: var(--tm-text-xs);
  transition: transform var(--tm-duration-normal) var(--tm-ease-in-out);
}

.tm-field-group__content {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--tm-space-4);
}

@media (max-width: 768px) {
  .tm-field-group__content {
    grid-template-columns: 1fr;
  }
}
</style>
