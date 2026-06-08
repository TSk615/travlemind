<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue"
import { RouterLink, useRoute, useRouter } from "vue-router"
import type {
  AdminCommunityPostDetail,
  AdminCommunityPostSummary,
  AdminJobDetail,
  AdminJobSummary,
  AdminOwnerSummary,
  AdminPage,
  AdminTripDetail,
  AdminTripSummary,
  AdminUserDetail,
  AdminUserSummary
} from "@travelmind/shared-types"
import { ApiError, api, type AdminListParams } from "@/lib/api"
import { useAuthStore } from "@/stores/auth"

type AdminSection = "users" | "trips" | "community" | "jobs"
type AdminDetail = AdminUserDetail | AdminTripDetail | AdminCommunityPostDetail | AdminJobDetail | null
type AdminRow = AdminUserSummary | AdminTripSummary | AdminCommunityPostSummary | AdminJobSummary

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const detailLoading = ref(false)
const actionPending = ref(false)
const error = ref("")
const detailError = ref("")
const rows = ref<AdminRow[]>([])
const detail = ref<AdminDetail>(null)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

const filters = reactive({
  query: "",
  status: "all",
  destination: "",
  ownerId: "",
  hasItinerary: "",
  hasCommunityPost: "",
  staleOnly: false,
  type: "",
  jobStatus: ""
})

const sections: Array<{ key: AdminSection; label: string; path: string }> = [
  { key: "users", label: "用户", path: "/admin/users" },
  { key: "trips", label: "行程", path: "/admin/trips" },
  { key: "community", label: "社区", path: "/admin/community" },
  { key: "jobs", label: "任务", path: "/admin/jobs" }
]

const jobStatusLabels: Record<string, string> = {
  queued: "排队中",
  running: "执行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消"
}

const jobTypeLabels: Record<string, string> = {
  "trip.generate": "生成行程",
  "trip.refine": "微调行程",
  "trip.image_enrich": "补全配图",
  "export.pdf": "导出 PDF",
  "image.generate": "生成图片"
}

const adminErrorMessages: Record<string, string> = {
  admin_forbidden: "你没有后台访问权限",
  admin_user_not_found: "未找到该用户",
  admin_trip_not_found: "未找到该行程",
  admin_community_post_not_found: "未找到该帖子",
  admin_job_not_found: "未找到该任务",
  cannot_disable_self: "不能禁用当前登录的管理员账号",
  invalid_user_status: "用户状态筛选参数不正确",
  user_disabled: "该账号已被禁用",
  not_authenticated: "当前未登录",
  invalid_token: "登录状态已失效，请重新登录",
  refresh_session_not_found: "登录状态已失效，请重新登录",
  refresh_session_expired: "登录状态已过期，请重新登录",
  user_not_found: "未找到当前用户"
}

const currentSection = computed<AdminSection>(() => {
  const path = route.path
  if (path.startsWith("/admin/trips")) return "trips"
  if (path.startsWith("/admin/community")) return "community"
  if (path.startsWith("/admin/jobs")) return "jobs"
  return "users"
})
const detailId = computed(() => (typeof route.params.id === "string" ? route.params.id : ""))
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const activeSectionLabel = computed(() => sections.find((section) => section.key === currentSection.value)?.label ?? "用户")
const searchPlaceholder = computed(() => {
  if (currentSection.value === "users") return "搜索用户姓名或邮箱"
  if (currentSection.value === "trips") return "搜索行程标题、目的地或用户"
  if (currentSection.value === "community") return "搜索帖子标题、目的地或作者"
  return "搜索任务 ID、类型或用户"
})

function ownerLabel(owner?: AdminOwnerSummary | null) {
  if (!owner) return "未知用户"
  return `${owner.name} / ${owner.email}`
}

function formatDate(value?: string | null) {
  if (!value) return "无"
  return new Date(value).toLocaleString("zh-CN")
}

function shortId(value?: string | null) {
  if (!value) return "无"
  return value.length > 16 ? `${value.slice(0, 8)}...${value.slice(-6)}` : value
}

function statusClass(value?: string | null) {
  const normalized = String(value || "").toLowerCase()
  return {
    "admin-pill--ok": ["completed", "active", "public"].includes(normalized),
    "admin-pill--warn": ["queued", "running"].includes(normalized),
    "admin-pill--danger": ["failed", "disabled"].includes(normalized)
  }
}

