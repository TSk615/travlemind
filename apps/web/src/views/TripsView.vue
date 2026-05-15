<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import type { Trip } from "@travelmind/shared-types"
import LlmStatusNotice from "@/components/LlmStatusNotice.vue"
import StatePanel from "@/components/StatePanel.vue"
import { api, getErrorMessage } from "@/lib/api"
import { formatCurrency, formatDateRange } from "@/lib/format"
import { useI18n } from "@/lib/useI18n"

const trips = ref<Trip[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const pendingDeleteId = ref<string | null>(null)
const { locale, t } = useI18n()

const copy = computed(() => {
  if (locale.value === "zh-CN") {
    return {
      deleteTrip: "删除行程",
      deletingTrip: "删除中...",
      deleteConfirmMessage: "确认删除这条行程吗？该操作会同时移除关联任务记录。",
      deleteFailedTitle: "删除行程失败",
      sharedLabel: "已分享",
      staleLabel: "社区版本待更新"
    }
  }

  return {
    deleteTrip: "Delete trip",
    deletingTrip: "Deleting...",
    deleteConfirmMessage: "Delete this trip? Related job records will be removed as well.",
    deleteFailedTitle: "Failed to delete trip",
    sharedLabel: "Shared",
    staleLabel: "Community update needed"
  }
})

async function loadTrips() {
  loading.value = true
  error.value = null

  try {
    trips.value = await api.listTrips()
  } catch (value) {
    trips.value = []
    error.value = getErrorMessage(value, t("trips.unavailableTitle"))
  } finally {
    loading.value = false
  }
}

async function removeTrip(trip: Trip) {
  if (pendingDeleteId.value || !window.confirm(copy.value.deleteConfirmMessage)) {
    return
  }

  pendingDeleteId.value = trip.id
  error.value = null
  try {
    await api.deleteTrip(trip.id)
    trips.value = trips.value.filter((item) => item.id !== trip.id)
  } catch (value) {
    error.value = getErrorMessage(value, copy.value.deleteFailedTitle)
  } finally {
    pendingDeleteId.value = null
  }
}

function communityStatusText(trip: Trip): string | null {
  if (!trip.community_post) {
    return null
  }
  return trip.community_post.is_stale ? copy.value.staleLabel : copy.value.sharedLabel
}

onMounted(() => {
  void loadTrips()
})
</script>

<template>
  <section class="page-grid">
    <article class="panel">
      <div class="inline-actions" style="justify-content: space-between; align-items: center;">
        <div>
          <p class="kicker">{{ t("trips.kicker") }}</p>
          <h1>{{ t("trips.title") }}</h1>
        </div>
        <RouterLink class="solid-button" to="/trips/new">{{ t("common.createTrip") }}</RouterLink>
      </div>
      <p class="muted">{{ t("trips.description") }}</p>
    </article>

    <LlmStatusNotice compact />

    <StatePanel
      v-if="loading"
      kind="loading"
      :title="t('trips.loadingTitle')"
      :message="t('trips.loadingMessage')"
    />

    <StatePanel
      v-else-if="error"
      kind="error"
      :title="t('trips.unavailableTitle')"
      :message="error"
      :action-label="t('common.retry')"
      @action="loadTrips"
    />

    <StatePanel
      v-else-if="trips.length === 0"
      kind="empty"
      :title="t('trips.emptyTitle')"
      :message="t('trips.emptyMessage')"
    >
      <template #actions>
        <RouterLink class="button-link primary" to="/trips/new">{{ t("common.createTrip") }}</RouterLink>
      </template>
    </StatePanel>

    <div v-else class="card-grid">
      <article v-for="trip in trips" :key="trip.id" class="trip-card">
        <p class="kicker">{{ `${trip.origin} → ${trip.destination}` }}</p>
        <h3>{{ trip.title }}</h3>
        <p>{{ formatDateRange(trip.start_date, trip.end_date) }}</p>
        <p>{{ t("common.budgetValue", { value: formatCurrency(trip.budget) }) }} | {{ t("common.travelersCount", { count: trip.travelers }) }}</p>
        <p v-if="communityStatusText(trip)" class="trip-card__status">
          {{ communityStatusText(trip) }}
        </p>
        <p>{{ trip.itinerary?.summary ?? t("common.noItineraryYet") }}</p>
        <div class="inline-actions">
          <RouterLink class="button-link primary" :to="`/trips/${trip.id}`">{{ t("common.openTrip") }}</RouterLink>
          <button class="button-danger" type="button" :disabled="pendingDeleteId === trip.id" @click="removeTrip(trip)">
            {{ pendingDeleteId === trip.id ? copy.deletingTrip : copy.deleteTrip }}
          </button>
        </div>
      </article>
    </div>
  </section>
</template>
