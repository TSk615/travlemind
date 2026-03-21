<script setup lang="ts">
import { computed, watchEffect } from "vue"
import { useRoute } from "vue-router"
import { brand } from "@travelmind/ui"
import AppLayout from "@/components/AppLayout.vue"
import { useI18n } from "@/lib/useI18n"
import { useLocaleStore } from "@/stores/locale"

const route = useRoute()
const localeStore = useLocaleStore()
localeStore.bootstrap()

const { t } = useI18n()
const usePlainShell = computed(() => Boolean(route.meta.plainShell))

watchEffect(() => {
  if (typeof document !== "undefined") {
    document.title = `${brand.name} · ${t("meta.appTitle")}`
  }
})
</script>

<template>
  <RouterView v-if="usePlainShell" />
  <AppLayout v-else>
    <RouterView />
  </AppLayout>
</template>