function userStatusLabel(disabledAt?: string | null) {
  return disabledAt ? "已禁用" : "正常"
}

function jobStatusLabel(value?: string | null) {
  if (!value) return "未知"
  return jobStatusLabels[String(value).toLowerCase()] ?? value
}

function jobTypeLabel(value?: string | null) {
  if (!value) return "未知类型"
  return jobTypeLabels[value] ?? value
}

function getAdminErrorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    return adminErrorMessages[error.code] ?? fallback
  }
  return fallback
}

function sectionPath(section: AdminSection, id?: string) {
  if (section === "community") return id ? `/admin/community/${id}` : "/admin/community"
  return id ? `/admin/${section}/${id}` : `/admin/${section}`
}

function rowId(row: AdminRow) {
  if ("job_id" in row) return row.job_id
  return row.id
}

function buildParams(): AdminListParams {
  const params: AdminListParams = {
    page: page.value,
    page_size: pageSize.value,
    query: filters.query.trim() || undefined
  }
  if (currentSection.value === "users") {
    params.status = filters.status
  }
  if (currentSection.value === "trips") {
    params.owner_id = filters.ownerId.trim() || undefined
    params.destination = filters.destination.trim() || undefined
    if (filters.hasItinerary) params.has_itinerary = filters.hasItinerary === "true"
    if (filters.hasCommunityPost) params.has_community_post = filters.hasCommunityPost === "true"
  }
  if (currentSection.value === "community") {
    params.author_id = filters.ownerId.trim() || undefined
    params.destination = filters.destination.trim() || undefined
    params.stale_only = filters.staleOnly || undefined
  }
  if (currentSection.value === "jobs") {
    params.owner_id = filters.ownerId.trim() || undefined
    params.status = filters.jobStatus.trim() || undefined
    params.type = filters.type.trim() || undefined
  }
  return params
}

function applyPage<T extends AdminRow>(payload: AdminPage<T>) {
  rows.value = payload.items
  page.value = payload.page
  pageSize.value = payload.page_size
  total.value = payload.total
}

async function loadRows() {
  loading.value = true
  error.value = ""
  try {
    if (currentSection.value === "users") {
      applyPage(await api.listAdminUsers(buildParams()))
    } else if (currentSection.value === "trips") {
      applyPage(await api.listAdminTrips(buildParams()))
    } else if (currentSection.value === "community") {
      applyPage(await api.listAdminCommunityPosts(buildParams()))
    } else {
      applyPage(await api.listAdminJobs(buildParams()))
    }
  } catch (caught) {
    error.value = getAdminErrorMessage(caught, "加载后台数据失败")
  } finally {
    loading.value = false
  }
}

async function loadDetail() {
  detail.value = null
  detailError.value = ""
  if (!detailId.value) return
  detailLoading.value = true
  try {
    if (currentSection.value === "users") {
      detail.value = await api.getAdminUser(detailId.value)
    } else if (currentSection.value === "trips") {
      detail.value = await api.getAdminTrip(detailId.value)
    } else if (currentSection.value === "community") {
      detail.value = await api.getAdminCommunityPost(detailId.value)
    } else {
      detail.value = await api.getAdminJob(detailId.value)
    }
  } catch (caught) {
    detailError.value = getAdminErrorMessage(caught, "加载详情失败")
  } finally {
    detailLoading.value = false
  }
}

function resetFilters() {
  filters.query = ""
  filters.status = "all"
  filters.destination = ""
  filters.ownerId = ""
  filters.hasItinerary = ""
  filters.hasCommunityPost = ""
  filters.staleOnly = false
  filters.type = ""
  filters.jobStatus = ""
  page.value = 1
  void loadRows()
}

function search() {
  page.value = 1
  void loadRows()
}

function changePage(nextPage: number) {
  page.value = Math.min(totalPages.value, Math.max(1, nextPage))
  void loadRows()
}

async function runReasonedAction(label: string, runner: (reason: string) => Promise<unknown>) {
  const reason = window.prompt(`请输入“${label}”原因`)
  if (!reason?.trim()) return
  actionPending.value = true
  error.value = ""
  try {
    await runner(reason.trim())
    await loadRows()
    await loadDetail()
  } catch (caught) {
    error.value = getAdminErrorMessage(caught, `${label}失败`)
  } finally {
    actionPending.value = false
  }
}

