<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue"
import type { CommunityPostDetail, ItineraryItem } from "@travelmind/shared-types"
import StatePanel from "@/components/StatePanel.vue"
import { api, getErrorMessage } from "@/lib/api"
import { formatCurrency, formatDateRange, formatDateTime } from "@/lib/format"
import { useI18n } from "@/lib/useI18n"

const props = defineProps<{
  id: string
}>()

const post = ref<CommunityPostDetail | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const { locale } = useI18n()

const copy = computed(() =>
  locale.value === "zh-CN"
    ? {
        loadingTitle: "正在加载攻略",
        loadingMessage: "获取这篇社区攻略的只读快照。",
        unavailableTitle: "攻略详情暂时不可用",
        summaryTitle: "攻略概览",
        shareNoteTitle: "作者心得",
        itineraryTitle: "每日安排",
        risksTitle: "风险提示",
        authorLabel: "作者",
        publishedLabel: "发布时间",
        updatedLabel: "最近更新",
        budgetLabel: "预算",
        travelersLabel: "出行人数",
        paceLabel: "节奏",
        transportLabel: "交通",
        accommodationLabel: "住宿偏好",
        retry: "重试",
        noRisks: "当前快照没有附带风险提示。"
      }
    : {
        loadingTitle: "Loading community post",
        loadingMessage: "Fetching the read-only trip snapshot for this community post.",
        unavailableTitle: "Community post unavailable",
        summaryTitle: "Trip summary",
        shareNoteTitle: "Author note",
        itineraryTitle: "Daily itinerary",
        risksTitle: "Risk notes",
        authorLabel: "Author",
        publishedLabel: "Published",
        updatedLabel: "Updated",
        budgetLabel: "Budget",
        travelersLabel: "Travelers",
        paceLabel: "Pace",
        transportLabel: "Transport",
        accommodationLabel: "Stay preference",
        retry: "Retry",
        noRisks: "No risk notes were attached to this snapshot."
      }
)

const snapshot = computed(() => post.value?.snapshot ?? null)
const itineraryMetrics = computed(() => {
  if (!snapshot.value) {
    return []
  }
  return [
    { label: copy.value.budgetLabel, value: formatCurrency(snapshot.value.budget) },
    { label: copy.value.travelersLabel, value: String(snapshot.value.travelers) },
    { label: copy.value.paceLabel, value: snapshot.value.pace },
    { label: copy.value.transportLabel, value: snapshot.value.transport_mode }
  ]
})

async function loadPost() {
  loading.value = true
  error.value = null
  try {
    post.value = await api.getCommunityPost(String(props.id ?? ""))
  } catch (value) {
    post.value = null
    error.value = getErrorMessage(value, copy.value.unavailableTitle)
  } finally {
    loading.value = false
  }
}

function itemTimeRange(item: ItineraryItem): string {
  return `${item.start_time} - ${item.end_time}`
}

onMounted(() => {
  void loadPost()
})

watch(
  () => props.id,
  () => {
    void loadPost()
  }
)
</script>

<template>
  <section class="page-grid community-page">
    <StatePanel v-if="loading" kind="loading" :title="copy.loadingTitle" :message="copy.loadingMessage" />

    <StatePanel
      v-else-if="error"
      kind="error"
      :title="copy.unavailableTitle"
      :message="error"
      :action-label="copy.retry"
      @action="loadPost"
    />

    <template v-else-if="post && snapshot">
      <article class="panel panel-stack">
        <img v-if="post.cover_image_url" class="community-detail-cover" :src="post.cover_image_url" :alt="post.title" />
        <div>
          <p class="kicker">{{ snapshot.destination }}</p>
          <h1>{{ post.title }}</h1>
          <div class="detail-meta">
            <span>{{ formatDateRange(snapshot.start_date, snapshot.end_date) }}</span>
            <span>{{ copy.authorLabel }}: {{ post.author_name }}</span>
            <span>{{ copy.publishedLabel }}: {{ formatDateTime(post.published_at) }}</span>
            <span>{{ copy.updatedLabel }}: {{ formatDateTime(post.updated_at) }}</span>
          </div>
        </div>
      </article>

      <article v-if="post.share_note" class="panel panel-stack">
        <div>
          <p class="kicker">{{ copy.shareNoteTitle }}</p>
          <h2>{{ copy.shareNoteTitle }}</h2>
        </div>
        <p class="community-note community-note--large">{{ post.share_note }}</p>
      </article>

      <article class="panel panel-stack">
        <div>
          <p class="kicker">{{ copy.summaryTitle }}</p>
          <h2>{{ snapshot.itinerary.summary }}</h2>
          <p class="muted">{{ snapshot.accommodation_preference || copy.accommodationLabel }}</p>
        </div>

        <div class="metric-grid">
          <article v-for="metric in itineraryMetrics" :key="metric.label" class="metric-card">
            <p class="kicker">{{ metric.label }}</p>
            <strong>{{ metric.value }}</strong>
          </article>
        </div>

        <div v-if="snapshot.interests.length" class="chip-list">
          <span v-for="interest in snapshot.interests" :key="interest" class="detail-chip detail-chip--soft">{{ interest }}</span>
        </div>
      </article>

      <article class="panel panel-stack">
        <div>
          <p class="kicker">{{ copy.itineraryTitle }}</p>
          <h2>{{ copy.itineraryTitle }}</h2>
        </div>

        <article v-for="day in snapshot.itinerary.days" :key="day.day_index" class="day-card itinerary-day-card panel-stack">
          <div class="day-card__header">
            <div>
              <p class="kicker">Day {{ day.day_index }}</p>
              <h3>{{ day.title }}</h3>
            </div>
            <strong class="day-card__cost">{{ formatCurrency(day.total_cost) }}</strong>
          </div>
          <p class="muted">{{ day.summary }}</p>
          <ol class="itinerary-items">
            <li v-for="item in day.items" :key="item.id" class="itinerary-item">
              <div class="item-time">{{ itemTimeRange(item) }}</div>
              <div class="item-main">
                <div class="item-topline">
                  <div>
                    <strong>{{ item.name }}</strong>
                    <p class="muted">{{ item.location }}</p>
                  </div>
                </div>
                <p class="item-note">{{ item.note }}</p>
                <div v-if="item.image_urls?.length" class="visual-doc-images">
                  <img v-for="url in item.image_urls.slice(0, 3)" :key="url" :src="url" :alt="item.name" />
                </div>
              </div>
            </li>
          </ol>
        </article>
      </article>

      <article class="panel panel-stack">
        <div>
          <p class="kicker">{{ copy.risksTitle }}</p>
          <h2>{{ copy.risksTitle }}</h2>
        </div>
        <ul v-if="snapshot.itinerary.risks.length" class="risk-list">
          <li v-for="risk in snapshot.itinerary.risks" :key="risk">{{ risk }}</li>
        </ul>
        <p v-else class="muted">{{ copy.noRisks }}</p>
      </article>
    </template>
  </section>
</template>
