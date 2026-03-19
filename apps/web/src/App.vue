<script setup lang="ts">
import { watchEffect } from "vue"
import { brand } from "@travelmind/ui"
import AppLayout from "@/components/AppLayout.vue"
import { useI18n } from "@/lib/useI18n"
import { useLocaleStore } from "@/stores/locale"

const localeStore = useLocaleStore()
localeStore.bootstrap()

const { t } = useI18n()

watchEffect(() => {
  if (typeof document !== "undefined") {
    document.title = `${brand.name} · ${t("meta.appTitle")}`
  }
})
</script>

<template>
  <AppLayout>
    <RouterView />
  </AppLayout>
</template>