function disableUser(user: AdminUserSummary | AdminUserDetail) {
  void runReasonedAction("禁用用户", (reason) => api.disableAdminUser(user.id, reason))
}

function enableUser(user: AdminUserSummary | AdminUserDetail) {
  void runReasonedAction("启用用户", (reason) => api.enableAdminUser(user.id, reason))
}

function deleteTrip(trip: AdminTripSummary | AdminTripDetail) {
  void runReasonedAction("删除行程", async (reason) => {
    await api.deleteAdminTrip(trip.id, reason)
    if (detailId.value === trip.id) await router.push(sectionPath("trips"))
  })
}

function deleteCommunityPost(post: AdminCommunityPostSummary | AdminCommunityPostDetail) {
  void runReasonedAction("删除社区帖子", async (reason) => {
    await api.deleteAdminCommunityPost(post.id, reason)
    if (detailId.value === post.id) await router.push(sectionPath("community"))
  })
}

watch(
  () => [currentSection.value, detailId.value],
  async () => {
    page.value = 1
    await loadRows()
    await loadDetail()
  }
)

onMounted(async () => {
  if (route.path === "/admin") {
    await router.replace("/admin/users")
    return
  }
  await loadRows()
  await loadDetail()
})
</script>

<template>
  <section class="admin-view">
    <header class="admin-view__header">
      <div>
        <p class="admin-view__eyebrow">后台管理</p>
        <h1>管理后台</h1>
      </div>
      <div class="admin-view__session">
        <span>{{ auth.user?.email }}</span>
        <span class="admin-pill admin-pill--ok">管理员</span>
      </div>
    </header>

    <nav class="admin-tabs" aria-label="后台分区">
      <RouterLink
        v-for="section in sections"
        :key="section.key"
        :class="['admin-tabs__item', { 'admin-tabs__item--active': currentSection === section.key }]"
        :to="section.path"
      >
        {{ section.label }}
      </RouterLink>
    </nav>

    <form class="admin-filters" @submit.prevent="search">
      <input v-model="filters.query" type="search" :placeholder="searchPlaceholder" />
      <select v-if="currentSection === 'users'" v-model="filters.status">
        <option value="all">全部用户</option>
        <option value="active">正常用户</option>
        <option value="disabled">已禁用用户</option>
      </select>
      <input v-if="currentSection !== 'users'" v-model="filters.ownerId" type="search" placeholder="用户 ID" />
      <input v-if="currentSection === 'trips' || currentSection === 'community'" v-model="filters.destination" type="search" placeholder="目的地" />
      <select v-if="currentSection === 'trips'" v-model="filters.hasItinerary">
        <option value="">全部行程状态</option>
        <option value="true">已生成行程</option>
        <option value="false">未生成行程</option>
      </select>
      <select v-if="currentSection === 'trips'" v-model="filters.hasCommunityPost">
        <option value="">全部发布状态</option>
        <option value="true">已发布</option>
        <option value="false">未发布</option>
      </select>
      <label v-if="currentSection === 'community'" class="admin-check">
        <input v-model="filters.staleOnly" type="checkbox" />
        只看已过期帖子
      </label>
      <input v-if="currentSection === 'jobs'" v-model="filters.jobStatus" type="search" placeholder="任务状态" />
      <input v-if="currentSection === 'jobs'" v-model="filters.type" type="search" placeholder="任务类型" />
      <button type="submit">筛选</button>
      <button type="button" class="admin-button-secondary" @click="resetFilters">重置</button>
    </form>

    <p v-if="error" class="admin-error">{{ error }}</p>

    <div class="admin-shell">
      <section class="admin-panel">
        <div class="admin-panel__bar">
          <strong>{{ activeSectionLabel }}</strong>
          <span>{{ total }} 条记录</span>
        </div>

        <div v-if="loading" class="admin-empty">正在加载记录...</div>
        <div v-else-if="!rows.length" class="admin-empty">暂无记录。</div>

        <div v-else class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr v-if="currentSection === 'users'">
                <th>用户</th>
                <th>状态</th>
                <th>活跃情况</th>
                <th>创建时间</th>
                <th>操作</th>
              </tr>
              <tr v-else-if="currentSection === 'trips'">
                <th>行程</th>
                <th>所有者</th>
                <th>标记</th>
                <th>更新时间</th>
                <th>操作</th>
              </tr>
              <tr v-else-if="currentSection === 'community'">
                <th>帖子</th>
                <th>作者</th>
                <th>状态</th>
                <th>发布时间</th>
                <th>操作</th>
              </tr>
              <tr v-else>
                <th>任务</th>
                <th>所有者</th>
                <th>状态</th>
                <th>更新时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="rowId(row)">
                <template v-if="'email' in row">
                  <td>
                    <RouterLink :to="sectionPath('users', row.id)" class="admin-link">{{ row.name }}</RouterLink>
                    <span>{{ row.email }}</span>
                  </td>
                  <td>
                    <span :class="['admin-pill', statusClass(row.disabled_at ? 'disabled' : 'active')]">
                      {{ userStatusLabel(row.disabled_at) }}
                    </span>
                    <span v-if="row.is_admin" class="admin-pill admin-pill--ok">管理员</span>
                  </td>
                  <td>{{ row.trip_count }} 个行程 / {{ row.community_post_count }} 篇帖子 / {{ row.job_count }} 个任务</td>
                  <td>{{ formatDate(row.created_at) }}</td>
                  <td>
                    <button v-if="row.disabled_at" type="button" @click="enableUser(row)">启用</button>
                    <button v-else type="button" :disabled="row.id === auth.user?.id" @click="disableUser(row)">禁用</button>
                  </td>
                </template>

                <template v-else-if="'has_itinerary' in row">
                  <td>
                    <RouterLink :to="sectionPath('trips', row.id)" class="admin-link">{{ row.title }}</RouterLink>
                    <span>{{ row.origin }} 至 {{ row.destination }}</span>
                  </td>
                  <td>{{ ownerLabel(row.owner) }}</td>
                  <td>
                    <span class="admin-pill" :class="{ 'admin-pill--ok': row.has_itinerary }">{{ row.has_itinerary ? "已生成行程" : "草稿" }}</span>
                    <span class="admin-pill" :class="{ 'admin-pill--ok': row.has_community_post }">{{ row.has_community_post ? "已发布" : "未发布" }}</span>
                  </td>
                  <td>{{ formatDate(row.updated_at) }}</td>
                  <td><button type="button" class="admin-danger" @click="deleteTrip(row)">删除</button></td>
                </template>

                <template v-else-if="'published_at' in row">
                  <td>
                    <RouterLink :to="sectionPath('community', row.id)" class="admin-link">{{ row.title }}</RouterLink>
                    <span>{{ row.destination }}</span>
                  </td>
                  <td>{{ ownerLabel(row.author) }}</td>
                  <td><span :class="['admin-pill', { 'admin-pill--warn': row.is_stale }]">{{ row.is_stale ? "已过期" : "最新" }}</span></td>
                  <td>{{ formatDate(row.published_at) }}</td>
                  <td><button type="button" class="admin-danger" @click="deleteCommunityPost(row)">删除</button></td>
                </template>

                <template v-else>
                  <td>
                    <RouterLink :to="sectionPath('jobs', row.job_id)" class="admin-link">{{ shortId(row.job_id) }}</RouterLink>
                    <span>{{ jobTypeLabel(row.type) }}</span>
                  </td>
                  <td>{{ ownerLabel(row.owner) }}</td>
                  <td><span :class="['admin-pill', statusClass(row.status)]">{{ jobStatusLabel(row.status) }}</span></td>
                  <td>{{ formatDate(row.updated_at) }}</td>
                  <td><span class="admin-muted">只读</span></td>
                </template>
              </tr>
            </tbody>
          </table>
        </div>

        <footer class="admin-pagination">
          <button type="button" :disabled="page <= 1 || loading" @click="changePage(page - 1)">上一页</button>
          <span>第 {{ page }} / {{ totalPages }} 页</span>
          <button type="button" :disabled="page >= totalPages || loading" @click="changePage(page + 1)">下一页</button>
        </footer>
      </section>

      <aside class="admin-detail">
        <div class="admin-panel__bar">
          <strong>详情</strong>
          <RouterLink :to="sectionPath(currentSection)">关闭</RouterLink>
        </div>

        <div v-if="detailLoading" class="admin-empty">正在加载详情...</div>
        <p v-else-if="detailError" class="admin-error">{{ detailError }}</p>
        <div v-else-if="!detail" class="admin-empty">请选择一条记录查看详情。</div>

        <div v-else class="admin-detail__body">
          <template v-if="'email' in detail">
            <h2>{{ detail.name }}</h2>
            <p>{{ detail.email }}</p>
            <dl>
              <dt>状态</dt><dd>{{ userStatusLabel(detail.disabled_at) }}</dd>
              <dt>创建时间</dt><dd>{{ formatDate(detail.created_at) }}</dd>
              <dt>统计</dt><dd>{{ detail.trip_count }} 个行程，{{ detail.community_post_count }} 篇帖子，{{ detail.job_count }} 个任务</dd>
              <dt>密钥配置</dt><dd>LLM {{ detail.has_llm_api_key ? "已配置" : "未配置" }}，搜索 {{ detail.has_search_api_key ? "已配置" : "未配置" }}，图片 {{ detail.has_image_api_key ? "已配置" : "未配置" }}</dd>
            </dl>
            <button v-if="detail.disabled_at" type="button" @click="enableUser(detail)">启用用户</button>
            <button v-else type="button" :disabled="detail.id === auth.user?.id" @click="disableUser(detail)">禁用用户</button>
          </template>

          <template v-else-if="'has_itinerary' in detail">
            <h2>{{ detail.title }}</h2>
            <p>{{ detail.origin }} 至 {{ detail.destination }}</p>
            <dl>
              <dt>所有者</dt><dd>{{ ownerLabel(detail.owner) }}</dd>
              <dt>日期</dt><dd>{{ detail.start_date }} 至 {{ detail.end_date }}</dd>
              <dt>预算</dt><dd>{{ detail.budget }} / {{ detail.travelers }} 人</dd>
              <dt>兴趣偏好</dt><dd>{{ detail.interests.join("、") || "无" }}</dd>
            </dl>
            <pre>{{ JSON.stringify(detail.itinerary ?? {}, null, 2) }}</pre>
            <button type="button" class="admin-danger" @click="deleteTrip(detail)">删除行程</button>
          </template>

          <template v-else-if="'published_at' in detail">
            <h2>{{ detail.title }}</h2>
            <p>{{ detail.share_note || "暂无分享说明" }}</p>
            <dl>
              <dt>作者</dt><dd>{{ ownerLabel(detail.author) }}</dd>
              <dt>目的地</dt><dd>{{ detail.destination }}</dd>
              <dt>发布时间</dt><dd>{{ formatDate(detail.published_at) }}</dd>
              <dt>是否过期</dt><dd>{{ detail.is_stale ? "是" : "否" }}</dd>
            </dl>
            <pre>{{ JSON.stringify(detail.snapshot ?? {}, null, 2) }}</pre>
            <button type="button" class="admin-danger" @click="deleteCommunityPost(detail)">删除帖子</button>
          </template>

          <template v-else>
            <h2>{{ shortId(detail.job_id) }}</h2>
            <p>{{ jobTypeLabel(detail.type) }}</p>
            <dl>
              <dt>状态</dt><dd>{{ jobStatusLabel(detail.status) }}</dd>
              <dt>所有者</dt><dd>{{ ownerLabel(detail.owner) }}</dd>
              <dt>关联行程</dt><dd>{{ detail.trip_id ?? "无" }}</dd>
              <dt>进度</dt><dd>{{ detail.progress_percent ?? 0 }}%</dd>
            </dl>
            <pre>{{ JSON.stringify({ payload: detail.payload, result: detail.result, timeline: detail.timeline_json }, null, 2) }}</pre>
          </template>
        </div>
      </aside>
    </div>

    <div v-if="actionPending" class="admin-action-status">正在执行操作...</div>
  </section>
