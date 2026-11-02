<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch, type ComponentPublicInstance } from "vue"
import type { GeneratedItinerary, ItineraryItem } from "@travelmind/shared-types"
import PoiImage from "@/components/PoiImage.vue"
import { useI18n } from "@/lib/useI18n"
import { formatCurrency } from "@/lib/format"
import { buildJourneyPath, isCompactJourneyStop, journeyDayDate, journeyDurationMinutes, journeyImages, safeJourneySource } from "@/lib/journeyFlow"
const props = defineProps<{ itinerary: GeneratedItinerary; startDate: string; preview?: boolean }>()
const emit = defineEmits<{ inspect: [stop: { dayIndex: number; itemId: string }] }>()
const { locale } = useI18n()
const zh = computed(() => locale.value === "zh-CN")
const days = computed(() => props.itinerary.days ?? [])
const activeDay = ref(0)
const dayNav = ref<HTMLElement | null>(null)
const stopDialog = ref<HTMLDialogElement | null>(null)
const selectedStop = ref<{ item: ItineraryItem; dayPosition: number } | null>(null)
const revealed = ref(new Set<string>())
const chapterNodes = new Map<number, HTMLElement>()
const timelineNodes = new Map<number, HTMLElement>()
const stopNodes = new Map<string, HTMLElement>()
const markerNodes = new Map<string, HTMLElement>()
const paths = ref<Record<number, { path: string; width: number; height: number; top: number }>>({})
const progress = ref<Record<number, number>>({})
let resizeObserver: ResizeObserver | null = null, entryObserver: IntersectionObserver | null = null
let media: MediaQueryList | null = null
let geometryFrame = 0, scrollFrame = 0, disposed = false, suspended = false
let previousOverflow: string | null = null
const key = (day: number, stop: number) => `${day}-${stop}`
function register<K>(map: Map<K, HTMLElement>, id: K, element: Element | ComponentPublicInstance | null) {
  if (element instanceof HTMLElement) map.set(id, element); else map.delete(id)
}
function updateScroll() {
  scrollFrame = 0
  const line = window.scrollY + Math.min(window.innerHeight * .38, 310)
  let current = 0
  const next: Record<number, number> = {}
  for (const [i, chapter] of chapterNodes) {
    if (chapter.getBoundingClientRect().top <= (window.innerWidth <= 760 ? 190 : 180)) current = i
    const path = paths.value[i]
    if (path) next[i] = Math.max(0, Math.min(1, (line - path.top) / path.height))
  }
  if (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 4) current = Math.max(0, days.value.length - 1)
  activeDay.value = current; progress.value = next
}
function scheduleScroll() { if (!scrollFrame) scrollFrame = requestAnimationFrame(updateScroll) }
function measure() {
  geometryFrame = 0
  if (disposed || suspended) return
  const next: typeof paths.value = {}
  for (const [dayPosition, timeline] of timelineNodes) {
    const rect = timeline.getBoundingClientRect()
    if (!rect.width || !rect.height) continue
    const points = (days.value[dayPosition]?.items ?? []).flatMap((_, i) => {
      const marker = markerNodes.get(key(dayPosition, i))?.getBoundingClientRect()
      return marker ? [{ x: marker.left + marker.width / 2 - rect.left, y: marker.top + marker.height / 2 - rect.top }] : []
    })
    if (points.length) next[dayPosition] = {
      path: buildJourneyPath([{ x: points[0].x, y: 0 }, ...points, { x: points[points.length - 1].x, y: rect.height }]),
      width: rect.width, height: rect.height, top: rect.top + window.scrollY
    }
  }
  paths.value = next; updateScroll()
}
function scheduleMeasure() { if (!disposed && !suspended && !geometryFrame) geometryFrame = requestAnimationFrame(measure) }
function observe() {
  resizeObserver?.disconnect(); entryObserver?.disconnect()
  for (const node of timelineNodes.values()) resizeObserver?.observe(node)
  for (const node of stopNodes.values()) { resizeObserver?.observe(node); entryObserver?.observe(node) }
  scheduleMeasure()
}
function jumpToDay(i: number) {
  activeDay.value = i
  chapterNodes.get(i)?.scrollIntoView({ behavior: media?.matches ? "auto" : "smooth", block: "start" })
}
function stopKind(item: ItineraryItem) {
  if (["transport", "intercity_transport", "local_transport", "flight", "train", "transfer", "交通"].includes(item.type.toLowerCase())) return zh.value ? "路上时光" : "On the way"
  return isCompactJourneyStop(item) ? (zh.value ? "停下来，吃点好的" : "A little pause") : (zh.value ? "沿途一站" : "Along the way")
}
function duration(item: ItineraryItem) {
  const minutes = journeyDurationMinutes(item)
  if (!minutes) return ""
  const h = Math.floor(minutes / 60), m = minutes % 60
  return zh.value ? `${h ? `${h} 小时` : ""}${h && m ? " " : ""}${m ? `${m} 分钟` : ""}` : `${h ? `${h}h ` : ""}${m ? `${m}min` : ""}`.trim()
}
function imageMessage(item: ItineraryItem) {
  return item.image_status === "pending" ? (zh.value ? "景点图片正在补充" : "Photographs are on their way") : (zh.value ? "景点图片暂不可用" : "Photograph unavailable")
}
function sources(item: ItineraryItem) { return [...new Set((item.image_source_urls ?? []).flatMap(url => safeJourneySource(url) ?? []))] }
async function openStop(item: ItineraryItem, dayPosition: number) {
  selectedStop.value = { item, dayPosition }; await nextTick()
  if (disposed || !stopDialog.value || stopDialog.value.open) return
  previousOverflow = document.body.style.overflow; document.body.style.overflow = "hidden"
  stopDialog.value.showModal()
}
function restoreOverflow() { if (previousOverflow !== null) document.body.style.overflow = previousOverflow; previousOverflow = null }
function closeStop() { stopDialog.value?.close() }
function onDialogClose() { selectedStop.value = null; restoreOverflow() }
function inspectStop() {
  const selection = selectedStop.value
  if (!selection) return
  emit("inspect", { dayIndex: days.value[selection.dayPosition].day_index, itemId: selection.item.id }); closeStop()
}
watch(() => props.itinerary.days, async () => { activeDay.value = 0; closeStop(); await nextTick(); if (!disposed && !suspended) observe() })
watch(activeDay, async () => {
  await nextTick()
  if (!dayNav.value) return
  const button = dayNav.value.querySelectorAll("button")[activeDay.value]
  if (button && window.innerWidth > 760) {
    const navRect = dayNav.value.getBoundingClientRect(), rect = button.getBoundingClientRect()
    if (rect.top < navRect.top || rect.bottom > navRect.bottom) dayNav.value.scrollTo({ top: dayNav.value.scrollTop + rect.top - navRect.top - navRect.height / 2 + rect.height / 2, behavior: "auto" })
    return
  }
  if (button) dayNav.value.scrollTo({ left: button.offsetLeft - dayNav.value.clientWidth / 2 + button.clientWidth / 2, behavior: media?.matches ? "auto" : "smooth" })
})
onMounted(() => {
  media = window.matchMedia("(prefers-reduced-motion: reduce)")
  resizeObserver = new ResizeObserver(scheduleMeasure)
  entryObserver = new IntersectionObserver(entries => {
    const next = new Set(revealed.value)
    for (const entry of entries) if (entry.isIntersecting) { next.add((entry.target as HTMLElement).dataset.stopKey ?? ""); entryObserver?.unobserve(entry.target) }
    revealed.value = next
  }, { threshold: .08 })
  observe()
  window.addEventListener("scroll", scheduleScroll, { passive: true }); window.addEventListener("resize", scheduleMeasure, { passive: true })
  void document.fonts.ready.then(() => { if (!disposed) scheduleMeasure() })
})
onDeactivated(() => {
  suspended = true
  closeStop(); restoreOverflow()
  resizeObserver?.disconnect(); entryObserver?.disconnect()
  window.removeEventListener("scroll", scheduleScroll); window.removeEventListener("resize", scheduleMeasure)
  cancelAnimationFrame(geometryFrame); cancelAnimationFrame(scrollFrame); geometryFrame = 0; scrollFrame = 0
})
onActivated(() => {
  suspended = false
  if (media) {
    observe()
    window.addEventListener("scroll", scheduleScroll, { passive: true }); window.addEventListener("resize", scheduleMeasure, { passive: true })
  }
})
onBeforeUnmount(() => {
  disposed = true; resizeObserver?.disconnect(); entryObserver?.disconnect()
  window.removeEventListener("scroll", scheduleScroll); window.removeEventListener("resize", scheduleMeasure)
  cancelAnimationFrame(geometryFrame); cancelAnimationFrame(scrollFrame); restoreOverflow()
})
</script>

