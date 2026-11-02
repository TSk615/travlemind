<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { RouterLink, useRoute, useRouter } from "vue-router"
import { brand } from "@travelmind/ui"
import { useI18n } from "@/lib/useI18n"
import { portalAssets } from "@/lib/portalAssets"
import { useAuthStore } from "@/stores/auth"
import { useJobGuardStore } from "@/stores/jobGuard"
import TmToast from "@/components/ui/TmToast.vue"

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const jobGuard = useJobGuardStore()
const { t, locale } = useI18n()
const mobileMenuOpen = ref(false)
const isLanding = computed(() => route.name === "home")
const isStudio = computed(() => route.name === "trips")
const copy = computed(() => locale.value === "zh-CN" ? {
  discover: "发现灵感", studio: "旅行空间", community: "攻略社区", trips: "我的行程",
  newTrip: "新建行程", settings: "模型设置", admin: "后台管理", enter: "进入旅行空间",
  search: "搜索行程或目的地", clear: "清空搜索", menu: "打开导航菜单", close: "关闭导航菜单",
  navigation: "主导航", workspace: "旅行空间导航", main: "跳到主要内容", user: "账户", home: "返回首页"
} : {
  discover: "Discover", studio: "Travel studio", community: "Community", trips: "My journeys",
  newTrip: "New journey", settings: "Model settings", admin: "Administration", enter: "Enter travel studio",
  search: "Search journeys or destinations", clear: "Clear search", menu: "Open navigation", close: "Close navigation",
  navigation: "Main navigation", workspace: "Travel studio navigation", main: "Skip to content", user: "Account", home: "Back home"
})
const publicLinks = computed(() => [
  { to: "/", label: copy.value.discover },
  { to: "/trips", label: copy.value.studio },
  { to: "/community", label: copy.value.community }
])
const workspaceLinks = computed(() => [
  { to: "/trips", label: copy.value.trips },
  { to: "/trips/new", label: copy.value.newTrip },
  { to: "/", label: copy.value.discover },
  { to: "/community", label: copy.value.community }
])
const studioQuery = computed({
  get: () => typeof route.query.q === "string" ? route.query.q : "",
  set: (value: string) => { void router.replace({ query: { ...route.query, q: value || undefined } }) }
})
const backgroundJob = computed(() => jobGuard.activeJob)
const showBackgroundJobBanner = computed(() => Boolean(backgroundJob.value) &&
  !(route.name === "trip-detail" && String(route.params.id ?? "") === backgroundJob.value?.tripId))
const backgroundJobLabel = computed(() => backgroundJob.value?.stageMessage?.trim() || "行程任务正在后台执行…")

function navigateToJob() {
  const job = backgroundJob.value
  if (job) void router.push({ name: "trip-detail", params: { id: job.tripId }, query: { jobId: job.jobId } })
}
async function logout() {
  try { await auth.logout() } catch { /* The auth store already clears the local session on failure. */ }
  finally { void router.push("/") }
}
watch(() => route.fullPath, () => {
  mobileMenuOpen.value = false
  if (auth.user?.generation_quota) void auth.refreshUser()
})
watch(() => jobGuard.activeJob?.jobId, () => {
  if (auth.user?.generation_quota) void auth.refreshUser()
})
</script>

