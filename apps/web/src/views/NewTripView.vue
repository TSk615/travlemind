<script setup lang="ts">
import { computed, reactive, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import type { TripPreferenceInput } from "@travelmind/shared-types"
import LlmStatusNotice from "@/components/LlmStatusNotice.vue"
import StatePanel from "@/components/StatePanel.vue"
import TmButton from "@/components/ui/TmButton.vue"
import TmSegmentedSwitch from "@/components/ui/TmSegmentedSwitch.vue"
import TmFieldGroup from "@/components/ui/TmFieldGroup.vue"
import TmField from "@/components/ui/TmField.vue"
import TmTextarea from "@/components/ui/TmTextarea.vue"
import TmSelect from "@/components/ui/TmSelect.vue"
import TmAuroraPanel from "@/components/ui/TmAuroraPanel.vue"
import TmProgressTrack from "@/components/ui/TmProgressTrack.vue"
import { api, getErrorMessage } from "@/lib/api"
import type { TripIntakeChatMessage } from "@/lib/api"
import { useI18n } from "@/lib/useI18n"
import { useAuthStore } from "@/stores/auth"

const auth = useAuthStore()
const isDemo = computed(() => Boolean(auth.user?.generation_quota))
const router = useRouter()
const route = useRoute()
const initialPrompt = typeof route.query.prompt === "string" ? route.query.prompt.slice(0, 1600) : ""
const submitting = ref(false)
const generating = ref(false)
const chatting = ref(false)
const error = ref<string | null>(null)
const mode = ref<"form" | "chat">(initialPrompt && !isDemo.value ? "chat" : "form")
const chatInput = ref(initialPrompt)
const chatMessages = ref<TripIntakeChatMessage[]>([])
const readyToCreate = ref(false)
const { locale, t } = useI18n()

const enCopy = {
  kicker: "New trip",
  title: "Capture the planning brief",
  description: "Switch between a structured form and an AI-guided intake conversation. Both modes write into the same trip brief.",
  formMode: "Form mode",
  chatMode: "Conversation mode",
  modeHint: "Use the form when you already know the details. Use conversation mode when you want the backend assistant to collect the missing information.",
  starter: "Use starter brief",
  clear: "Clear form",
  creatingTitle: "Creating trip",
  creatingMessage: "Posting the planning brief to `/api/v1/trips` and waiting for the persisted record.",
  chatLoadingTitle: "Collecting trip brief",
  chatLoadingMessage: "The backend intake assistant is processing your latest reply and updating the draft.",
  needsAttentionTitle: "Trip brief needs attention",
  blankTitle: "Trip brief is blank",
  blankMessage: "Add origin, destination, dates, budget, and interests before creating the trip.",
  titleLabel: "Trip title",
  originLabel: "Departure",
  destinationLabel: "Destination",
  startDateLabel: "Start date",
  endDateLabel: "End date",
  budgetLabel: "Budget",
  travelersLabel: "Travelers",
  paceLabel: "Pace",
  transportLabel: "Transport",
  interestsLabel: "Interests",
  accommodationLabel: "Accommodation preference",
  interestsPlaceholder: "temples, coffee, quiet neighborhoods",
  createTrip: "Create trip",
  creatingTrip: "Creating trip...",
  generateTrip: "Create and generate",
  generatingTrip: "Creating and generating...",
  nextStepNote: "Create trip only saves the brief; the next step is Generate itinerary on the trip detail page.",
  intakeTitle: "Guided intake",
  intakeDescription: "Tell the backend assistant what you already know. It will keep asking for the missing pieces and mirror them into the draft on the right.",
  chatInputLabel: "Reply",
  chatInputPlaceholder: "Example: I want to go from Guangzhou to Shantou from 2026/04/14 to 2026/04/18 with a budget around 6800.",
  send: "Send",
  assistantLabel: "Assistant",
  userLabel: "You",
  collectedTitle: "Current brief draft",
  collectedEmpty: "No information captured yet.",
  readyMessage: "The brief is complete enough to create the trip now.",
  validation: {
    title: "Trip title must be at least 3 characters.",
    origin: "Departure must be at least 2 characters.",
    destination: "Destination must be at least 2 characters.",
    datesRequired: "Start date and end date are required.",
    startDatePast: "Start date must be today or later.",
    datesRange: "End date must be on or after the start date.",
    budget: "Budget must be greater than 0.",
    travelers: "Travelers must be at least 1."
  },
  autoTitlePrefix: "Trip"
}

const zhCopy = {
  kicker: "新建行程",
  title: "整理行程 Brief",
  description: "可以在结构化表单和 AI 引导式对话之间切换，两种模式都会写入同一份行程草稿。",
  formMode: "填表单",
  chatMode: "直接对话",
  modeHint: "如果你已经知道大部分信息，就直接填表。若只知道一部分，可以让后端助手通过对话逐步补全。",
  starter: "使用示例草稿",
  clear: "清空草稿",
  creatingTitle: "正在创建行程",
  creatingMessage: "正在把行程 Brief 提交到 `/api/v1/trips`，并等待后端返回持久化结果。",
  chatLoadingTitle: "正在补全行程 Brief",
  chatLoadingMessage: "后端对话助手正在处理你的最新回复，并同步更新草稿。",
  needsAttentionTitle: "行程 Brief 需要补充",
  blankTitle: "行程 Brief 还是空的",
  blankMessage: "请先补充出发地、目的地、日期、预算和兴趣偏好，再创建行程。",
  titleLabel: "行程标题",
  originLabel: "出发地",
  destinationLabel: "目的地",
  startDateLabel: "开始日期",
  endDateLabel: "结束日期",
  budgetLabel: "预算",
  travelersLabel: "出行人数",
  paceLabel: "节奏",
  transportLabel: "交通方式",
  interestsLabel: "兴趣偏好",
  accommodationLabel: "住宿偏好",
  interestsPlaceholder: "寺庙, 咖啡, 安静街区",
  createTrip: "创建行程",
  creatingTrip: "创建中...",
  generateTrip: "创建并生成",
  generatingTrip: "创建并生成中...",
  nextStepNote: "创建 trip 只会保存 Brief；下一步是在详情页点击“生成行程”，正式进入规划链路。",
  intakeTitle: "引导式对话",
  intakeDescription: "把你已知的信息告诉后端助手，它会继续追问缺失项，并同步写入右侧草稿。",
  chatInputLabel: "回复",
  chatInputPlaceholder: "例如：我想从广州去汕头，2026/04/14 到 2026/04/18，预算大概 6800。",
  send: "发送",
  assistantLabel: "助手",
  userLabel: "你",
  collectedTitle: "当前草稿",
  collectedEmpty: "还没有收集到信息。",
  readyMessage: "当前信息已经足够创建行程，可以直接提交。",
  validation: {
    title: "行程标题至少需要 3 个字符。",
    origin: "出发地至少需要 2 个字符。",
    destination: "目的地至少需要 2 个字符。",
    datesRequired: "开始日期和结束日期都需要填写。",
    startDatePast: "开始日期不能早于今天。",
    datesRange: "结束日期必须晚于或等于开始日期。",
    budget: "预算必须大于 0。",
    travelers: "出行人数至少为 1。"
  },
  autoTitlePrefix: "行程"
}
const copy = computed<typeof enCopy>(() => (locale.value === "zh-CN" ? (zhCopy as typeof enCopy) : enCopy))
const chatGenerateLabel = computed(() => (locale.value === "zh-CN" ? "创建并生成" : "Create and generate"))
const chatGeneratingLabel = computed(() => (locale.value === "zh-CN" ? "创建并生成中..." : "Creating and generating..."))

const modeOptions = computed(() => [
  { value: "form", label: copy.value.formMode, icon: "📋" },
  { value: "chat", label: copy.value.chatMode, icon: "💬" }
])

function formatDateInputValue(value: Date): string {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, "0")
  const day = String(value.getDate()).padStart(2, "0")
  return `${year}-${month}-${day}`
}

