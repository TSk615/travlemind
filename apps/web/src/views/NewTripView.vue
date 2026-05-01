<script setup lang="ts">
import { computed, reactive, ref } from "vue"
import { useRouter } from "vue-router"
import type { TripPreferenceInput } from "@travelmind/shared-types"
import LlmStatusNotice from "@/components/LlmStatusNotice.vue"
import StatePanel from "@/components/StatePanel.vue"
import { api, getErrorMessage } from "@/lib/api"
import type { TripIntakeChatMessage } from "@/lib/api"
import { useI18n } from "@/lib/useI18n"

const router = useRouter()
const submitting = ref(false)
const generating = ref(false)
const chatting = ref(false)
const error = ref<string | null>(null)
const mode = ref<"form" | "chat">("form")
const chatInput = ref("")
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
    title: "京都春日慢游",
    origin: "广州",
    destination: "汕头",
    start_date: formatDateInputValue(today),
    end_date: formatDateInputValue(endDate),
    budget: 6800,
    travelers: 2,
    interests: ["美食", "城市漫步", "海边风景"],
    accommodation_preference: "靠近市区、方便步行觅食的酒店",
    pace: "balanced",
    transport_mode: "rail"
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
    transport_mode: ""
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

const paceOptions = computed(() => [
  { value: "", label: locale.value === "zh-CN" ? "请选择" : "Select" },
  { value: "slow", label: t("common.pace.slow") },
  { value: "balanced", label: t("common.pace.balanced") },
  { value: "packed", label: t("common.pace.packed") }
])

