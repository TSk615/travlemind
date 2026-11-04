<script setup lang="ts">
import { computed } from "vue"
import type { JobPresentationInput } from "@/lib/jobPresentation"
import { jobPresentation } from "@/lib/jobPresentation"
import TmProgressTrack from "@/components/ui/TmProgressTrack.vue"

const props = defineProps<{ job: JobPresentationInput; compact?: boolean }>()
const view = computed(() => jobPresentation(props.job))
</script>

<template>
  <div class="job-summary" :class="{ 'job-summary--compact': compact }" :data-job-state="job.status">
    <p class="job-summary__stage" role="status" aria-live="polite" aria-atomic="true">{{ view.label }}</p>
    <TmProgressTrack v-if="view.progress !== null && job.status !== 'failed' && job.status !== 'cancelled'" :value="view.progress" label="处理进度" :variant="job.status === 'running' || job.status === 'retrying' ? 'aurora' : 'default'" />
    <ul v-if="!compact && view.branches.length" class="job-summary__branches" aria-label="并行查询状态">
      <li v-for="branch in view.branches" :key="branch.name" :data-research-state="branch.status">
        <span>{{ branch.name }}</span><strong>{{ branch.statusLabel }}</strong>
      </li>
    </ul>
    <p v-if="!compact" class="job-summary__hint">{{ view.detail }}</p>
  </div>
</template>

<style scoped>
.job-summary { display: grid; gap: 14px; min-width: 0; padding-block: 10px; }
.job-summary__stage { margin: 0; color: var(--tm-tea, #244b39); font-size: 18px; font-weight: 600; line-height: 1.6; }
.job-summary__hint { margin: 0; color: var(--tm-stone, #5d6d64); font-size: 13px; line-height: 1.8; }
.job-summary__branches { display: flex; flex-wrap: wrap; gap: 12px; margin: 0; padding: 0; list-style: none; }
.job-summary__branches li { display: flex; gap: 12px; padding: 8px 14px; border: 1px solid var(--tm-border, #dce5df); border-radius: 12px; font-size: 13px; }
.job-summary__branches strong { color: var(--tm-tea, #244b39); font-weight: 500; }
.job-summary--compact { gap: 8px; width: 100%; }
.job-summary--compact .job-summary__stage { font-size: 14px; }
</style>
