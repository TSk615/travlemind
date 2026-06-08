<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from "vue"

interface AnchorItem {
  id: string
  label: string
}

const props = defineProps<{
  items: AnchorItem[]
}>()

const activeId = ref(props.items[0]?.id ?? "")

function scrollTo(id: string) {
  activeId.value = id
  const el = document.getElementById(id)
  if (el) {
    el.scrollIntoView({ behavior: "smooth", block: "start" })
  }
}

let observer: IntersectionObserver | null = null

onMounted(() => {
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          activeId.value = entry.target.id
        }
      }
    },
    { rootMargin: "-80px 0px -60% 0px", threshold: 0 }
  )
  for (const item of props.items) {
    const el = document.getElementById(item.id)
    if (el) observer.observe(el)
  }
})

onBeforeUnmount(() => {
  observer?.disconnect()
})
</script>

<template>
  <nav class="tm-anchor-nav" aria-label="Page sections">
    <button
      v-for="item in props.items"
      :key="item.id"
      type="button"
      :class="['tm-anchor-nav__item', { 'tm-anchor-nav__item--active': activeId === item.id }]"
      :aria-current="activeId === item.id ? 'true' : undefined"
      @click="scrollTo(item.id)"
    >
      {{ item.label }}
    </button>
  </nav>
</template>

<style scoped>
.tm-anchor-nav {
  display: flex;
  gap: var(--tm-space-1);
  padding: var(--tm-space-2) var(--tm-space-4);
  border-radius: var(--tm-radius-lg);
  background-color: var(--tm-snow);
  border: var(--tm-border-hairline);
  box-shadow: var(--tm-shadow-card);
  position: sticky;
  top: calc(var(--tm-topbar-height) + var(--tm-space-4));
  z-index: 10;
  overflow-x: auto;
  scrollbar-width: none;
}

.tm-anchor-nav::-webkit-scrollbar {
  display: none;
}

.tm-anchor-nav__item {
  flex-shrink: 0;
  padding: var(--tm-space-2) var(--tm-space-4);
  border: none;
  border-radius: var(--tm-radius-sm);
  background: transparent;
  color: var(--tm-stone);
  font-family: var(--tm-font-body);
  font-size: var(--tm-text-sm);
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition:
    color var(--tm-duration-fast) var(--tm-ease-out),
    background-color var(--tm-duration-fast) var(--tm-ease-out);
}

.tm-anchor-nav__item:hover {
  color: var(--tm-tea);
  background-color: var(--tm-mist);
}

.tm-anchor-nav__item--active {
  color: var(--tm-moss);
  background-color: rgba(93, 122, 99, 0.08);
}

.tm-anchor-nav__item:focus-visible {
  outline: 2px solid var(--tm-moss);
  outline-offset: 2px;
}
</style>
