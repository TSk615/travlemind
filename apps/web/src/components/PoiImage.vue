<script setup lang="ts">
import { computed, ref, watch } from "vue"
const props = defineProps<{ urls: string[]; backups?: string[]; alt: string }>()
const index = ref(0)
const candidates = computed(() => [...new Set([...props.urls, ...(props.backups ?? [])])])
watch(() => candidates.value.join("|"), () => { index.value = 0 })
</script>

<template>
  <img v-if="index < candidates.length" :src="candidates[index]" :alt="alt"
    loading="lazy" referrerpolicy="no-referrer" @error="index += 1" />
  <span v-else class="poi-image-empty">景点图片暂不可用</span>
</template>

<style scoped>
.poi-image-empty { display: grid; place-items: center; min-height: 140px; color: #777; background: #f5f5f5; }
</style>
