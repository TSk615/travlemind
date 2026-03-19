<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "@/lib/useI18n"

const props = defineProps<{
  status: string
}>()

const { t } = useI18n()
const statusLabel = computed(() => {
  const key = `status.${props.status}`
  const translated = t(key)
  return translated === key ? props.status : translated
})
</script>

<template>
  <span :class="['status-pill', `status-pill--${props.status}`]">{{ statusLabel }}</span>
</template>