<template>
  <div class="tm-app-shell" :class="{ 'tm-app-shell--landing': isLanding, 'tm-app-shell--studio': isStudio, 'tm-app-shell--standard': !isLanding && !isStudio }" @keydown.esc="mobileMenuOpen = false">
    <a class="tm-skip-link" href="#main-content">{{ copy.main }}</a>
    <div class="tm-shell-window">
      <header class="tm-topbar">
        <RouterLink class="tm-brand" to="/" :aria-label="`${brand.name} · ${copy.home}`">
          <img :src="portalAssets.brandMark" alt="" width="28" height="28" />
          <span>TravelMind</span>
        </RouterLink>
        <div v-if="isStudio" class="tm-studio-search">
          <label class="tm-sr-only" for="studio-search">{{ copy.search }}</label>
          <input id="studio-search" v-model="studioQuery" type="search" :placeholder="copy.search" autocomplete="off" />
          <button v-if="studioQuery" class="tm-search-clear" type="button" :aria-label="copy.clear" @click="studioQuery = ''">×</button>
        </div>
        <nav v-else class="tm-topbar__nav" :aria-label="copy.navigation">
          <RouterLink v-for="link in publicLinks" :key="link.to" :to="link.to" :aria-current="route.path === link.to ? 'page' : undefined">{{ link.label }}</RouterLink>
          <RouterLink v-if="auth.user && !isLanding" to="/settings">{{ copy.settings }}</RouterLink>
          <RouterLink v-if="auth.user?.is_admin && !isLanding" to="/admin">{{ copy.admin }}</RouterLink>
        </nav>
        <div class="tm-topbar__account">
          <span v-if="auth.bootstrapping" class="tm-account-status">{{ t('layout.checkingSession') }}</span>
          <template v-else-if="auth.user">
            <RouterLink class="tm-user-pill" to="/settings" :aria-label="`${copy.user} · ${auth.user.name}`">{{ auth.user.name }}</RouterLink>
            <button class="tm-logout" type="button" :disabled="auth.pending || jobGuard.hasActiveJob" @click="logout">{{ t('layout.logOut') }}</button>
          </template>
          <RouterLink v-else class="tm-entry-link" :to="isLanding ? '/trips' : '/login'">{{ isLanding ? copy.enter : t('layout.signIn') }} <span aria-hidden="true">↗</span></RouterLink>
        </div>
        <button class="tm-menu-toggle" type="button" aria-controls="tm-mobile-navigation" :aria-expanded="mobileMenuOpen" :aria-label="mobileMenuOpen ? copy.close : copy.menu" @click="mobileMenuOpen = !mobileMenuOpen">
          {{ mobileMenuOpen ? (locale === 'zh-CN' ? '关闭' : 'Close') : (locale === 'zh-CN' ? '菜单' : 'Menu') }}
          <span aria-hidden="true">{{ mobileMenuOpen ? '−' : '＋' }}</span>
        </button>
        <nav v-if="mobileMenuOpen" id="tm-mobile-navigation" class="tm-mobile-nav" :aria-label="copy.navigation">
          <RouterLink v-for="link in workspaceLinks" :key="link.to" :to="link.to" :aria-current="route.path === link.to ? 'page' : undefined">{{ link.label }}</RouterLink>
          <RouterLink v-if="auth.user" to="/settings">{{ copy.settings }}</RouterLink>
          <RouterLink v-if="auth.user?.is_admin" to="/admin">{{ copy.admin }}</RouterLink>
          <button v-if="auth.user" type="button" :disabled="auth.pending || jobGuard.hasActiveJob" @click="logout">{{ t('layout.logOut') }}</button>
          <RouterLink v-else to="/login">{{ t('layout.signIn') }}</RouterLink>
        </nav>
      </header>
      <div v-if="auth.user?.generation_quota" class="tm-demo-quota" role="status">
        <template v-if="locale === 'zh-CN'">
          公开体验账户 · 剩余 {{ auth.user.generation_quota.remaining }} / {{ auth.user.generation_quota.limit }} 次
          · 所有访客共享，重新生成 / AI 调整 / 手动重试均计次。请勿填写个人隐私，已有行程对其他访客可见。
        </template>
        <template v-else>
          Public demo · {{ auth.user.generation_quota.remaining }} / {{ auth.user.generation_quota.limit }} remaining.
          Shared by all visitors; regeneration, AI refinement and manual retries count. Do not enter private information.
        </template>
      </div>
      <div class="tm-shell-body">
        <aside v-if="isStudio" class="tm-sidebar" :aria-label="copy.workspace">
          <nav class="tm-sidebar__primary" :aria-label="copy.workspace">
            <RouterLink v-for="link in workspaceLinks" :key="link.to" :to="link.to" :class="{ 'is-active': route.path === link.to }" :aria-current="route.path === link.to ? 'page' : undefined">{{ link.label }}</RouterLink>
          </nav>
          <nav class="tm-sidebar__secondary" :aria-label="copy.settings">
            <RouterLink to="/settings">{{ copy.settings }}</RouterLink>
            <RouterLink v-if="auth.user?.is_admin" to="/admin">{{ copy.admin }}</RouterLink>
            <RouterLink to="/">{{ copy.home }} <span aria-hidden="true">↗</span></RouterLink>
          </nav>
        </aside>
        <main id="main-content" class="tm-content" tabindex="-1">
          <div v-if="showBackgroundJobBanner" class="tm-background-job">
            <TmToast :message="backgroundJobLabel" :action-label="locale === 'zh-CN' ? '查看行程' : 'View journey'" variant="info" @action="navigateToJob" />
          </div>
          <slot />
        </main>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tm-demo-quota { padding: 12px 24px; background: #eef5ee; color: #244b39; border-bottom: 1px solid #d4e2d5; font-size: 13px; line-height: 1.7; }
</style>
