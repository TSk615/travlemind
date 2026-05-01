<script setup lang="ts">
import { computed } from "vue"
import { RouterLink, useRoute } from "vue-router"
import { brand } from "@travelmind/ui"
import { useI18n } from "@/lib/useI18n"
import { useAuthStore } from "@/stores/auth"
import { useJobGuardStore } from "@/stores/jobGuard"
import type { LocaleCode } from "@/lib/i18n"

const route = useRoute()
const auth = useAuthStore()
const jobGuard = useJobGuardStore()
const { locale, supportedLocales, setLocale, t } = useI18n()

const communityNavLabel = computed(() => (locale.value === "zh-CN" ? "攻略社区" : "Community"))
const settingsNavLabel = computed(() => (locale.value === "zh-CN" ? "模型设置" : "Model settings"))
const imageNavLabel = computed(() => (locale.value === "zh-CN" ? "AI 生图" : "AI Images"))
const backgroundJob = computed(() => jobGuard.activeJob)
const hasBackgroundJob = computed(() => jobGuard.hasActiveJob)
const showBackgroundJobBanner = computed(() => {
  if (!backgroundJob.value) {
    return false
  }
  return !(route.name === "trip-detail" && String(route.params.id ?? "") === backgroundJob.value.tripId)
})
const backgroundJobLabel = computed(() =>
  locale.value === "zh-CN"
    ? "行程任务正在后台继续执行"
    : "Trip task is still running in the background"
)
const backgroundJobMessage = computed(() => {
  if (!backgroundJob.value) {
    return ""
  }
  const stageMessage = backgroundJob.value.stageMessage?.trim()
  return stageMessage
    ? stageMessage
    : locale.value === "zh-CN"
      ? "你可以先去使用其他功能，稍后再回来看进度。"
      : "You can use other features now and return later to review the progress."
})
const backgroundJobTripLabel = computed(() => (locale.value === "zh-CN" ? "返回任务页" : "Back to trip"))
const backgroundJobRoute = computed(() => {
  if (!backgroundJob.value) {
    return { name: "trips" as const }
  }
  return {
    name: "trip-detail" as const,
    params: { id: backgroundJob.value.tripId },
    query: { jobId: backgroundJob.value.jobId }
  }
})

const currentSection = computed(() => {
  if (route.name === "trips" || route.name === "trip-new" || route.name === "trip-detail" || route.name === "export-detail") {
    return "trips"
  }

  if (route.name === "settings") {
    return "settings"
  }

  if (route.name === "images") {
    return "images"
  }

  if (route.name === "community" || route.name === "community-post") {
    return "community"
  }

  return route.name
})

function switchLocale(nextLocale: LocaleCode) {
  setLocale(nextLocale)
}
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <RouterLink class="brand" to="/">
        <span class="brand-mark">TM</span>
        <div>
          <strong>{{ brand.name }}</strong>
          <p>{{ t('layout.tagline') }}</p>
        </div>
      </RouterLink>

      <nav class="nav-links">
        <RouterLink :class="['nav-link', { current: currentSection === 'home' }]" to="/">{{ t('layout.nav.home') }}</RouterLink>
        <RouterLink :class="['nav-link', { current: currentSection === 'trips' }]" to="/trips">{{ t('layout.nav.trips') }}</RouterLink>
        <RouterLink :class="['nav-link', { current: route.name === 'trip-new' }]" to="/trips/new">{{ t('layout.nav.newTrip') }}</RouterLink>
        <RouterLink v-if="auth.user" :class="['nav-link', { current: currentSection === 'community' }]" to="/community">{{ communityNavLabel }}</RouterLink>
        <RouterLink v-if="auth.user" :class="['nav-link', { current: currentSection === 'images' }]" to="/images">{{ imageNavLabel }}</RouterLink>
        <RouterLink v-if="auth.user" :class="['nav-link', { current: currentSection === 'settings' }]" to="/settings">{{ settingsNavLabel }}</RouterLink>
      </nav>

      <div class="account-box">
        <div class="locale-switch" :aria-label="t('language.label')">
          <button
            v-for="option in supportedLocales"
            :key="option.code"
            type="button"
            :class="['locale-button', { 'locale-button--active': locale === option.code }]"
            @click="switchLocale(option.code)"
          >
            {{ option.shortLabel }}
          </button>
        </div>

        <template v-if="auth.bootstrapping">
          <p>{{ t('layout.checkingSession') }}</p>
        </template>
        <template v-else-if="auth.user">
          <div>
            <strong>{{ auth.user.name }}</strong>
            <p>{{ auth.user.email }}</p>
          </div>
          <button class="ghost-button" :disabled="auth.pending || hasBackgroundJob" @click="auth.logout">{{ t('layout.logOut') }}</button>
        </template>
        <RouterLink v-else class="solid-button" to="/login">{{ t('layout.signIn') }}</RouterLink>
      </div>
    </header>

    <div v-if="showBackgroundJobBanner" class="background-job-banner">
      <div>
        <strong>{{ backgroundJobLabel }}</strong>
        <p>{{ backgroundJobMessage }}</p>
      </div>
      <RouterLink class="button-link primary" :to="backgroundJobRoute">{{ backgroundJobTripLabel }}</RouterLink>
    </div>

    <main class="content-area">
      <slot />
    </main>
  </div>
</template>
