<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue"
import type { CommunityPostDetail, ItineraryItem, SearchDocument } from "@travelmind/shared-types"
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
        loadingMessage: "获取这篇社区攻略的完整只读快照。",
        unavailableTitle: "攻略详情暂时不可用",
        projectTitle: "项目概览",
        briefTitle: "规划输入",
        shareNoteTitle: "作者心得",
        itineraryTitle: "每日安排",
        risksTitle: "风险提示",
        traceTitle: "执行轨迹",
        sourceTitle: "参考来源",
        authorLabel: "作者",
        publishedLabel: "发布时间",
        updatedLabel: "最近更新",
        originLabel: "出发地",
        destinationLabel: "目的地",
        datesLabel: "日期",
        budgetLabel: "预算",
        travelersLabel: "出行人数",
        paceLabel: "节奏",
        transportLabel: "交通",
        accommodationLabel: "住宿偏好",
        providerLabel: "Provider",
        workflowLabel: "工作流 ID",
        modelLabel: "模型",
        outputLabel: "输出摘要",
        retry: "重试",
        noTrace: "当前分享快照没有附带执行轨迹。",
        noSources: "当前分享快照没有附带参考来源。",
        noRisks: "当前快照没有附带风险提示。",
        openSource: "打开来源"
      }
    : {
        loadingTitle: "Loading community post",
        loadingMessage: "Fetching the full read-only Trip snapshot for this community post.",
        unavailableTitle: "Community post unavailable",
        projectTitle: "Project overview",
        briefTitle: "Planning brief",
        shareNoteTitle: "Author note",
        itineraryTitle: "Daily itinerary",
        risksTitle: "Risk notes",
        traceTitle: "Execution trace",
        sourceTitle: "Grounding sources",
        authorLabel: "Author",
        publishedLabel: "Published",
        updatedLabel: "Updated",
        originLabel: "Origin",
        destinationLabel: "Destination",
        datesLabel: "Dates",
        budgetLabel: "Budget",
        travelersLabel: "Travelers",
        paceLabel: "Pace",
        transportLabel: "Transport",
        accommodationLabel: "Stay preference",
        providerLabel: "Provider",
        workflowLabel: "Workflow ID",
        modelLabel: "Model",
        outputLabel: "Output summary",
        retry: "Retry",
        noTrace: "No execution trace was attached to this shared snapshot.",
        noSources: "No grounding sources were attached to this shared snapshot.",
        noRisks: "No risk notes were attached to this snapshot.",
        openSource: "Open source"
      }
)

const snapshot = computed(() => post.value?.snapshot ?? null)
const briefFields = computed(() => {
  if (!snapshot.value) {
    return []
  }
  return [
    { label: copy.value.originLabel, value: snapshot.value.origin },
    { label: copy.value.destinationLabel, value: snapshot.value.destination },
    { label: copy.value.datesLabel, value: formatDateRange(snapshot.value.start_date, snapshot.value.end_date) },
    { label: copy.value.budgetLabel, value: formatCurrency(snapshot.value.budget) },
    { label: copy.value.travelersLabel, value: String(snapshot.value.travelers) },
    { label: copy.value.paceLabel, value: snapshot.value.pace },
    { label: copy.value.transportLabel, value: snapshot.value.transport_mode },
    { label: copy.value.accommodationLabel, value: snapshot.value.accommodation_preference || "—" }
  ]
})
const trace = computed(() => snapshot.value?.latest_agent_trace ?? null)
const groundingDocuments = computed<SearchDocument[]>(() => {
  const raw = trace.value?.grounding_documents
  return Array.isArray(raw) ? raw : []
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
          <p class="kicker">{{ copy.projectTitle }}</p>
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
          <p class="kicker">{{ copy.briefTitle }}</p>
          <h2>{{ snapshot.itinerary.summary }}</h2>
        </div>

        <dl class="data-grid">
          <div v-for="field in briefFields" :key="field.label" class="data-pair">
            <dt>{{ field.label }}</dt>
            <dd>{{ field.value }}</dd>
          </div>
        </dl>

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
          <p class="kicker">{{ copy.traceTitle }}</p>
          <h2>{{ copy.traceTitle }}</h2>
        </div>

        <template v-if="trace">
          <dl class="data-grid">
            <div class="data-pair">
              <dt>{{ copy.providerLabel }}</dt>
              <dd>{{ trace.provider }}</dd>
            </div>
            <div class="data-pair">
              <dt>{{ copy.workflowLabel }}</dt>
              <dd>{{ trace.workflow_id }}</dd>
            </div>
          </dl>

          <div v-if="trace.agent_runs?.length" class="agent-run-grid">
            <article v-for="agent in trace.agent_runs" :key="agent.key" class="search-card panel-stack agent-run-card">
              <div class="agent-run-card__header">
                <div>
                  <p class="kicker">{{ agent.key }}</p>
                  <h3>{{ agent.title }}</h3>
                </div>
              </div>
              <p>{{ agent.description }}</p>
              <dl class="data-grid">
                <div v-if="agent.model" class="data-pair">
                  <dt>{{ copy.modelLabel }}</dt>
                  <dd>{{ agent.model }}</dd>
                </div>
                <div v-if="agent.output_summary" class="data-pair">
                  <dt>{{ copy.outputLabel }}</dt>
                  <dd>{{ agent.output_summary }}</dd>
                </div>
              </dl>
            </article>
          </div>
        </template>
        <p v-else class="muted">{{ copy.noTrace }}</p>
      </article>

      <article class="panel panel-stack">
        <div>
          <p class="kicker">{{ copy.sourceTitle }}</p>
          <h2>{{ copy.sourceTitle }}</h2>
        </div>

        <div v-if="groundingDocuments.length" class="reference-doc-grid">
          <article v-for="doc in groundingDocuments" :key="doc.id" class="search-card panel-stack">
            <div class="search-card__header">
              <div>
                <p class="kicker">{{ doc.platform }}</p>
                <h3>{{ doc.place_name || doc.title }}</h3>
              </div>
            </div>
            <p>{{ doc.summary }}</p>
            <div class="inline-actions">
              <a class="button-link" :href="doc.url" target="_blank" rel="noreferrer">{{ copy.openSource }}</a>
            </div>
          </article>
        </div>
        <p v-else class="muted">{{ copy.noSources }}</p>
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
