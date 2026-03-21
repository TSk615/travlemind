<script setup lang="ts">
import { computed } from "vue"
import { RouterLink, useRoute } from "vue-router"
import { brand } from "@travelmind/ui"
import { useI18n } from "@/lib/useI18n"
import { useAuthStore } from "@/stores/auth"
import type { LocaleCode } from "@/lib/i18n"

const route = useRoute()
const auth = useAuthStore()
const { locale, supportedLocales, setLocale, t } = useI18n()

const settingsNavLabel = computed(() => (locale.value === "zh-CN" ? "模型设置" : "Model settings"))

const currentSection = computed(() => {
  if (route.name === "trips" || route.name === "trip-new" || route.name === "trip-detail" || route.name === "export-detail") {
    return "trips"
  }

  if (route.name === "settings") {
    return "settings"
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
          <button class="ghost-button" :disabled="auth.pending" @click="auth.logout">{{ t('layout.logOut') }}</button>
        </template>
        <RouterLink v-else class="solid-button" to="/login">{{ t('layout.signIn') }}</RouterLink>
      </div>
    </header>

    <main class="content-area">
      <slot />
    </main>
  </div>
</template>
