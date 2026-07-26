<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue"
import type { ImageGenerationRecord, ImageGenerationStatus, ImageVisibility } from "@travelmind/shared-types"
import StatePanel from "@/components/StatePanel.vue"
import StatusPill from "@/components/StatusPill.vue"
import { ApiError, api, getErrorMessage, type JobRecord } from "@/lib/api"
import { formatDateTime } from "@/lib/format"
import { isJobActive } from "@/lib/jobStatus"
import { useI18n } from "@/lib/useI18n"
import { useLlmSettingsStore } from "@/stores/llmSettings"

const settingsStore = useLlmSettingsStore()
void settingsStore.bootstrap()

const { locale } = useI18n()
const loading = ref(true)
const feedLoading = ref(true)
const generatePending = ref(false)
const composePending = ref(false)
const pendingVisibilityId = ref<string | null>(null)
const activeJob = ref<JobRecord | null>(null)
const lastGenerated = ref<ImageGenerationRecord | null>(null)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const composeError = ref<string | null>(null)
const generateError = ref<string | null>(null)
const sourcePreviewUrl = ref<string | null>(null)
const sourceFile = ref<File | null>(null)
const referenceFiles = ref<File[]>([])
const feedRecords = ref<ImageGenerationRecord[]>([])
const myRecords = ref<ImageGenerationRecord[]>([])
let pollTimer: number | null = null

const filters = reactive<{
  mode: "" | "text_to_image" | "image_to_image"
  status: "" | ImageGenerationStatus
  visibility: "" | ImageVisibility
}>({
  mode: "",
  status: "",
  visibility: ""
})

const form = reactive({
  prompt: "",
  optimized_prompt: "",
  negative_prompt: "",
  mode: "text_to_image" as "text_to_image" | "image_to_image",
  visibility: "private" as ImageVisibility,
  reference_urls_input: ""
})

const enCopy = {
  title: "AI Image Studio",
  description: "Create travel visuals, publish prompt-backed assets, and remix what works.",
  createTitle: "Create",
  createHint: "Use text-to-image or image-to-image. Prompt optimization uses your text model; final generation uses your image model.",
  feedTitle: "Explore",
  feedHint: "Public assets published inside TravelMind. Sorted by remix count first.",
  libraryTitle: "My Library",
  libraryHint: "Your private and public image history.",
  trendsTitle: "Prompt trends",
  trendsMessage: "Platform trend endpoints are reserved but not implemented yet.",
  missingImageConfigTitle: "Image model settings are incomplete",
  missingImageConfigMessage: "Add base URL, API key, model, and provider in Settings before running image generation jobs.",
  titleLabel: "Title",
  destinationLabel: "Destination",
  sceneLabel: "Scene prompt",
  tagsLabel: "Style tags",
  tagsPlaceholder: "cinematic, light travel, summer, editorial",
  promptLabel: "Base prompt",
  optimizedPromptLabel: "Optimized prompt",
  negativePromptLabel: "Negative prompt",
  modeLabel: "Mode",
  visibilityLabel: "Visibility",
  sourceLabel: "Source image",
  referenceFilesLabel: "Reference files",
  referenceUrlsLabel: "Reference URLs",
  optimize: "Optimize prompt",
  optimizing: "Optimizing...",
  generate: "Generate",
  generating: "Generating...",
  refresh: "Refresh",
  loadToForm: "Use in creator",
  remix: "Remix",
  copyPrompt: "Copy prompt",
  makePublic: "Publish",
  makePrivate: "Make private",
  emptyFeedTitle: "No public images yet",
  emptyFeedMessage: "Publish a generation to seed the public feed.",
  emptyLibraryTitle: "No image history yet",
  emptyLibraryMessage: "Create your first travel visual from the form on the left.",
  latestTitle: "Latest result",
  latestMessage: "The most recent generation result is shown here after the job completes.",
  composeFailed: "Unable to optimize prompt",
  generateFailed: "Unable to generate image",
  listFailed: "Unable to load image records",
  filtersMode: "Filter mode",
  filtersStatus: "Filter status",
  filtersVisibility: "Filter visibility",
  publicLabel: "Public",
  privateLabel: "Private",
  statusDraft: "Draft",
  statusQueued: "Queued",
  statusRunning: "Running",
  statusCompleted: "Completed",
  statusFailed: "Failed",
  sourceRequired: "Image-to-image requires one uploaded source image.",
  copied: "Prompt copied.",
  noPrompt: "No prompt available to copy.",
  trendSoon: "Coming soon"
}

