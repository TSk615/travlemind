<script setup lang="ts">
import { computed, reactive, ref } from "vue"
import { useRouter } from "vue-router"
import type { TripPreferenceInput } from "@travelmind/shared-types"
import LlmStatusNotice from "@/components/LlmStatusNotice.vue"
import StatePanel from "@/components/StatePanel.vue"
import { api, getErrorMessage } from "@/lib/api"
import { useI18n } from "@/lib/useI18n"

const router = useRouter()
const submitting = ref(false)
const error = ref<string | null>(null)
const { locale, t } = useI18n()

const flowCopy = computed(() =>
  locale.value === "zh-CN"
    ? {
        creatingMessage: "正在保存行程 Brief。下一页会直接带你进入行程详情，你再手动触发生成，不会自动调用规划任务。",
        nextStepNote: "创建 trip 只会保存 Brief；下一步是在详情页点击“生成行程”，正式进入攻略生成链路。"
      }
    : {
        creatingMessage: "Saving the trip brief now. The next screen will land on trip detail, where you explicitly start generation.",
        nextStepNote: "Create trip only saves the brief; the next step is Generate itinerary on the trip detail page."
      }
)

function createStarterTrip(): TripPreferenceInput {
  return {
    title: "Spring Kyoto reset",
    destination: "Kyoto",
    start_date: "2026-04-14",
    end_date: "2026-04-18",
    budget: 6800,
    travelers: 2,
    interests: ["temples", "coffee", "quiet neighborhoods"],
    accommodation_preference: "Boutique hotel near transit",
    pace: "balanced",
    transport_mode: "rail"
  }
}

function createBlankTrip(): TripPreferenceInput {
  return {
    title: "",
    destination: "",
    start_date: "",
    end_date: "",
    budget: 0,
    travelers: 1,
    interests: [],
    accommodation_preference: "",
    pace: "balanced",
    transport_mode: "mixed"
  }
}

const form = reactive<TripPreferenceInput>(createStarterTrip())

const isDraftEmpty = computed(() => {
  return !form.title.trim() && !form.destination.trim() && !form.start_date && !form.end_date && form.interests.length === 0
})

const paceOptions = computed(() => [
  { value: "slow", label: t("common.pace.slow") },
  { value: "balanced", label: t("common.pace.balanced") },
  { value: "packed", label: t("common.pace.packed") }
])

const transportOptions = computed(() => [
  { value: "rail", label: t("common.transport.rail") },
  { value: "car", label: t("common.transport.car") },
  { value: "walking", label: t("common.transport.walking") },
  { value: "mixed", label: t("common.transport.mixed") }
])

function assignForm(nextValue: TripPreferenceInput) {
  form.title = nextValue.title
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

function clearDraft() {
  error.value = null
  assignForm(createBlankTrip())
}

function restoreStarterDraft() {
  error.value = null
  assignForm(createStarterTrip())
}

function updateInterests(value: string) {
  form.interests = value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
}

function onInterestsInput(event: Event) {
  updateInterests((event.target as HTMLInputElement).value)
}

function validateForm(): string | null {
  if (form.title.trim().length < 3) {
    return t("tripForm.validation.title")
  }

  if (form.destination.trim().length < 2) {
    return t("tripForm.validation.destination")
  }

  if (!form.start_date || !form.end_date) {
    return t("tripForm.validation.datesRequired")
  }

  if (form.end_date < form.start_date) {
    return t("tripForm.validation.datesRange")
  }

  if (form.budget <= 0) {
    return t("tripForm.validation.budget")
  }

  if (form.travelers < 1) {
    return t("tripForm.validation.travelers")
  }

  return null
}

async function submit() {
  error.value = validateForm()
  if (error.value) {
    return
  }

  submitting.value = true
  try {
    const trip = await api.createTrip(form)
    await router.push({ path: `/trips/${trip.id}`, query: { entry: "create" } })
  } catch (value) {
    error.value = getErrorMessage(value, t("tripForm.needsAttentionTitle"))
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="page-grid" style="max-width: 1080px; margin: 0 auto;">
    <article class="panel panel-stack">
      <div class="form-toolbar">
        <div>
          <p class="kicker">{{ t('tripForm.kicker') }}</p>
          <h1>{{ t('tripForm.title') }}</h1>
          <p class="muted">{{ t('tripForm.description') }}</p>
        </div>
        <div class="inline-actions">
          <button type="button" @click="restoreStarterDraft">{{ t('common.useStarterBrief') }}</button>
          <button type="button" @click="clearDraft">{{ t('common.clearForm') }}</button>
        </div>
      </div>

      <LlmStatusNotice compact />

      <StatePanel
        v-if="submitting"
        kind="loading"
        :title="t('tripForm.creatingTitle')"
        :message="flowCopy.creatingMessage"
        compact
      />

      <StatePanel
        v-if="error"
        kind="error"
        :title="t('tripForm.needsAttentionTitle')"
        :message="error"
        compact
      />

      <StatePanel
        v-if="isDraftEmpty"
        kind="empty"
        :title="t('tripForm.blankTitle')"
        :message="t('tripForm.blankMessage')"
        compact
      >
        <template #actions>
          <button class="primary" type="button" @click="restoreStarterDraft">{{ t('common.loadStarterBrief') }}</button>
        </template>
      </StatePanel>

      <form class="form-grid" @submit.prevent="submit">
        <div class="field">
          <label for="title">{{ t('tripForm.titleLabel') }}</label>
          <input id="title" v-model="form.title" required minlength="3" />
        </div>
        <div class="field">
          <label for="destination">{{ t('tripForm.destinationLabel') }}</label>
          <input id="destination" v-model="form.destination" required minlength="2" />
        </div>
        <div class="field">
          <label for="start-date">{{ t('tripForm.startDateLabel') }}</label>
          <input id="start-date" v-model="form.start_date" type="date" required />
        </div>
        <div class="field">
          <label for="end-date">{{ t('tripForm.endDateLabel') }}</label>
          <input id="end-date" v-model="form.end_date" type="date" required />
        </div>
        <div class="field">
          <label for="budget">{{ t('tripForm.budgetLabel') }}</label>
          <input id="budget" v-model.number="form.budget" type="number" min="0" required />
        </div>
        <div class="field">
          <label for="travelers">{{ t('tripForm.travelersLabel') }}</label>
          <input id="travelers" v-model.number="form.travelers" type="number" min="1" required />
        </div>
        <div class="field">
          <label for="pace">{{ t('tripForm.paceLabel') }}</label>
          <select id="pace" v-model="form.pace">
            <option v-for="option in paceOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </div>
        <div class="field">
          <label for="transport-mode">{{ t('tripForm.transportLabel') }}</label>
          <select id="transport-mode" v-model="form.transport_mode">
            <option v-for="option in transportOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </div>
        <div class="field field--full">
          <label for="interests">{{ t('tripForm.interestsLabel') }}</label>
          <input id="interests" :value="form.interests.join(', ')" :placeholder="t('tripForm.interestsPlaceholder')" @input="onInterestsInput" />
        </div>
        <div class="field field--full">
          <label for="accommodation">{{ t('tripForm.accommodationLabel') }}</label>
          <textarea id="accommodation" v-model="form.accommodation_preference"></textarea>
        </div>
        <div class="field field--full inline-actions">
          <button class="primary" :disabled="submitting" type="submit">{{ submitting ? t('tripForm.creatingTrip') : t('tripForm.createTrip') }}</button>
          <p class="muted">{{ flowCopy.nextStepNote }}</p>
        </div>
      </form>
    </article>
  </section>
</template>