</template>

<style scoped>
.admin-view {
  display: grid;
  gap: 16px;
}

.admin-view__header,
.admin-filters,
.admin-panel,
.admin-detail {
  border: 1px solid rgba(255, 255, 255, 0.58);
  border-radius: 8px;
  background: rgba(242, 245, 249, 0.74);
  box-shadow: var(--tm-shadow-raised-sm);
}

.admin-view__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px;
}

.admin-view__eyebrow {
  margin: 0 0 4px;
  color: var(--tm-muted);
  font-size: 0.74rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.admin-view h1,
.admin-detail h2 {
  margin: 0;
  color: var(--tm-ink);
  line-height: 1.15;
}

.admin-view__session {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--tm-muted);
  font-size: 0.85rem;
}

.admin-tabs {
  display: flex;
  gap: 8px;
  overflow-x: auto;
}

.admin-tabs__item {
  padding: 8px 12px;
  border-radius: 8px;
  color: var(--tm-muted);
  text-decoration: none;
  font-size: 0.9rem;
  font-weight: 700;
}

.admin-tabs__item--active {
  background: var(--tm-surface-strong);
  color: var(--tm-accent-strong);
  box-shadow: var(--tm-shadow-inset-sm);
}

.admin-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 12px;
}

.admin-filters input,
.admin-filters select {
  min-height: 36px;
  min-width: 160px;
  border: 0;
  border-radius: 8px;
  padding: 0 10px;
  background: var(--tm-surface-strong);
  color: var(--tm-ink);
  box-shadow: var(--tm-shadow-inset-sm);
}