const zhCopy = {
  title: "AI 生图工作台",
  description: "创建旅行视觉内容、发布提示词资产，并在站内 remix 已验证有效的作品。",
  createTitle: "创作区",
  createHint: "支持文生图和图生图。提示词优化使用文本模型，最终出图使用图片模型。",
  feedTitle: "公开流",
  feedHint: "站内公开素材流，按 remix 数优先排序。",
  libraryTitle: "我的素材库",
  libraryHint: "查看自己的私有和公开生图记录。",
  trendsTitle: "热点提示词",
  trendsMessage: "平台热点接口已预留，当前版本仅保留占位。",
  missingImageConfigTitle: "图片模型设置不完整",
  missingImageConfigMessage: "请先在设置页补齐图片模型的 base URL、API key、model 和 provider。",
  titleLabel: "标题",
  destinationLabel: "目的地",
  sceneLabel: "场景描述",
  tagsLabel: "风格标签",
  tagsPlaceholder: "电影感, 度假风, 夏日, editorial",
  promptLabel: "基础提示词",
  optimizedPromptLabel: "优化后提示词",
  negativePromptLabel: "负向提示词",
  modeLabel: "生成模式",
  visibilityLabel: "可见性",
  sourceLabel: "源图",
  referenceFilesLabel: "参考图文件",
  referenceUrlsLabel: "参考图 URL",
  optimize: "优化提示词",
  optimizing: "优化中...",
  generate: "开始生成",
  generating: "生成中...",
  refresh: "刷新",
  loadToForm: "载入创作区",
  remix: "Remix",
  copyPrompt: "复制提示词",
  makePublic: "发布公开",
  makePrivate: "设为私有",
  emptyFeedTitle: "还没有公开素材",
  emptyFeedMessage: "发布一条生成记录后，这里会出现公开卡片。",
  emptyLibraryTitle: "还没有生成历史",
  emptyLibraryMessage: "先从左侧表单创建第一张旅行图。",
  latestTitle: "最近结果",
  latestMessage: "最近一次完成的生成结果会显示在这里。",
  composeFailed: "提示词优化失败",
  generateFailed: "图片生成失败",
  listFailed: "图片记录加载失败",
  filtersMode: "筛选模式",
  filtersStatus: "筛选状态",
  filtersVisibility: "筛选可见性",
  publicLabel: "公开",
  privateLabel: "私有",
  statusDraft: "草稿",
  statusQueued: "排队中",
  statusRunning: "生成中",
  statusCompleted: "已完成",
  statusFailed: "失败",
  sourceRequired: "图生图必须上传一张源图。",
  copied: "提示词已复制。",
  noPrompt: "没有可复制的提示词。",
  trendSoon: "即将上线"
}

const copy = computed(() => (locale.value === "zh-CN" ? zhCopy : enCopy))

const sourceFileName = computed(() => sourceFile.value?.name ?? "")
const referenceFileNames = computed(() => referenceFiles.value.map((item) => item.name))
const referenceUrls = computed(() =>
  form.reference_urls_input
    .split(/,|\n/)
    .map((value) => value.trim())
    .filter(Boolean)
)
const latestPrompt = computed(() => lastGenerated.value?.optimized_prompt || lastGenerated.value?.prompt || "")

function clearPollTimer() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

function revokeSourcePreview() {
  if (sourcePreviewUrl.value) {
    URL.revokeObjectURL(sourcePreviewUrl.value)
    sourcePreviewUrl.value = null
  }
}

