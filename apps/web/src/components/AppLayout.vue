<script setup lang="ts">
import { computed } from "vue"
import { RouterLink, useRoute } from "vue-router"
import { brand } from "@travelmind/ui"
import { useI18n } from "@/lib/useI18n"
import { useAuthStore } from "@/stores/auth"
import { useJobGuardStore } from "@/stores/jobGuard"
import TmToast from "@/components/ui/TmToast.vue"
import type { LocaleCode } from "@/lib/i18n"

const route = useRoute()
const auth = useAuthStore()
const jobGuard = useJobGuardStore()
const { locale, supportedLocales, setLocale, t } = useI18n()

const communityNavLabel = computed(() => (locale.value === "zh-CN" ? "攻略社区" : "Community"))
const settingsNavLabel = computed(() => (locale.value === "zh-CN" ? "模型设置" : "Settings"))
const imageNavLabel = computed(() => (locale.value === "zh-CN" ? "AI 生图" : "AI Images"))
const adminNavLabel = computed(() => "后台管理")
const backgroundJob = computed(() => jobGuard.activeJob)
const hasBackgroundJob = computed(() => jobGuard.hasActiveJob)
const showBackgroundJobBanner = computed(() => {
  if (!backgroundJob.value) {
    return false
  }
  return !(route.name === "trip-detail" && String(route.params.id ?? "") === backgroundJob.value.tripId)
})
const backgroundJobLabel = computed(() => {
  if (!backgroundJob.value) return ""
  const stageMessage = backgroundJob.value.stageMessage?.trim()
  if (stageMessage) return stageMessage
  return locale.value === "zh-CN"
    ? "行程任务正在后台执行..."
    : "Trip task running in background..."
})
const backgroundJobTripLabel = computed(() => (locale.value === "zh-CN" ? "查看" : "View"))
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
  if (route.name === "settings") return "settings"
  if (String(route.name ?? "").startsWith("admin-")) return "admin"
  if (route.name === "images") return "images"
  if (route.name === "community" || route.name === "community-post") return "community"
  return route.name
})

function switchLocale(nextLocale: LocaleCode) {
  setLocale(nextLocale)
}

function navigateToJob() {
  // handled by RouterLink in template
}
</script>

<template>
  <div class="tm-app-shell">
    <header class="tm-topbar">
      <!-- Brand -->
      <RouterLink class="tm-topbar__brand" to="/">
        <span class="tm-topbar__brand-mark">TM</span>
        <span class="tm-topbar__brand-name">{{ brand.name }}</span>
      </RouterLink>

      <!-- Navigation -->
      <nav class="tm-topbar__nav">
        <RouterLink :class="['tm-topbar__nav-item', { 'tm-topbar__nav-item--active': currentSection === 'home' }]" to="/">
          {{ t('layout.nav.home') }}
        </RouterLink>
        <RouterLink :class="['tm-topbar__nav-item', { 'tm-topbar__nav-item--active': currentSection === 'trips' }]" to="/trips">
          {{ t('layout.nav.trips') }}
        </RouterLink>
        <RouterLink :class="['tm-topbar__nav-item', { 'tm-topbar__nav-item--active': route.name === 'trip-new' }]" to="/trips/new">
          {{ t('layout.nav.newTrip') }}
        </RouterLink>
        <RouterLink v-if="auth.user" :class="['tm-topbar__nav-item', { 'tm-topbar__nav-item--active': currentSection === 'community' }]" to="/community">
          {{ communityNavLabel }}
        </RouterLink>
        <RouterLink v-if="auth.user" :class="['tm-topbar__nav-item', { 'tm-topbar__nav-item--active': currentSection === 'images' }]" to="/images">
          {{ imageNavLabel }}
        </RouterLink>
        <RouterLink v-if="auth.user" :class="['tm-topbar__nav-item', { 'tm-topbar__nav-item--active': currentSection === 'settings' }]" to="/settings">
          {{ settingsNavLabel }}
        </RouterLink>
        <RouterLink v-if="auth.user?.is_admin" :class="['tm-topbar__nav-item', { 'tm-topbar__nav-item--active': currentSection === 'admin' }]" to="/admin/users">
          {{ adminNavLabel }}
        </RouterLink>
      </nav>

      <!-- Tools -->
      <div class="tm-topbar__tools">
        <div class="tm-topbar__locale" :aria-label="t('language.label')">
          <button
            v-for="option in supportedLocales"
            :key="option.code"
            type="button"
            :class="['tm-topbar__locale-btn', { 'tm-topbar__locale-btn--active': locale === option.code }]"
            @click="switchLocale(option.code)"
          >
            {{ option.shortLabel }}
          </button>
        </div>

        <template v-if="auth.bootstrapping">
          <span class="tm-topbar__status">{{ t('layout.checkingSession') }}</span>
        </template>
        <template v-else-if="auth.user">
          <span class="tm-topbar__user">{{ auth.user.name }}</span>
          <button class="tm-topbar__logout" :disabled="auth.pending || hasBackgroundJob" @click="auth.logout">
            {{ t('layout.logOut') }}
          </button>
        </template>
        <RouterLink v-else class="tm-topbar__signin" to="/login">{{ t('layout.signIn') }}</RouterLink>
      </div>

      <!-- Mobile menu button (hidden on desktop) -->
      <button class="tm-topbar__hamburger" type="button" aria-label="Menu">
        <span></span><span></span><span></span>
      </button>
    </header>

    <!-- Background job toast -->
    <TmToast
      v-if="showBackgroundJobBanner"
      :message="backgroundJobLabel"
      :action-label="backgroundJobTripLabel"
      variant="info"
      :visible="true"
      @action="navigateToJob"
    />

    <!-- Main content -->
    <main class="tm-content">
      <slot />
    </main>
  </div>