.admin-check {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--tm-muted);
  font-size: 0.9rem;
}

button {
  min-height: 34px;
  border: 0;
  border-radius: 8px;
  padding: 0 12px;
  background: var(--tm-accent);
  color: white;
  font-weight: 700;
  cursor: pointer;
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.admin-button-secondary {
  background: var(--tm-surface-strong);
  color: var(--tm-muted);
}

.admin-danger {
  background: var(--tm-danger);
}

.admin-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 0.42fr);
  gap: 16px;
  align-items: start;
}

.admin-panel,
.admin-detail {
  min-width: 0;
}

.admin-panel__bar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid rgba(60, 64, 67, 0.1);
  color: var(--tm-muted);
}

.admin-panel__bar strong {
  color: var(--tm-ink);
}

.admin-table-wrap {
  overflow: auto;
}

.admin-table {
  width: 100%;
  min-width: 820px;
  border-collapse: collapse;
}

.admin-table th,
.admin-table td {
  padding: 12px 14px;
  border-bottom: 1px solid rgba(60, 64, 67, 0.08);
  text-align: left;
  vertical-align: top;
  font-size: 0.86rem;
}

.admin-table th {
  color: var(--tm-muted);
  font-size: 0.72rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.admin-table td > span {
  display: block;
  margin-top: 4px;
  color: var(--tm-muted);
}

.admin-link {
  color: var(--tm-accent-strong);
  font-weight: 800;
  text-decoration: none;
}

.admin-pill {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  margin: 0 6px 6px 0;
  border-radius: 999px;
  padding: 0 8px;
  background: rgba(95, 99, 104, 0.12);
  color: var(--tm-muted);
  font-size: 0.72rem;
  font-weight: 800;
}

.admin-pill--ok {
  background: rgba(52, 168, 83, 0.16);
  color: var(--tm-success);
}

.admin-pill--warn {
  background: rgba(251, 188, 4, 0.2);
  color: #8a6500;
}

.admin-pill--danger {
  background: rgba(234, 67, 53, 0.14);
  color: var(--tm-danger);
}

.admin-empty,
.admin-error,
.admin-action-status {
  padding: 18px;
  color: var(--tm-muted);
}

.admin-error {
  border-radius: 8px;
  background: rgba(234, 67, 53, 0.1);
  color: var(--tm-danger);
}

.admin-pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  padding: 12px 14px;
  color: var(--tm-muted);
}

.admin-detail {
  position: sticky;
  top: 12px;
}

.admin-detail__body {
  display: grid;
  gap: 12px;
  padding: 14px;
}

.admin-detail__body p {
  margin: 0;
  color: var(--tm-muted);
}

.admin-detail dl {
  display: grid;
  grid-template-columns: 92px 1fr;
  gap: 8px 12px;
  margin: 0;
}

.admin-detail dt {
  color: var(--tm-muted);
  font-size: 0.78rem;
  font-weight: 800;
}

.admin-detail dd {
  margin: 0;
  color: var(--tm-ink);
  min-width: 0;
  overflow-wrap: anywhere;
}

.admin-detail pre {
  max-height: 340px;
  overflow: auto;
  margin: 0;
  border-radius: 8px;
  padding: 12px;
  background: rgba(216, 220, 227, 0.72);
  color: var(--tm-ink);
  font-size: 0.78rem;
  line-height: 1.45;
}

.admin-muted {
  color: var(--tm-muted);
}

@media (max-width: 980px) {
  .admin-shell {
    grid-template-columns: 1fr;
  }

  .admin-detail {
    position: static;
  }

  .admin-view__header {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