function applyRecordToForm(record: ImageGenerationRecord) {
  form.prompt = record.prompt
  form.optimized_prompt = record.optimized_prompt ?? ""
  form.negative_prompt = record.negative_prompt ?? ""
  form.mode = record.mode
  form.visibility = record.visibility
  form.reference_urls_input = record.reference_images.map((item) => item.url).join("\n")
  referenceFiles.value = []
  sourceFile.value = null
  revokeSourcePreview()
}

function summarizePrompt(text: string, fallback: string) {
  const normalized = text.trim()
  if (!normalized) {
    return fallback
  }
  return normalized.length > 88 ? `${normalized.slice(0, 88)}...` : normalized
}

function formatVisibility(value: ImageVisibility): string {
  return value === "public" ? copy.value.publicLabel : copy.value.privateLabel
}

function formatStatus(value: ImageGenerationStatus): string {
  switch (value) {
    case "draft":
      return copy.value.statusDraft
    case "queued":
      return copy.value.statusQueued
    case "running":
      return copy.value.statusRunning
    case "completed":
      return copy.value.statusCompleted
    case "failed":
      return copy.value.statusFailed
    default:
      return value
  }
}

async function loadFeed() {
  feedLoading.value = true
  try {
    feedRecords.value = await api.listImageFeed()
  } finally {
    feedLoading.value = false
  }
}

async function loadLibrary() {
  loading.value = true
  error.value = null
  try {
    myRecords.value = await api.listImages({
      mode: filters.mode || undefined,
      status: filters.status || undefined,
      visibility: filters.visibility || undefined
    })
  } catch (value) {
    error.value = getErrorMessage(value, copy.value.listFailed)
  } finally {
    loading.value = false
  }
}

async function refreshAll() {
  await Promise.all([loadFeed(), loadLibrary()])
}

async function composePrompt() {
  composePending.value = true
  composeError.value = null
  try {
    const result = await api.composeImagePrompt({
      title: "",
      destination: "",
      scene_prompt: "",
      prompt: form.prompt.trim(),
      negative_prompt: form.negative_prompt.trim(),
      style_tags: [],
      reference_urls: referenceUrls.value,
      reference_count: referenceUrls.value.length + referenceFiles.value.length
    })
    form.optimized_prompt = result.optimized_prompt
    form.negative_prompt = result.negative_prompt
  } catch (value) {
    composeError.value = getErrorMessage(value, copy.value.composeFailed)
  } finally {
    composePending.value = false
  }
}

async function pollJob(jobId: string, generationId: string) {
  try {
    const job = await api.getJob(jobId)
    activeJob.value = job
    if (isJobActive(job.status)) {
      clearPollTimer()
      pollTimer = window.setTimeout(() => {
        void pollJob(jobId, generationId)
      }, 2000)
      return
    }

    if (job.status === "completed") {
      lastGenerated.value = await api.getImage(generationId)
      generateError.value = null
      await refreshAll()
      return
    }

    generateError.value = job.error_message || copy.value.generateFailed
    await refreshAll()
  } catch (value) {
    generateError.value = getErrorMessage(value, copy.value.generateFailed)
  }
}

async function submitGenerate() {
  if (form.mode === "image_to_image" && !sourceFile.value) {
    generateError.value = copy.value.sourceRequired
    return
  }

  generatePending.value = true
  generateError.value = null
  const formData = new FormData()
  formData.set("title", "")
  formData.set("destination", "")
  formData.set("scene_prompt", "")
  formData.set("mode", form.mode)
  formData.set("visibility", form.visibility)
  formData.set("prompt", form.prompt.trim())
  formData.set("optimized_prompt", form.optimized_prompt.trim())
  formData.set("negative_prompt", form.negative_prompt.trim())
  formData.set("style_tags_json", JSON.stringify([]))
  formData.set("reference_urls_json", JSON.stringify(referenceUrls.value))
  if (sourceFile.value) {
    formData.append("source_image", sourceFile.value)
  }
  for (const file of referenceFiles.value) {
    formData.append("reference_files", file)
  }

  try {
    const result = await api.generateImage(formData)
    activeJob.value = result.job
    lastGenerated.value = result.generation
    await pollJob(result.job.job_id, result.generation.id)
  } catch (value) {
    const message = getErrorMessage(value, copy.value.generateFailed)
    generateError.value =
      value instanceof ApiError && value.code === "image_provider_not_configured"
        ? copy.value.missingImageConfigMessage
        : message
  } finally {
    generatePending.value = false
  }
}