<template>
  <section class="journey-flow" :aria-label="zh ? '流动旅程' : 'Journey flow'">
    <header class="journey-flow__intro">
      <div><p class="journey-flow__eyebrow">A JOURNEY, NOT JUST A LIST.</p><h2>{{ itinerary.summary }}</h2></div>
      <p class="journey-flow__legend"><span aria-hidden="true">⌁</span>{{ zh ? '循着时间，串起每一站' : 'Follow the moments, find your way' }}<small>{{ zh ? '连线表示游览顺序，非地图导航' : 'Visit order, not geographic navigation' }}</small></p>
    </header>
    <div v-if="!days.length" class="journey-flow__empty">{{ zh ? '这段旅程还没有每日安排，可在完整清单中补充。' : 'No daily stops yet. Add them in the full itinerary.' }}</div>
    <div v-else class="journey-flow__layout">
      <aside class="journey-flow__rail"><div class="journey-flow__rail-inner">
        <p class="journey-flow__eyebrow">YOUR CHAPTERS <span>{{ String(days.length).padStart(2, '0') }}</span></p>
        <nav ref="dayNav" class="journey-flow__day-nav" :aria-label="zh ? '按天浏览行程' : 'Browse itinerary by day'">
          <button v-for="(day, di) in days" :key="di" type="button" :aria-label="`${zh ? '第' : 'Day '}${day.day_index}${zh ? '天：' : ': '}${day.title}`" :aria-controls="`journey-day-${di}`" :aria-current="activeDay === di ? 'step' : undefined" @click="jumpToDay(di)">
            <span class="journey-flow__day-number">{{ String(day.day_index).padStart(2, '0') }}</span>
            <span class="journey-flow__day-label"><strong>{{ day.title }}</strong><small>{{ journeyDayDate(startDate, Math.max(0, day.day_index - 1), locale) }}</small></span><span class="journey-flow__nav-arrow" aria-hidden="true">↗</span>
          </button>
        </nav>
        <div class="journey-flow__rail-note"><span aria-hidden="true">↟</span><p>{{ zh ? '不必赶路，\n也别错过沿途。' : 'Take your time.\nNotice the little things.' }}</p><small>{{ zh ? '滚动，慢慢展开这段旅程' : 'Scroll to unfold your journey' }}</small></div>
      </div></aside>
      <div class="journey-flow__chapters">
        <section v-for="(day, di) in days" :id="`journey-day-${di}`" :key="di" :data-active="activeDay === di" :ref="el => register(chapterNodes, di, el)" class="journey-chapter" :aria-labelledby="`journey-day-title-${di}`">
          <header class="journey-chapter__header"><span class="journey-chapter__index" aria-hidden="true">{{ String(day.day_index).padStart(2, '0') }}</span><div><p class="journey-flow__eyebrow">DAY {{ String(day.day_index).padStart(2, '0') }} <span>{{ journeyDayDate(startDate, Math.max(0, day.day_index - 1), locale) }}</span></p><h3 :id="`journey-day-title-${di}`">{{ day.title }}</h3><p class="journey-chapter__summary">{{ day.summary }}</p></div></header>
          <div v-if="day.flexible_windows?.length" class="journey-chapter__facts" aria-label="Flexible time windows">
            <span v-for="(window, wi) in day.flexible_windows" :key="`flex-${di}-${wi}`">{{ window.start_time }}—{{ window.end_time }} · {{ window.note }}</span>
          </div>
          <div class="journey-chapter__facts"><span>{{ day.items.length }} {{ zh ? '站' : 'stops' }}</span><span>{{ zh ? '当日预算' : 'Daily estimate' }} {{ formatCurrency(day.total_cost) }}</span><span v-if="day.weather?.summary">{{ day.weather.forecast_type === 'seasonal_reference' ? (zh ? '季节参考 · ' : 'Seasonal reference · ') : '' }}{{ day.weather.summary }}</span></div>
          <div v-if="!day.items.length" class="journey-flow__empty">{{ zh ? '留一点空白，给这一天的新发现。完整清单中可继续编辑。' : 'A little room for discovery. Add stops in the full itinerary.' }}</div>
          <div v-else :ref="el => register(timelineNodes, di, el)" class="journey-timeline" :class="{ 'journey-timeline--paired': day.items.length > 1 }">
            <svg v-if="paths[di]" class="journey-timeline__route" aria-hidden="true" :viewBox="`0 0 ${paths[di].width} ${paths[di].height}`" preserveAspectRatio="none"><path :d="paths[di].path" class="journey-timeline__base" /><path :d="paths[di].path" class="journey-timeline__progress" pathLength="1" :style="{ strokeDashoffset: 1 - (progress[di] ?? 0) }" /></svg>
            <ol class="journey-timeline__stops">
              <li v-for="(item, si) in day.items" :key="`${si}-${item.id}`" :ref="el => register(stopNodes, key(di, si), el)" :data-stop-key="key(di, si)" class="journey-stop" :class="{ 'journey-stop--compact': isCompactJourneyStop(item), 'is-revealed': revealed.has(key(di, si)) }">
                <span :ref="el => register(markerNodes, key(di, si), el)" class="journey-stop__marker" aria-hidden="true"><i></i></span>
                <div class="journey-stop__card">
                  <button class="journey-stop__open" type="button" :aria-label="`${zh ? '查看景点' : 'View stop'}：${item.name}`" @click="openStop(item, di)">
                    <div v-if="!isCompactJourneyStop(item)" class="journey-stop__photo">
                      <PoiImage v-if="journeyImages([...(item.image_urls ?? []), ...(item.image_backup_urls ?? [])]).length" :urls="journeyImages(item.image_urls)" :backups="journeyImages(item.image_backup_urls)" :alt="item.name" />
                      <div v-else class="journey-stop__placeholder"><span aria-hidden="true">⌁</span><p>{{ imageMessage(item) }}</p></div>
                      <span class="journey-stop__photo-label">{{ String(si + 1).padStart(2, '0') }} / {{ stopKind(item) }}</span>
                    </div>
                    <div class="journey-stop__body">
                      <p class="journey-stop__time"><time>{{ item.start_time || '—' }}</time><span>—</span><time>{{ item.end_day_offset ? `+${item.end_day_offset}${zh ? '天 ' : 'd '}` : '' }}{{ item.end_time || '—' }}</time><small v-if="duration(item)">{{ duration(item) }}</small></p>
                      <p v-if="isCompactJourneyStop(item)" class="journey-stop__kind">{{ stopKind(item) }}</p><h4>{{ item.name }}</h4><p class="journey-stop__note">{{ item.note || item.location }}</p><span class="journey-stop__more">{{ zh ? '看看这一站' : 'Explore this stop' }} <span aria-hidden="true">↗</span></span>
                    </div>
                  </button>
                  <div v-if="!isCompactJourneyStop(item)" class="journey-stop__source"><span>{{ preview ? (zh ? 'AI 氛围图 · 非实景' : 'AI concept art · not a real location') : (zh ? '沿途影像' : 'Along the way') }}</span><a v-if="sources(item).length" :href="sources(item)[0]" target="_blank" rel="noopener noreferrer">{{ zh ? '图片来源 ↗' : 'Image source ↗' }}</a><span v-else-if="!preview">{{ zh ? '图片来源待补充' : 'Image source unavailable' }}</span></div>
                </div>
              </li>
            </ol>
          </div>
          <footer class="journey-chapter__closing"><span aria-hidden="true">○</span>{{ di === days.length - 1 ? (zh ? '这一程的结束，也是下一次出发的开始。' : 'Every ending leaves room for a new beginning.') : (zh ? '收好今天，明天继续。' : 'Keep a little of today. Tomorrow awaits.') }}</footer>
        </section>
        <section v-if="itinerary.risks?.length" class="journey-flow__risks"><h3>{{ zh ? '出发前，记得这些' : 'A few things before you go' }}</h3><ul><li v-for="(risk, i) in itinerary.risks" :key="i">{{ risk }}</li></ul></section>
      </div>
    </div>
    <dialog ref="stopDialog" class="journey-stop-dialog" :aria-label="zh ? '景点详情' : 'Stop details'" @close="onDialogClose" @click.self="closeStop">
      <article v-if="selectedStop">
        <button class="journey-stop-dialog__close" type="button" autofocus :aria-label="zh ? '关闭景点详情' : 'Close stop details'" @click="closeStop">×</button>
        <div v-if="!isCompactJourneyStop(selectedStop.item)" class="journey-stop-dialog__photo"><PoiImage :urls="journeyImages(selectedStop.item.image_urls)" :backups="journeyImages(selectedStop.item.image_backup_urls)" :alt="selectedStop.item.name" /></div>
        <div class="journey-stop-dialog__body"><p class="journey-flow__eyebrow">DAY {{ days[selectedStop.dayPosition]?.day_index }} / {{ selectedStop.item.start_time }} — {{ selectedStop.item.end_time }}</p><h2>{{ selectedStop.item.name }}</h2><p class="journey-stop-dialog__location">{{ selectedStop.item.location }}</p><p>{{ selectedStop.item.note }}</p>
          <p v-if="preview" class="journey-stop-dialog__notice">{{ zh ? '设计演示：本页安排、预算和 AI 氛围图均为示例，不是可预订的真实旅行产品。' : 'Design preview: example itinerary, budget and AI concept art; not a bookable trip.' }}</p><p v-else-if="selectedStop.item.image_status === 'pending'" class="journey-stop-dialog__notice">{{ imageMessage(selectedStop.item) }}</p>
          <div v-if="sources(selectedStop.item).length" class="journey-stop-dialog__sources"><span>{{ zh ? '图片来源' : 'Image sources' }}</span><a v-for="(url, i) in sources(selectedStop.item)" :key="url" :href="url" target="_blank" rel="noopener noreferrer">{{ zh ? '来源' : 'Source' }} {{ i + 1 }} ↗</a></div>
          <button v-if="!preview" class="journey-stop-dialog__inspect" type="button" @click="inspectStop">{{ zh ? '查看预订与完整信息' : 'View booking and full details' }} ↗</button>
        </div>
      </article>
    </dialog>
  </section>
</template>

<style scoped src="../styles/journey-flow.css"></style>
