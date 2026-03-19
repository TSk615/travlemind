<script setup lang="ts">
import { onMounted, ref } from "vue"
import type { Trip } from "@travelmind/shared-types"
import StatePanel from "@/components/StatePanel.vue"
import { api, getErrorMessage } from "@/lib/api"
import { formatCurrency, formatDateRange } from "@/lib/format"
import { useI18n } from "@/lib/useI18n"

const trips = ref<Trip[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const { t } = useI18n()

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

onMounted(() => {
  void loadTrips()
})
</script>

<template>
  <section class="page-grid">
    <article class="panel">
      <div class="inline-actions" style="justify-content: space-between; align-items: center;">
        <div>
          <p class="kicker">{{ t('trips.kicker') }}</p>
          <h1>{{ t('trips.title') }}</h1>
        </div>
        <RouterLink class="solid-button" to="/trips/new">{{ t('common.createTrip') }}</RouterLink>
      </div>
      <p class="muted">{{ t('trips.description') }}</p>
    </article>

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
        <RouterLink class="button-link primary" to="/trips/new">{{ t('common.createTrip') }}</RouterLink>
      </template>
    </StatePanel>

    <div v-else class="card-grid">
      <article v-for="trip in trips" :key="trip.id" class="trip-card">
        <p class="kicker">{{ trip.destination }}</p>
        <h3>{{ trip.title }}</h3>
        <p>{{ formatDateRange(trip.start_date, trip.end_date) }}</p>
        <p>{{ t('common.budgetValue', { value: formatCurrency(trip.budget) }) }} · {{ t('common.travelersCount', { count: trip.travelers }) }}</p>
        <p>{{ trip.itinerary?.summary ?? t('common.noItineraryYet') }}</p>
        <RouterLink class="button-link primary" :to="`/trips/${trip.id}`">{{ t('common.openTrip') }}</RouterLink>
      </article>
    </div>
  </section>
</template>