async function toggleVisibility(record: ImageGenerationRecord) {
  pendingVisibilityId.value = record.id
  try {
    await api.updateImage(record.id, {
      visibility: record.visibility === "public" ? "private" : "public"
    })
    await refreshAll()
  } catch (value) {
    error.value = getErrorMessage(value, copy.value.listFailed)
  } finally {
    pendingVisibilityId.value = null
  }
}

async function remixRecord(record: ImageGenerationRecord) {
  try {
    const remixed = await api.remixImage(record.id)
    applyRecordToForm(remixed)
    await loadLibrary()
  } catch (value) {
    error.value = getErrorMessage(value, copy.value.listFailed)
  }
}

async function copyPrompt(record: ImageGenerationRecord) {
  const content = record.optimized_prompt || record.prompt
  if (!content.trim()) {
    error.value = copy.value.noPrompt
    return
  }
  try {
    await navigator.clipboard.writeText(content)
    notice.value = copy.value.copied
  } catch {
    error.value = copy.value.noPrompt
  }
}

function onSourceFileChange(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0] ?? null
  sourceFile.value = file
  revokeSourcePreview()
  if (file) {
    sourcePreviewUrl.value = URL.createObjectURL(file)
  }
}

function onReferenceFilesChange(event: Event) {
  const target = event.target as HTMLInputElement
  referenceFiles.value = Array.from(target.files ?? [])
}

watch(
  () => [filters.mode, filters.status, filters.visibility],
  () => {
    void loadLibrary()
  }
)

onMounted(async () => {
  await refreshAll()
})

onBeforeUnmount(() => {
  clearPollTimer()
  revokeSourcePreview()
})
</script>