</template>

<style scoped>
.tm-app-shell {
  min-height: 100vh;
  padding: var(--tm-space-6);
}

/* === Topbar === */
.tm-topbar {
  display: flex;
  align-items: center;
  gap: var(--tm-space-6);
  padding: var(--tm-space-4) var(--tm-space-6);
  border-radius: var(--tm-radius-2xl);
  border: var(--tm-border-subtle);
  background-color: rgba(232, 234, 237, 0.9);
  box-shadow: var(--tm-shadow-float);
  margin-bottom: var(--tm-space-4);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
}

/* Brand */
.tm-topbar__brand {
  display: flex;
  align-items: center;
  gap: var(--tm-space-3);
  text-decoration: none;
  flex-shrink: 0;
}

.tm-topbar__brand-mark {
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  border-radius: var(--tm-radius-md);
  background: linear-gradient(135deg, #5a9bff 0%, var(--tm-moss) 54%, #77d7a8 100%);
  color: white;
  font-weight: 800;
  font-size: var(--tm-text-sm);
  letter-spacing: 0.08em;
  box-shadow: var(--tm-shadow-primary);
}

.tm-topbar__brand-name {
  font-weight: 700;
  font-size: var(--tm-text-base);
  color: var(--tm-tea);
}

/* Navigation */
.tm-topbar__nav {
  display: flex;
  align-items: center;
  gap: var(--tm-space-1);
  flex: 1;
  justify-content: center;
  padding: var(--tm-space-1);
  border-radius: var(--tm-radius-full);
  background: rgba(216, 220, 227, 0.5);
  box-shadow: var(--tm-shadow-inset-sm);
}

.tm-topbar__nav-item {
  position: relative;
  padding: var(--tm-space-2) var(--tm-space-3);
  font-size: var(--tm-text-sm);
  font-weight: 500;
  color: var(--tm-stone);
  text-decoration: none;
  border-radius: var(--tm-radius-full);
  transition:
    color var(--tm-duration-fast) var(--tm-ease-out),
    background-color var(--tm-duration-fast) var(--tm-ease-out);
}

.tm-topbar__nav-item:hover {
  color: var(--tm-tea);
  background-color: var(--tm-snow);
  box-shadow: var(--tm-shadow-raised-sm);
}

.tm-topbar__nav-item--active {
  color: var(--tm-moss);
  background-color: var(--tm-paper);
  box-shadow: var(--tm-shadow-inset-sm);
}

.tm-topbar__nav-item--active::after {
  content: "";
  position: absolute;
  bottom: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 16px;
  height: 2px;
  border-radius: 1px;
  background-color: var(--tm-moss);
}

/* Tools */
.tm-topbar__tools {
  display: flex;
  align-items: center;
  gap: var(--tm-space-3);
  flex-shrink: 0;
}

.tm-topbar__locale {
  display: inline-flex;
  gap: 2px;
  padding: 4px;
  border-radius: var(--tm-radius-full);
  background-color: var(--tm-paper);
  box-shadow: var(--tm-shadow-inset-sm);
}

.tm-topbar__locale-btn {
  padding: var(--tm-space-1) var(--tm-space-2);
  border: none;
  border-radius: var(--tm-radius-full);
  background: transparent;
  font-size: var(--tm-text-xs);
  font-weight: 600;
  color: var(--tm-stone);
  cursor: pointer;
  transition: all var(--tm-duration-fast) var(--tm-ease-out);
}

.tm-topbar__locale-btn--active {
  background: linear-gradient(135deg, #5a9bff 0%, var(--tm-moss) 100%);
  color: white;
  box-shadow: var(--tm-shadow-primary);
}

.tm-topbar__user {
  font-size: var(--tm-text-sm);
  font-weight: 600;
  color: var(--tm-tea);
}

.tm-topbar__status {
  font-size: var(--tm-text-sm);
  color: var(--tm-stone);
}

.tm-topbar__logout {
  padding: var(--tm-space-1) var(--tm-space-3);
  border: 0;
  border-radius: var(--tm-radius-full);
  background: var(--tm-snow);
  box-shadow: var(--tm-shadow-raised-sm);
  font-size: var(--tm-text-xs);
  font-weight: 600;
  color: var(--tm-stone);
  cursor: pointer;
  transition: all var(--tm-duration-fast) var(--tm-ease-out);
}

.tm-topbar__logout:hover:not(:disabled) {
  color: var(--tm-tea);
  background-color: var(--tm-snow);
  box-shadow: var(--tm-shadow-raised-md);
}

.tm-topbar__logout:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.tm-topbar__signin {
  padding: var(--tm-space-2) var(--tm-space-4);
  border-radius: var(--tm-radius-full);
  background: linear-gradient(135deg, #5a9bff 0%, var(--tm-moss) 100%);
  color: white;
  font-size: var(--tm-text-sm);
  font-weight: 600;
  text-decoration: none;
  transition: all var(--tm-duration-fast) var(--tm-ease-out);
}

.tm-topbar__signin:hover {
  color: white;
  box-shadow: var(--tm-shadow-primary);
}

/* Hamburger (mobile only) */
.tm-topbar__hamburger {
  display: none;
  flex-direction: column;
  gap: 4px;
  padding: var(--tm-space-2);
  border: none;
  background: transparent;
  cursor: pointer;
}

.tm-topbar__hamburger span {
  display: block;
  width: 18px;
  height: 2px;
  background-color: var(--tm-tea);
  border-radius: 1px;
}

/* === Content === */
.tm-content {
  max-width: var(--tm-content-max-width);
  margin: 0 auto;
  padding-top: var(--tm-space-6);
}

/* === Responsive === */
@media (max-width: 768px) {
  .tm-app-shell {
    padding: var(--tm-space-3);
  }

  .tm-topbar {
    padding: var(--tm-space-3) var(--tm-space-4);
  }

  .tm-topbar__nav,
  .tm-topbar__tools {
    display: none;
  }

  .tm-topbar__hamburger {
    display: flex;
    margin-left: auto;
  }

  .tm-topbar__brand-name {
    font-size: var(--tm-text-sm);
  }
}

@media (max-width: 1024px) and (min-width: 769px) {
  .tm-topbar__nav-item {
    font-size: var(--tm-text-xs);
    padding: var(--tm-space-2) var(--tm-space-2);
  }
}
</style>