function addDays(value: Date, days: number): Date {
  const next = new Date(value)
  next.setDate(next.getDate() + days)
  return next
}

const todayIso = formatDateInputValue(new Date())

function createStarterTrip(): TripPreferenceInput {
  const today = new Date()
  const endDate = addDays(today, 4)
  return {
    title: "汕头海边慢游",
    origin: "广州",
    destination: "汕头",
    start_date: formatDateInputValue(today),
    end_date: formatDateInputValue(endDate),
    budget: 6800,
    travelers: 2,
    interests: ["美食", "城市漫步", "海边风景"],
    accommodation_preference: "靠近市区、方便步行觅食的酒店",
    pace: "balanced",
    transport_mode: "auto"
  }
}

function createBlankTrip(): TripPreferenceInput {
  return {
    title: "",
    origin: "",
    destination: "",
    start_date: "",
    end_date: "",
    budget: 0,
    travelers: 0,
    interests: [],
    accommodation_preference: "",
    pace: "",
    transport_mode: "auto"
  }
}

const form = reactive<TripPreferenceInput>(createStarterTrip())
const displayedDraftFields = computed(() => [
  { key: "title", label: copy.value.titleLabel, value: buildSuggestedTitle() },
  { key: "origin", label: copy.value.originLabel, value: form.origin.trim() },
  { key: "destination", label: copy.value.destinationLabel, value: form.destination.trim() },
  { key: "start_date", label: copy.value.startDateLabel, value: form.start_date },
  { key: "end_date", label: copy.value.endDateLabel, value: form.end_date },
  { key: "budget", label: copy.value.budgetLabel, value: form.budget > 0 ? String(form.budget) : "" },
  { key: "travelers", label: copy.value.travelersLabel, value: form.travelers > 0 ? String(form.travelers) : "" },
  { key: "pace", label: copy.value.paceLabel, value: paceLabel(form.pace) },
  { key: "transport_mode", label: copy.value.transportLabel, value: transportLabel(form.transport_mode) },
  { key: "interests", label: copy.value.interestsLabel, value: form.interests.join(", ") },
  { key: "accommodation_preference", label: copy.value.accommodationLabel, value: form.accommodation_preference.trim() }
])