<template>
  <section class="page-grid image-studio-page">
    <article class="panel image-hero">
      <div>
        <p class="kicker">{{ copy.title }}</p>
        <h1>{{ copy.title }}</h1>
        <p class="muted">{{ copy.description }}</p>
      </div>
      <div class="inline-actions">
        <button type="button" :disabled="loading || feedLoading" @click="refreshAll">{{ copy.refresh }}</button>
      </div>
    </article>

    <StatePanel v-if="error" kind="error" :title="copy.listFailed" :message="error" compact />
    <StatePanel v-if="notice" kind="info" :title="copy.title" :message="notice" compact />

    <div class="image-studio-grid">
      <article class="panel panel-stack image-create-panel">
        <div>
          <p class="kicker">{{ copy.createTitle }}</p>
          <h2>{{ copy.createTitle }}</h2>
          <p class="muted">{{ copy.createHint }}</p>
        </div>

        <div class="form-grid">
          <div class="field">
            <label for="image-visibility">{{ copy.visibilityLabel }}</label>
            <select id="image-visibility" v-model="form.visibility">
              <option value="private">{{ copy.privateLabel }}</option>
              <option value="public">{{ copy.publicLabel }}</option>
            </select>
          </div>

          <div class="field">
            <label for="image-mode">{{ copy.modeLabel }}</label>
            <select id="image-mode" v-model="form.mode">
              <option value="text_to_image">Text to image</option>
              <option value="image_to_image">Image to image</option>
            </select>
          </div>

          <div class="field">
            <label for="image-source">{{ copy.sourceLabel }}</label>
            <input id="image-source" type="file" accept="image/*" @change="onSourceFileChange" />
          </div>

          <div class="field field--full">
            <label for="image-prompt">{{ copy.promptLabel }}</label>
            <textarea id="image-prompt" v-model="form.prompt" />
          </div>

          <div class="field field--full">
            <label for="image-optimized-prompt">{{ copy.optimizedPromptLabel }}</label>
            <textarea id="image-optimized-prompt" v-model="form.optimized_prompt" />
          </div>

          <div class="field field--full">
            <label for="image-negative-prompt">{{ copy.negativePromptLabel }}</label>
            <textarea id="image-negative-prompt" v-model="form.negative_prompt" />
          </div>

          <div class="field field--full">
            <label for="image-reference-files">{{ copy.referenceFilesLabel }}</label>
            <input id="image-reference-files" type="file" accept="image/*" multiple @change="onReferenceFilesChange" />
          </div>

          <div class="field field--full">
            <label for="image-reference-urls">{{ copy.referenceUrlsLabel }}</label>
            <textarea id="image-reference-urls" v-model="form.reference_urls_input" />
          </div>
        </div>

        <div v-if="sourcePreviewUrl || sourceFileName || referenceFileNames.length" class="image-upload-preview">
          <div v-if="sourcePreviewUrl" class="image-upload-preview__source">
            <img :src="sourcePreviewUrl" :alt="sourceFileName || 'source preview'" />
          </div>
          <div class="panel-subsection">
            <p v-if="sourceFileName" class="muted"><strong>{{ copy.sourceLabel }}:</strong> {{ sourceFileName }}</p>
            <p v-if="referenceFileNames.length" class="muted"><strong>{{ copy.referenceFilesLabel }}:</strong> {{ referenceFileNames.join(", ") }}</p>
          </div>
        </div>

        <StatePanel v-if="composeError" kind="error" :title="copy.composeFailed" :message="composeError" compact />
        <StatePanel v-if="generateError" kind="error" :title="copy.generateFailed" :message="generateError" compact />

        <div class="inline-actions">
          <button type="button" :disabled="composePending" @click="composePrompt">
            {{ composePending ? copy.optimizing : copy.optimize }}
          </button>
          <button class="primary" type="button" :disabled="generatePending" @click="submitGenerate">
            {{ generatePending ? copy.generating : copy.generate }}
          </button>
        </div>

        <article class="panel-subsection">
          <div class="inline-actions" style="justify-content: space-between;">
            <div>
              <p class="kicker">{{ copy.latestTitle }}</p>
              <h3>{{ lastGenerated?.title || copy.latestTitle }}</h3>
            </div>
            <StatusPill v-if="lastGenerated" :status="lastGenerated.status" />
          </div>
          <p class="muted">{{ copy.latestMessage }}</p>
          <div v-if="activeJob" class="image-job-card">
            <p class="muted"><strong>Job:</strong> {{ activeJob.job_id }}</p>
            <p class="muted"><strong>Stage:</strong> {{ activeJob.stage || "-" }}</p>
            <p class="muted"><strong>Status:</strong> {{ activeJob.status }}</p>
          </div>
          <div v-if="lastGenerated?.result_images.length" class="image-result-grid">
            <img v-for="asset in lastGenerated.result_images" :key="asset.id" :src="asset.url" :alt="lastGenerated.title" loading="lazy" />
          </div>
        </article>

        <StatePanel kind="info" :title="copy.trendsTitle" :message="copy.trendsMessage" compact>
          <template #actions>
            <span class="detail-chip detail-chip--soft">{{ copy.trendSoon }}</span>
          </template>
        </StatePanel>
      </article>

      <div class="page-grid">
        <article class="panel panel-stack">
          <div>
            <p class="kicker">{{ copy.feedTitle }}</p>
            <h2>{{ copy.feedTitle }}</h2>
            <p class="muted">{{ copy.feedHint }}</p>
          </div>

          <StatePanel
            v-if="feedLoading"
            kind="loading"
            :title="copy.feedTitle"
            :message="copy.feedHint"
            compact
          />

          <StatePanel
            v-else-if="feedRecords.length === 0"
            kind="empty"
            :title="copy.emptyFeedTitle"
            :message="copy.emptyFeedMessage"
            compact
          />

          <div v-else class="image-card-grid">
            <article v-for="record in feedRecords" :key="record.id" class="image-card panel-subsection">
              <div class="image-card__media" v-if="record.result_images[0]">
                <img :src="record.result_images[0].url" :alt="record.title" loading="lazy" />
              </div>
              <div class="image-card__body">
                <div class="inline-actions" style="justify-content: space-between;">
                  <div>
                    <p class="kicker">{{ record.destination || formatVisibility(record.visibility) }}</p>
                    <h3>{{ record.title }}</h3>
                  </div>
                  <StatusPill :status="record.status" />
                </div>
                <p class="muted">{{ record.optimized_prompt || record.prompt }}</p>
                <p class="muted">{{ [record.author_name, formatDateTime(record.created_at)].filter(Boolean).join(" · ") }}</p>
                <div class="inline-actions">
                  <button type="button" @click="copyPrompt(record)">{{ copy.copyPrompt }}</button>
                  <button type="button" @click="remixRecord(record)">{{ copy.remix }}</button>
                  <button type="button" @click="applyRecordToForm(record)">{{ copy.loadToForm }}</button>
                </div>
              </div>
            </article>
          </div>
        </article>

        <article class="panel panel-stack">
          <div>
            <p class="kicker">{{ copy.libraryTitle }}</p>
            <h2>{{ copy.libraryTitle }}</h2>
            <p class="muted">{{ copy.libraryHint }}</p>
          </div>

          <div class="image-filter-grid">
            <div class="field">
              <label for="filter-mode">{{ copy.filtersMode }}</label>
              <select id="filter-mode" v-model="filters.mode">
                <option value="">All</option>
                <option value="text_to_image">Text to image</option>
                <option value="image_to_image">Image to image</option>
              </select>
            </div>
            <div class="field">
              <label for="filter-status">{{ copy.filtersStatus }}</label>
              <select id="filter-status" v-model="filters.status">
                <option value="">All</option>
                <option value="draft">{{ copy.statusDraft }}</option>
                <option value="queued">{{ copy.statusQueued }}</option>
                <option value="running">{{ copy.statusRunning }}</option>
                <option value="completed">{{ copy.statusCompleted }}</option>
                <option value="failed">{{ copy.statusFailed }}</option>
              </select>
            </div>
            <div class="field">
              <label for="filter-visibility">{{ copy.filtersVisibility }}</label>
              <select id="filter-visibility" v-model="filters.visibility">
                <option value="">All</option>
                <option value="private">{{ copy.privateLabel }}</option>
                <option value="public">{{ copy.publicLabel }}</option>
              </select>
            </div>
          </div>

          <StatePanel
            v-if="loading"
            kind="loading"
            :title="copy.libraryTitle"
            :message="copy.libraryHint"
            compact
          />

          <StatePanel
            v-else-if="myRecords.length === 0"
            kind="empty"
            :title="copy.emptyLibraryTitle"
            :message="copy.emptyLibraryMessage"
            compact
          />

          <div v-else class="image-card-grid">
            <article v-for="record in myRecords" :key="record.id" class="image-card panel-subsection">
              <div class="image-card__media" v-if="record.result_images[0]">
                <img :src="record.result_images[0].url" :alt="record.title" loading="lazy" />
              </div>
              <div class="image-card__body">
                <div class="inline-actions" style="justify-content: space-between;">
                  <div>
                    <p class="kicker">{{ formatVisibility(record.visibility) }}</p>
                    <h3>{{ record.title }}</h3>
                  </div>
                  <StatusPill :status="record.status" />
                </div>
                <p class="muted">{{ summarizePrompt(record.optimized_prompt || record.prompt, formatVisibility(record.visibility)) }}</p>
                <p class="muted">{{ formatDateTime(record.updated_at) }}</p>
                <div class="inline-actions">
                  <button type="button" @click="applyRecordToForm(record)">{{ copy.loadToForm }}</button>
                  <button type="button" @click="copyPrompt(record)">{{ copy.copyPrompt }}</button>
                  <button type="button" :disabled="pendingVisibilityId === record.id || record.status !== 'completed'" @click="toggleVisibility(record)">
                    {{ record.visibility === "public" ? copy.makePrivate : copy.makePublic }}
                  </button>
                </div>
                <p class="muted">Remix: {{ record.remix_count }} · {{ formatStatus(record.status) }}</p>
              </div>
            </article>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>
