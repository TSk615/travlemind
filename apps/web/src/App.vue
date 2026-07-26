<script setup lang="ts">
import { computed, watch, watchEffect } from "vue"
import { useRoute, useRouter, type RouteLocationNormalizedLoaded } from "vue-router"
import { brand } from "@travelmind/ui"
import AppLayout from "@/components/AppLayout.vue"
import { clearUnauthorizedSessionNotice, useUnauthorizedSessionState } from "@/lib/authSession"
import { useI18n } from "@/lib/useI18n"
import { useAuthStore } from "@/stores/auth"
import { useJobGuardStore } from "@/stores/jobGuard"
import { useLocaleStore } from "@/stores/locale"

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const jobGuard = useJobGuardStore()
const localeStore = useLocaleStore()
const sessionState = useUnauthorizedSessionState()
localeStore.bootstrap()

const { locale, t } = useI18n()
const usePlainShell = computed(() => Boolean(route.meta.plainShell))

function routeCacheKey(viewRoute: RouteLocationNormalizedLoaded) {
  const cacheScope = auth.user?.email ?? "guest"

  if (viewRoute.name === "trip-detail") {
    return `${cacheScope}:trip-detail:${String(viewRoute.params.id ?? "")}`
  }

  if (viewRoute.name === "images") {
    return `${cacheScope}:images`
  }

  return `${cacheScope}:${String(viewRoute.name ?? viewRoute.path)}`
}

const sessionExpiredMessage = computed(() =>
  locale.value === "zh-CN"
    ? "登录状态已失效，请重新登录后继续操作。"
    : "Your session has expired. Sign in again to continue."
)

watchEffect(() => {
  if (typeof document !== "undefined") {
    document.title = `${brand.name} 路 ${t("meta.appTitle")}`
  }
})

watch(
  () => sessionState.version,
  async (version) => {
    if (version === 0 || !sessionState.active) {
      return
    }

    const redirect = route.name === "login" ? (typeof route.query.redirect === "string" ? route.query.redirect : "/trips") : route.fullPath

    auth.invalidateSession()
    jobGuard.clearActiveJob()

    try {
      if (typeof window !== "undefined" && route.name !== "login") {
        window.alert(sessionExpiredMessage.value)
      }

      if (route.name !== "login") {
        await router.push({
          name: "login",
          query: {
            redirect,
            reason: "expired"
          }
        })
      }
    } finally {
      clearUnauthorizedSessionNotice()
    }
  }
)
</script>

<template>
  <RouterView v-if="usePlainShell" />
  <AppLayout v-else>
    <RouterView v-slot="{ Component, route: viewRoute }">
      <KeepAlive>
        <component
          :is="Component"
          v-if="viewRoute.meta.keepAlive"
          :key="routeCacheKey(viewRoute)"
        />
      </KeepAlive>
      <component
        :is="Component"
        v-if="!viewRoute.meta.keepAlive"
        :key="routeCacheKey(viewRoute)"
      />
    </RouterView>
  </AppLayout>
</template>
