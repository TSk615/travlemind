<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import type { Trip } from "@travelmind/shared-types"
import LlmStatusNotice from "@/components/LlmStatusNotice.vue"
import StatePanel from "@/components/StatePanel.vue"
import { api, getErrorMessage } from "@/lib/api"
import { formatCurrency, formatDateRange } from "@/lib/format"
import { getTripCover, portalAssets } from "@/lib/portalAssets"
import { filterTripCollection, getTripDayCount, type TripCollectionFilter } from "@/lib/tripCollection"
import { useI18n } from "@/lib/useI18n"

const trips = ref<Trip[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const operationError = ref<string | null>(null)
const pendingDeleteId = ref<string | null>(null)
const activeFilter = ref<TripCollectionFilter>("all")
const route = useRoute()
const router = useRouter()
const { locale, t } = useI18n()
const copy = computed(() => locale.value === "zh-CN" ? {
  title: "我的旅行", description: "每一个收藏，都可以成为下一次出发。", create: "＋ 新建行程",
  all: "全部行程", planning: "规划中", ready: "已生成", filters: "行程状态筛选",
  continue: "继续规划", revisit: "重温这段旅程", featureHint: "留一点空白，给路上的新发现。",
  collection: "把向往，慢慢收好", disclosure: "氛围封面为 AI 创作，非目的地实景",
  count: "段旅程", days: "天", people: "人", open: "打开行程", delete: "删除行程", deleting: "删除中…",
  deleteConfirm: "确认删除这条行程吗？该操作会同时移除关联任务记录。", deleteFailed: "删除行程失败",
  shared: "已分享", stale: "社区版本待更新", noMatches: "暂时没有找到这段旅程",
  noMatchesHint: "试试其他目的地、标题或兴趣，或者切换行程状态。", reset: "清除搜索与筛选",
  modelStatus: "模型状态与设置", modelHint: "生成前可在此检查模型配置"
} : {
  title: "My journeys", description: "Every saved thought can become your next departure.", create: "+ New journey",
  all: "All journeys", planning: "Planning", ready: "Generated", filters: "Filter journeys by status",
  continue: "Continue planning", revisit: "Revisit this journey", featureHint: "Leave a little room for the unexpected.",
  collection: "Keep a little wonder", disclosure: "AI mood covers, not photographs of these destinations",
  count: "journeys", days: "days", people: "travelers", open: "Open trip", delete: "Delete trip", deleting: "Deleting…",
  deleteConfirm: "Delete this trip? Related job records will be removed as well.", deleteFailed: "Failed to delete trip",
  shared: "Shared", stale: "Community update needed", noMatches: "No journeys found",
  noMatchesHint: "Try another destination, title, or interest, or change the status filter.", reset: "Clear search and filters",
  modelStatus: "Model status and settings", modelHint: "Check your model configuration before generating"
})
const searchQuery = computed(() => typeof route.query.q === "string" ? route.query.q : "")
const filteredTrips = computed(() => filterTripCollection(trips.value, searchQuery.value, activeFilter.value))
const featuredTrip = computed(() => filteredTrips.value.find((trip) => !trip.itinerary) ?? filteredTrips.value[0])
const filters = computed(() => [
  { value: "all" as const, label: copy.value.all },
  { value: "planning" as const, label: copy.value.planning },
  { value: "ready" as const, label: copy.value.ready }
])

async function loadTrips() {
  loading.value = true
  error.value = null
  try { trips.value = await api.listTrips() }
  catch (value) { trips.value = []; error.value = getErrorMessage(value, t("trips.unavailableTitle")) }
  finally { loading.value = false }
}
async function removeTrip(trip: Trip) {
  if (pendingDeleteId.value || !window.confirm(copy.value.deleteConfirm)) return
  pendingDeleteId.value = trip.id
  operationError.value = null
  try {
    await api.deleteTrip(trip.id)
    trips.value = trips.value.filter((item) => item.id !== trip.id)
  } catch (value) { operationError.value = getErrorMessage(value, copy.value.deleteFailed) }
  finally { pendingDeleteId.value = null }
}
function communityStatusText(trip: Trip): string | null {
  if (!trip.community_post) return null
  return trip.community_post.is_stale ? copy.value.stale : copy.value.shared
}
function resetFilters() {
  activeFilter.value = "all"
  void router.replace({ query: { ...route.query, q: undefined } })
}
onMounted(() => { void loadTrips() })
</script>

<template>
  <section class="studio-collection" aria-labelledby="collection-title">
    <header class="studio-collection__header">
      <div><h1 id="collection-title">{{ copy.title }}</h1><p>{{ copy.description }}</p></div>
      <RouterLink class="portal-button-link studio-create" to="/trips/new">{{ copy.create }}</RouterLink>
    </header>
    <div class="studio-filters" role="group" :aria-label="copy.filters">
      <button v-for="filter in filters" :key="filter.value" type="button" :aria-pressed="activeFilter === filter.value" :class="{ 'is-selected': activeFilter === filter.value }" @click="activeFilter = filter.value">{{ filter.label }}</button>
    </div>
    <StatePanel v-if="loading" kind="loading" :title="t('trips.loadingTitle')" :message="t('trips.loadingMessage')" />
    <StatePanel v-else-if="error" kind="error" :title="t('trips.unavailableTitle')" :message="error" :action-label="t('common.retry')" @action="loadTrips" />
    <StatePanel v-else-if="trips.length === 0" kind="empty" :title="t('trips.emptyTitle')" :message="t('trips.emptyMessage')">
      <template #actions><RouterLink class="portal-button-link" to="/trips/new">{{ copy.create }}</RouterLink></template>
    </StatePanel>
    <StatePanel v-else-if="filteredTrips.length === 0" kind="empty" :title="copy.noMatches" :message="copy.noMatchesHint" :action-label="copy.reset" @action="resetFilters" />
    <template v-else>
      <StatePanel v-if="operationError" kind="error" :title="copy.deleteFailed" :message="operationError" compact />
      <article v-if="featuredTrip" class="studio-feature">
        <div class="studio-feature__info">
          <p class="studio-feature__eyebrow">{{ featuredTrip.itinerary ? copy.revisit : copy.continue }} / {{ featuredTrip.destination }}</p>
          <h2>{{ featuredTrip.title }}</h2>
          <p class="studio-feature__summary">{{ featuredTrip.itinerary?.summary || copy.featureHint }}</p>
          <p class="studio-feature__meta">{{ formatDateRange(featuredTrip.start_date, featuredTrip.end_date) }} · {{ featuredTrip.travelers }} {{ copy.people }}</p>
          <RouterLink :to="`/trips/${featuredTrip.id}`">{{ copy.open }} <span aria-hidden="true">↗</span></RouterLink>
        </div>
        <img :src="portalAssets.forestFlow" alt="" width="960" height="640" class="studio-feature__image" />
      </article>
      <div class="studio-collection__subheading"><h2>{{ copy.collection }}</h2><p>{{ filteredTrips.length }} {{ copy.count }} <span aria-hidden="true">·</span> {{ copy.disclosure }}</p></div>
      <div class="studio-trip-grid">
        <article v-for="trip in filteredTrips" :key="trip.id" class="studio-trip-card">
          <RouterLink class="studio-trip-card__main" :to="`/trips/${trip.id}`" :aria-label="`${copy.open}：${trip.title}`">
            <div class="studio-trip-card__cover"><img :src="getTripCover(trip.id)" alt="" width="960" height="640" loading="lazy" decoding="async" /></div>
            <div class="studio-trip-card__caption">
              <p class="studio-trip-card__route">{{ trip.origin }} <span aria-hidden="true">→</span> {{ trip.destination }}</p>
              <h3 :title="trip.title">{{ trip.title }}</h3>
              <p class="studio-trip-card__date"><template v-if="getTripDayCount(trip)">{{ getTripDayCount(trip) }} {{ copy.days }} <span aria-hidden="true">·</span> </template>{{ formatDateRange(trip.start_date, trip.end_date) }}</p>
              <p class="studio-trip-card__budget">{{ formatCurrency(trip.budget) }} <span aria-hidden="true">·</span> {{ trip.travelers }} {{ copy.people }}</p>
            </div>
          </RouterLink>
          <div class="studio-trip-card__footer">
            <span class="studio-trip-status" :class="{ 'studio-trip-status--ready': !!trip.itinerary }">{{ trip.itinerary ? copy.ready : copy.planning }}</span>
            <span v-if="communityStatusText(trip)" class="studio-community-status">{{ communityStatusText(trip) }}</span>
            <button type="button" :disabled="!!pendingDeleteId" :aria-label="`${copy.delete}：${trip.title}`" @click="removeTrip(trip)">{{ pendingDeleteId === trip.id ? copy.deleting : copy.delete }}</button>
          </div>
        </article>
      </div>
    </template>
    <details class="studio-model-status"><summary>{{ copy.modelStatus }}<span>{{ copy.modelHint }}</span></summary><LlmStatusNotice compact /></details>
  </section>
</template>