const isDraftEmpty = computed(() => displayedDraftFields.value.every((field) => !field.value))

const completionPercentage = computed(() => {
  const fields = displayedDraftFields.value
  const filled = fields.filter((f) => !!f.value && f.value !== "—").length
  return Math.round((filled / fields.length) * 100)
})

const paceOptions = computed(() => [
  { value: "", label: locale.value === "zh-CN" ? "请选择" : "Select" },
  { value: "slow", label: t("common.pace.slow") },
  { value: "balanced", label: t("common.pace.balanced") },
  { value: "packed", label: t("common.pace.packed") }
])

const transportOptions = computed(() => [
  { value: "", label: locale.value === "zh-CN" ? "请选择" : "Select" },
  { value: "auto", label: t("common.transport.auto") },
  { value: "rail", label: t("common.transport.rail") },
  { value: "flight", label: t("common.transport.flight") },
  { value: "car", label: t("common.transport.car") },
  { value: "walking", label: t("common.transport.walking") },
  { value: "mixed", label: t("common.transport.mixed") }
])
function assignForm(nextValue: TripPreferenceInput) {
  form.title = nextValue.title
  form.origin = nextValue.origin
  form.destination = nextValue.destination
  form.start_date = nextValue.start_date
  form.end_date = nextValue.end_date
  form.budget = nextValue.budget
  form.travelers = nextValue.travelers
  form.interests = [...nextValue.interests]
  form.accommodation_preference = nextValue.accommodation_preference
  form.pace = nextValue.pace
  form.transport_mode = nextValue.transport_mode
}

function buildSuggestedTitle() {
  const destination = form.destination.trim()
  const origin = form.origin.trim()
  if (!destination) return ""
  if (locale.value === "zh-CN") {
    return origin ? `${origin}出发去${destination}` : `${destination}${copy.value.autoTitlePrefix}`
  }
  return origin ? `${destination} trip from ${origin}` : `${destination} ${copy.value.autoTitlePrefix}`
}

