<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import type { CommunityPostSummary } from "@travelmind/shared-types"
import StatePanel from "@/components/StatePanel.vue"
import { api, getErrorMessage } from "@/lib/api"
import { formatCurrency, formatDateRange, formatDateTime } from "@/lib/format"
import { useI18n } from "@/lib/useI18n"

const posts = ref<CommunityPostSummary[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const { locale } = useI18n()

const copy = computed(() =>
  locale.value === "zh-CN"
    ? {
        kicker: "攻略社区",
        title: "站内攻略参考",
        description: "查看其他用户公开分享的攻略快照，快速获得路线灵感、预算参考和行程节奏。",
        loadingTitle: "正在加载社区攻略",
        loadingMessage: "从站内社区接口拉取最新已发布攻略。",
        unavailableTitle: "社区暂时不可用",
        emptyTitle: "还没有公开攻略",
        emptyMessage: "第一篇攻略发布后，这里就会出现可供参考的社区内容。",
        authorLabel: "作者",
        publishedLabel: "发布时间",
        daysLabel: "天数",
        openLabel: "查看详情",
        retry: "重试"
      }
    : {
        kicker: "Community",
        title: "Shared trip references",
        description: "Browse published trip snapshots from other users for route ideas, budget references, and pacing inspiration.",
        loadingTitle: "Loading community posts",
        loadingMessage: "Fetching the latest published trip snapshots from the community feed.",
        unavailableTitle: "Community feed unavailable",
        emptyTitle: "No shared guides yet",
        emptyMessage: "Once the first guide is published, the community feed will appear here.",
        authorLabel: "Author",
        publishedLabel: "Published",
        daysLabel: "Days",
        openLabel: "Open post",
        retry: "Retry"
      }
)

async function loadPosts() {
  loading.value = true
  error.value = null
  try {
    posts.value = await api.listCommunityPosts()
  } catch (value) {
    posts.value = []
    error.value = getErrorMessage(value, copy.value.unavailableTitle)
  } finally {
    loading.value = false
  }
}

function interestPreview(post: CommunityPostSummary): string[] {
  return post.interests.slice(0, 4)
}

onMounted(() => {
  void loadPosts()
})
</script>

<template>
  <section class="page-grid community-page">
    <article class="panel">
      <p class="kicker">{{ copy.kicker }}</p>
      <h1>{{ copy.title }}</h1>
      <p class="muted">{{ copy.description }}</p>
    </article>

    <StatePanel v-if="loading" kind="loading" :title="copy.loadingTitle" :message="copy.loadingMessage" />

    <StatePanel
      v-else-if="error"
      kind="error"
      :title="copy.unavailableTitle"
      :message="error"
      :action-label="copy.retry"
      @action="loadPosts"
    />

    <StatePanel
      v-else-if="posts.length === 0"
      kind="empty"
      :title="copy.emptyTitle"
      :message="copy.emptyMessage"
    />

    <div v-else class="card-grid">
      <article v-for="post in posts" :key="post.id" class="trip-card community-card">
        <img v-if="post.cover_image_url" class="community-cover" :src="post.cover_image_url" :alt="post.title" />
        <p class="kicker">{{ post.destination }}</p>
        <h3>{{ post.title }}</h3>
        <p>{{ post.itinerary_summary }}</p>
        <p v-if="post.share_note" class="community-note">“{{ post.share_note }}”</p>
        <div class="community-meta">
          <span>{{ copy.authorLabel }}: {{ post.author_name }}</span>
          <span>{{ copy.publishedLabel }}: {{ formatDateTime(post.published_at) }}</span>
        </div>
        <div class="community-meta">
          <span>{{ formatDateRange(post.start_date, post.end_date) }}</span>
          <span>{{ copy.daysLabel }}: {{ post.day_count }}</span>
          <span>{{ formatCurrency(post.budget) }}</span>
        </div>
        <div v-if="interestPreview(post).length" class="chip-list">
          <span v-for="interest in interestPreview(post)" :key="interest" class="detail-chip detail-chip--soft">{{ interest }}</span>
        </div>
        <div class="inline-actions">
          <RouterLink class="button-link primary" :to="`/community/${post.id}`">{{ copy.openLabel }}</RouterLink>
        </div>
      </article>
    </div>
  </section>
</template>