const transportOptions = computed(() => [
  { value: "", label: locale.value === "zh-CN" ? "请选择" : "Select" },
  { value: "rail", label: t("common.transport.rail") },
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
  if (!destination) {
    return ""
  }
  if (locale.value === "zh-CN") {
    return origin ? `${origin}出发去${destination}` : `${destination}${copy.value.autoTitlePrefix}`
  }
  return origin ? `${destination} trip from ${origin}` : `${destination} ${copy.value.autoTitlePrefix}`
}

function ensureDerivedTitle() {
  if (form.title.trim().length >= 3 || !form.destination.trim()) {
    return
  }
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

function updateInterests(value: string) {
  form.interests = value
    .split(/,|，|、|\n/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function onInterestsInput(event: Event) {
  updateInterests((event.target as HTMLInputElement).value)
}

function paceLabel(value: string): string {
  const key = `common.pace.${value}`
  const translated = t(key)
  return translated === key ? (value || "—") : translated
}

function transportLabel(value: string): string {
  const key = `common.transport.${value}`
  const translated = t(key)
  return translated === key ? (value || "—") : translated
}

function validateForm(): string | null {
  if (form.origin.trim().length < 2) {
    return copy.value.validation.origin
  }
  if (form.destination.trim().length < 2) {
    return copy.value.validation.destination
  }
  if (!form.start_date || !form.end_date) {
    return copy.value.validation.datesRequired
  }
  if (form.start_date < todayIso) {
    return copy.value.validation.startDatePast
  }
  if (form.end_date < form.start_date) {
    return copy.value.validation.datesRange
  }
  if (form.budget <= 0) {
    return copy.value.validation.budget
  }
  if (form.travelers < 1) {
    return copy.value.validation.travelers
  }
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

function activateMode(nextMode: "form" | "chat") {
  mode.value = nextMode
  if (nextMode === "chat" && chatMessages.value.length === 0) {
    void requestChatTurn()
  }
}

async function submitConversationTurn() {
  const raw = chatInput.value.trim()
  if (!raw || chatting.value) {
    return
  }
  chatMessages.value.push({ role: "user", text: raw })
  chatInput.value = ""
  await requestChatTurn(raw)
}

async function submit() {
  error.value = validateForm()
  if (error.value) {
    return
  }

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
  if (error.value) {
    return
  }

  generating.value = true
  try {
    const trip = await api.createTrip({ ...form, title: buildSuggestedTitle() })
    const job = await api.generateTrip(trip.id)
    await router.push({
      path: `/trips/${trip.id}`,
      query: {
        entry: "create",
        autoGenerate: "1",
        jobId: job.job_id,
      },
    })
  } catch (value) {
    error.value = getErrorMessage(value, copy.value.needsAttentionTitle)
  } finally {
    generating.value = false
  }
}
</script>

<template>
  <section class="page-grid" style="max-width: 1120px; margin: 0 auto;">
    <article class="panel panel-stack">
      <div class="form-toolbar">
        <div>
          <p class="kicker">{{ copy.kicker }}</p>
          <h1>{{ copy.title }}</h1>
          <p class="muted">{{ copy.description }}</p>
        </div>
        <div class="inline-actions">
          <button type="button" @click="restoreStarterDraft">{{ copy.starter }}</button>
          <button type="button" @click="clearDraft">{{ copy.clear }}</button>
        </div>
      </div>

      <LlmStatusNotice compact />
      <StatePanel v-if="submitting" kind="loading" :title="copy.creatingTitle" :message="copy.creatingMessage" compact />
      <StatePanel v-if="generating" kind="loading" :title="chatGeneratingLabel" :message="copy.creatingMessage" compact />
      <StatePanel v-if="chatting" kind="loading" :title="copy.chatLoadingTitle" :message="copy.chatLoadingMessage" compact />
      <StatePanel v-if="error" kind="error" :title="copy.needsAttentionTitle" :message="error" compact />
      <StatePanel v-if="isDraftEmpty" kind="empty" :title="copy.blankTitle" :message="copy.blankMessage" compact />

      <div class="panel-subsection">
        <p class="kicker">{{ copy.modeHint }}</p>
        <div class="inline-actions">
          <button :class="mode === 'form' ? 'primary' : ''" type="button" @click="activateMode('form')">{{ copy.formMode }}</button>
          <button :class="mode === 'chat' ? 'primary' : ''" type="button" @click="activateMode('chat')">{{ copy.chatMode }}</button>
        </div>
      </div>

      <div class="workspace-layout">
        <div class="workspace-column">
          <form v-if="mode === 'form'" class="form-grid" @submit.prevent="submit">
            <div class="field">
              <label for="origin">{{ copy.originLabel }}</label>
              <input id="origin" v-model="form.origin" required minlength="2" />
            </div>
            <div class="field">
              <label for="destination">{{ copy.destinationLabel }}</label>
              <input id="destination" v-model="form.destination" required minlength="2" />
            </div>
            <div class="field">
              <label for="start-date">{{ copy.startDateLabel }}</label>
              <input id="start-date" v-model="form.start_date" type="date" :min="todayIso" required />
            </div>
            <div class="field">
              <label for="end-date">{{ copy.endDateLabel }}</label>
              <input id="end-date" v-model="form.end_date" type="date" :min="form.start_date || todayIso" required />
            </div>
            <div class="field">
              <label for="budget">{{ copy.budgetLabel }}</label>
              <input id="budget" v-model.number="form.budget" type="number" min="0" required />
            </div>
            <div class="field">
              <label for="travelers">{{ copy.travelersLabel }}</label>
              <input id="travelers" v-model.number="form.travelers" type="number" min="1" required />
            </div>
            <div class="field">
              <label for="pace">{{ copy.paceLabel }}</label>
              <select id="pace" v-model="form.pace">
                <option v-for="option in paceOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </div>
            <div class="field">
              <label for="transport-mode">{{ copy.transportLabel }}</label>
              <select id="transport-mode" v-model="form.transport_mode">
                <option v-for="option in transportOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </div>
            <div class="field field--full">
              <label for="interests">{{ copy.interestsLabel }}</label>
              <input id="interests" :value="form.interests.join(', ')" :placeholder="copy.interestsPlaceholder" @input="onInterestsInput" />
            </div>
            <div class="field field--full">
              <label for="accommodation">{{ copy.accommodationLabel }}</label>
              <textarea id="accommodation" v-model="form.accommodation_preference"></textarea>
            </div>
            <div class="field field--full inline-actions">
              <button class="primary" :disabled="submitting" type="submit">{{ submitting ? copy.creatingTrip : copy.createTrip }}</button>
              <p class="muted">{{ copy.nextStepNote }}</p>
            </div>
          </form>

          <article v-else class="panel panel-stack">
            <div>
              <p class="kicker">{{ copy.chatMode }}</p>
              <h2>{{ copy.intakeTitle }}</h2>
              <p class="muted">{{ copy.intakeDescription }}</p>
            </div>

            <div class="panel-subsection" style="display: grid; gap: 12px; max-height: 420px; overflow: auto;">
              <article
                v-for="(message, index) in chatMessages"
                :key="`${message.role}-${index}`"
                class="panel-subsection"
                :style="message.role === 'assistant' ? 'border-style:dashed;' : 'background: rgba(255,255,255,0.7);'"
              >
                <p class="kicker">{{ message.role === 'assistant' ? copy.assistantLabel : copy.userLabel }}</p>
                <p>{{ message.text }}</p>
              </article>
            </div>

            <div class="field field--full">
              <label for="chat-intake">{{ copy.chatInputLabel }}</label>
              <textarea id="chat-intake" v-model="chatInput" :placeholder="copy.chatInputPlaceholder"></textarea>
            </div>

            <div class="inline-actions">
              <button class="primary" type="button" :disabled="chatting" @click="submitConversationTurn">{{ copy.send }}</button>
              <button type="button" :disabled="submitting || generating || !readyToCreate" @click="submitAndGenerate">{{ generating ? chatGeneratingLabel : chatGenerateLabel }}</button>
            </div>
          </article>
        </div>

        <div class="workspace-column">
          <article class="panel panel-stack">
            <div>
              <p class="kicker">{{ copy.collectedTitle }}</p>
              <h2>{{ buildSuggestedTitle() || copy.collectedTitle }}</h2>
              <p class="muted">{{ readyToCreate ? copy.readyMessage : copy.nextStepNote }}</p>
            </div>

            <StatePanel v-if="displayedDraftFields.every((field) => !field.value)" kind="empty" :title="copy.collectedTitle" :message="copy.collectedEmpty" compact />

            <dl v-else class="data-grid">
              <div v-for="field in displayedDraftFields" :key="field.key" class="data-pair">
                <dt>{{ field.label }}</dt>
                <dd>{{ field.value || '—' }}</dd>
              </div>
            </dl>
          </article>
        </div>
      </div>
    </article>
  </section>
</template>