function ensureDerivedTitle() {
  if (form.title.trim().length >= 3 || !form.destination.trim()) return
  form.title = buildSuggestedTitle()
}

function clearDraft() {
  error.value = null
  readyToCreate.value = false
  assignForm(createBlankTrip())
  chatMessages.value = []
  chatInput.value = ""
}

function restoreStarterDraft() {
  error.value = null
  readyToCreate.value = true
  assignForm(createStarterTrip())
  chatMessages.value = []
  chatInput.value = ""
}

function updateInterests(value: string | number) {
  const str = String(value)
  form.interests = str
    .split(/,|，|、|\n/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function paceLabel(value: string): string {
  const key = `common.pace.${value}`
  const translated = t(key)
  return translated === key ? (value || "") : translated
}

function transportLabel(value: string): string {
  const key = `common.transport.${value}`
  const translated = t(key)
  return translated === key ? (value || "") : translated
}
function validateForm(): string | null {
  if (form.origin.trim().length < 2) return copy.value.validation.origin
  if (form.destination.trim().length < 2) return copy.value.validation.destination
  if (!form.start_date || !form.end_date) return copy.value.validation.datesRequired
  if (form.start_date < todayIso) return copy.value.validation.startDatePast
  if (form.end_date < form.start_date) return copy.value.validation.datesRange
  if (form.budget <= 0) return copy.value.validation.budget
  if (form.travelers < 1) return copy.value.validation.travelers
  return null
}

async function requestChatTurn(userMessage?: string) {
  chatting.value = true
  error.value = null
  try {
    const response = await api.tripIntakeChat({
      draft: { ...form },
      messages: chatMessages.value,
      user_message: userMessage ?? null
    })
    assignForm(response.draft)
    readyToCreate.value = response.ready_to_create
    chatMessages.value.push({ role: "assistant", text: response.assistant_message })
  } catch (value) {
    error.value = getErrorMessage(value, copy.value.needsAttentionTitle)
  } finally {
    chatting.value = false
  }
}

function activateMode(nextMode: string) {
  const m = nextMode as "form" | "chat"
  mode.value = m
  if (m === "chat" && chatMessages.value.length === 0) {
    void requestChatTurn()
  }
}

async function submitConversationTurn() {
  const raw = chatInput.value.trim()
  if (!raw || chatting.value) return
  chatMessages.value.push({ role: "user", text: raw })
  chatInput.value = ""
  await requestChatTurn(raw)
}

async function submit() {
  error.value = validateForm()
  if (error.value) return
  submitting.value = true
  try {
    const trip = await api.createTrip({ ...form, title: buildSuggestedTitle() })
    await router.push({ path: `/trips/${trip.id}`, query: { entry: "create" } })
  } catch (value) {
    error.value = getErrorMessage(value, copy.value.needsAttentionTitle)
  } finally {
    submitting.value = false
  }
}

async function submitAndGenerate() {
  error.value = validateForm()
  if (error.value) return
  generating.value = true
  try {
    const trip = await api.createTrip({ ...form, title: buildSuggestedTitle() })
    const job = await api.generateTrip(trip.id)
    await router.push({
      path: `/trips/${trip.id}`,
      query: { entry: "create", autoGenerate: "1", jobId: job.job_id }
    })
  } catch (value) {
    error.value = getErrorMessage(value, copy.value.needsAttentionTitle)
  } finally {
    generating.value = false
  }
}
</script>

<template>
  <div class="tm-workbench">
    <!-- Header -->
    <header class="tm-workbench__header">
      <p class="tm-workbench__kicker">{{ copy.kicker }}</p>
      <h1 class="tm-workbench__title">{{ copy.title }}</h1>
      <p class="tm-workbench__desc">{{ copy.description }}</p>
    </header>

    <!-- Toolbar -->
    <div class="tm-workbench__toolbar">
      <TmSegmentedSwitch v-if="!isDemo" :options="modeOptions" :model-value="mode" @update:model-value="activateMode" />
      <div class="tm-workbench__toolbar-actions">
        <TmButton variant="ghost" size="sm" @click="restoreStarterDraft">{{ copy.starter }}</TmButton>
        <TmButton variant="ghost" size="sm" @click="clearDraft">{{ copy.clear }}</TmButton>
      </div>
    </div>

    <!-- Status notices -->
    <LlmStatusNotice compact />
    <StatePanel v-if="submitting" kind="loading" :title="copy.creatingTitle" :message="copy.creatingMessage" compact />
    <StatePanel v-if="generating" kind="loading" :title="copy.generatingTrip" :message="copy.creatingMessage" compact />
    <StatePanel v-if="chatting" kind="loading" :title="copy.chatLoadingTitle" :message="copy.chatLoadingMessage" compact />
    <StatePanel v-if="error" kind="error" :title="copy.needsAttentionTitle" :message="error" compact />

    <!-- Workbench body: 60/40 split -->
    <div class="tm-workbench__body">
      <!-- Left: main content area -->
      <div class="tm-workbench__main">
        <!-- Form mode -->
        <form v-if="mode === 'form'" class="tm-workbench__form" @submit.prevent="submit">
          <TmFieldGroup :title="locale === 'zh-CN' ? '行程基础' : 'Basics'">
            <TmField id="origin" :model-value="form.origin" :label="copy.originLabel" required :minlength="2" @update:model-value="(v: string | number) => form.origin = String(v)" />
            <TmField id="destination" :model-value="form.destination" :label="copy.destinationLabel" required :minlength="2" @update:model-value="(v: string | number) => form.destination = String(v)" />
            <TmField id="start-date" type="date" :model-value="form.start_date" :label="copy.startDateLabel" :min="todayIso" required @update:model-value="(v: string | number) => form.start_date = String(v)" />
            <TmField id="end-date" type="date" :model-value="form.end_date" :label="copy.endDateLabel" :min="form.start_date || todayIso" required @update:model-value="(v: string | number) => form.end_date = String(v)" />
          </TmFieldGroup>

          <TmFieldGroup :title="locale === 'zh-CN' ? '预算与人数' : 'Budget & Travelers'">
            <TmField id="budget" type="number" :model-value="form.budget" :label="copy.budgetLabel" min="0" required @update:model-value="(v: string | number) => form.budget = Number(v)" />
            <TmField id="travelers" type="number" :model-value="form.travelers" :label="copy.travelersLabel" min="1" required @update:model-value="(v: string | number) => form.travelers = Number(v)" />
          </TmFieldGroup>

          <TmFieldGroup :title="locale === 'zh-CN' ? '节奏与交通' : 'Pace & Transport'">
            <TmSelect id="pace" :model-value="form.pace" :label="copy.paceLabel" :options="paceOptions" @update:model-value="(v: string) => form.pace = v" />
            <TmSelect id="transport-mode" :model-value="form.transport_mode" :label="copy.transportLabel" :hint="locale === 'zh-CN' ? '自动选择会比较铁路、飞机的费用、全程耗时与接驳；票价和余票以购票平台为准。' : 'Automatic compares rail and flights by cost, total journey time and transfers. Confirm fares and availability with the booking provider.'" :options="transportOptions" @update:model-value="(v: string) => form.transport_mode = v" />
          </TmFieldGroup>

          <TmFieldGroup :title="locale === 'zh-CN' ? '偏好与住宿' : 'Preferences'">
            <div class="tm-workbench__field-full">
              <TmField id="interests" :model-value="form.interests.join(', ')" :label="copy.interestsLabel" :placeholder="copy.interestsPlaceholder" @update:model-value="updateInterests" />
            </div>
            <div class="tm-workbench__field-full">
              <TmTextarea id="accommodation" :model-value="form.accommodation_preference" :label="copy.accommodationLabel" :rows="3" @update:model-value="(v: string) => form.accommodation_preference = v" />
            </div>
          </TmFieldGroup>

          <!-- Action rail -->
          <div class="tm-workbench__actions">
            <TmButton variant="primary" type="submit" :loading="submitting" :disabled="submitting">{{ submitting ? copy.creatingTrip : copy.createTrip }}</TmButton>
            <TmButton variant="ai" :loading="generating" :disabled="generating" @click="submitAndGenerate">{{ generating ? copy.generatingTrip : copy.generateTrip }}</TmButton>
            <p class="tm-workbench__actions-hint">{{ copy.nextStepNote }}</p>
          </div>
        </form>
        <!-- Chat mode -->
        <TmAuroraPanel v-else :active="chatting" :completed="readyToCreate">
          <div class="tm-workbench__chat-header">
            <h2 class="tm-workbench__chat-title">{{ copy.intakeTitle }}</h2>
            <p class="tm-workbench__chat-desc">{{ copy.intakeDescription }}</p>
          </div>

          <div class="tm-workbench__chat-messages">
            <div
              v-for="(message, index) in chatMessages"
              :key="`${message.role}-${index}`"
              :class="['tm-workbench__chat-bubble', `tm-workbench__chat-bubble--${message.role}`]"
            >
              <span class="tm-workbench__chat-role">{{ message.role === 'assistant' ? copy.assistantLabel : copy.userLabel }}</span>
              <p class="tm-workbench__chat-text">{{ message.text }}</p>
            </div>
          </div>

          <div class="tm-workbench__chat-input">
            <TmTextarea
              id="chat-intake"
              :model-value="chatInput"
              :label="copy.chatInputLabel"
              :placeholder="copy.chatInputPlaceholder"
              :rows="3"
              @update:model-value="(v: string) => chatInput = v"
            />
            <div class="tm-workbench__chat-actions">
              <TmButton variant="primary" :disabled="chatting" @click="submitConversationTurn">{{ copy.send }}</TmButton>
              <TmButton variant="ai" :disabled="submitting || generating || !readyToCreate" :loading="generating" @click="submitAndGenerate">
                {{ generating ? chatGeneratingLabel : chatGenerateLabel }}
              </TmButton>
            </div>
          </div>
        </TmAuroraPanel>
      </div>

      <!-- Right: sticky summary sidebar -->
      <aside class="tm-workbench__sidebar">
        <div class="tm-workbench__sidebar-inner">
          <h2 class="tm-workbench__sidebar-title">{{ buildSuggestedTitle() || copy.collectedTitle }}</h2>
          <p class="tm-workbench__sidebar-hint">{{ readyToCreate ? copy.readyMessage : copy.nextStepNote }}</p>


          <TmProgressTrack
            :value="completionPercentage"
            :label="locale === 'zh-CN' ? '完成度' : 'Completeness'"
            :variant="chatting ? 'aurora' : 'default'"
          />

          <StatePanel v-if="isDraftEmpty" kind="empty" :title="copy.collectedTitle" :message="copy.collectedEmpty" compact />

          <dl v-else class="tm-workbench__draft-list">
            <div v-for="field in displayedDraftFields" :key="field.key" class="tm-workbench__draft-item">
              <dt>{{ field.label }}</dt>
              <dd>{{ field.value || "—" }}</dd>
            </div>
          </dl>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.tm-workbench { max-width: 1120px; margin: 0 auto; }

.tm-workbench__header { margin-bottom: var(--tm-space-6); }
.tm-workbench__kicker { font-size: var(--tm-text-xs); font-weight: 800; text-transform: uppercase; letter-spacing: 0.15em; color: var(--tm-clay); margin: 0 0 var(--tm-space-2) 0; }
.tm-workbench__title { font-family: var(--tm-font-display); font-size: var(--tm-text-2xl); color: var(--tm-moss); margin: 0 0 var(--tm-space-2) 0; }
.tm-workbench__desc { font-size: var(--tm-text-sm); color: var(--tm-stone); line-height: var(--tm-leading-relaxed); margin: 0; }

.tm-workbench__toolbar { display: flex; align-items: center; justify-content: space-between; gap: var(--tm-space-4); margin-bottom: var(--tm-space-6); flex-wrap: wrap; }
.tm-workbench__toolbar-actions { display: flex; gap: var(--tm-space-2); }

.tm-workbench__body { display: grid; grid-template-columns: 1fr 380px; gap: var(--tm-space-8); align-items: start; }
.tm-workbench__main { min-width: 0; }
.tm-workbench__form { display: flex; flex-direction: column; }
.tm-workbench__field-full { grid-column: 1 / -1; }

.tm-workbench__actions { display: flex; align-items: center; gap: var(--tm-space-4); flex-wrap: wrap; padding-top: var(--tm-space-4); border-top: var(--tm-border-hairline); }
.tm-workbench__actions-hint { font-size: var(--tm-text-xs); color: var(--tm-stone); margin: 0; flex-basis: 100%; }

.tm-workbench__chat-header { margin-bottom: var(--tm-space-4); }
.tm-workbench__chat-title { font-size: var(--tm-text-lg); font-weight: 700; color: var(--tm-tea); margin: 0 0 var(--tm-space-2) 0; }
.tm-workbench__chat-desc { font-size: var(--tm-text-sm); color: var(--tm-stone); margin: 0; }
.tm-workbench__chat-messages { display: flex; flex-direction: column; gap: var(--tm-space-3); max-height: 400px; overflow-y: auto; padding: var(--tm-space-4) 0; }
.tm-workbench__chat-bubble { padding: var(--tm-space-3) var(--tm-space-4); border-radius: var(--tm-radius-lg); }
.tm-workbench__chat-bubble--assistant { background-color: var(--tm-mist); border: 1px dashed rgba(43, 42, 40, 0.1); }
.tm-workbench__chat-bubble--user { background-color: rgba(255, 255, 255, 0.7); border: var(--tm-border-subtle); }
.tm-workbench__chat-role { display: block; font-size: var(--tm-text-xs); font-weight: 800; text-transform: uppercase; letter-spacing: 0.1em; color: var(--tm-clay); margin-bottom: var(--tm-space-1); }
.tm-workbench__chat-text { font-size: var(--tm-text-sm); color: var(--tm-tea); line-height: var(--tm-leading-normal); margin: 0; }
.tm-workbench__chat-input { margin-top: var(--tm-space-4); padding-top: var(--tm-space-4); border-top: var(--tm-border-hairline); }
.tm-workbench__chat-actions { display: flex; gap: var(--tm-space-3); margin-top: var(--tm-space-3); }

.tm-workbench__sidebar { position: sticky; top: calc(var(--tm-topbar-height, 72px) + var(--tm-space-6)); }
.tm-workbench__sidebar-inner { padding: var(--tm-space-6); border-radius: var(--tm-radius-xl); background-color: var(--tm-snow); border: var(--tm-border-subtle); box-shadow: var(--tm-shadow-card); display: flex; flex-direction: column; gap: var(--tm-space-4); }
.tm-workbench__sidebar-title { font-size: var(--tm-text-lg); font-weight: 700; color: var(--tm-tea); margin: 0; }
.tm-workbench__sidebar-hint { font-size: var(--tm-text-xs); color: var(--tm-stone); margin: 0; }

.tm-workbench__draft-list { display: grid; gap: var(--tm-space-3); margin: 0; padding: 0; }
.tm-workbench__draft-item { display: flex; flex-direction: column; gap: 2px; }
.tm-workbench__draft-item dt { font-size: var(--tm-text-xs); font-weight: 700; color: var(--tm-stone); text-transform: uppercase; letter-spacing: 0.05em; }
.tm-workbench__draft-item dd { font-size: var(--tm-text-sm); color: var(--tm-tea); margin: 0; }

@media (max-width: 1024px) {
  .tm-workbench__body { grid-template-columns: 1fr 320px; gap: var(--tm-space-6); }
}
@media (max-width: 768px) {
  .tm-workbench__body { grid-template-columns: 1fr; }
  .tm-workbench__sidebar { position: static; order: -1; }
  .tm-workbench__toolbar { flex-direction: column; align-items: stretch; }
}
</style>
