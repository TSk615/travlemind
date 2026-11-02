<script setup lang="ts">
import { computed, ref } from "vue"
import TripJourneyFlow from "@/components/TripJourneyFlow.vue"
import { journeyPreviewData, type JourneyPreviewScenario } from "@/dev/journeyPreview"
const scenario = ref<JourneyPreviewScenario>("three-days")
const itinerary = computed(() => journeyPreviewData(scenario.value))
const showList = ref(false)
</script>

<template>
  <div class="journey-preview">
    <div class="journey-preview__notice"><span>DESIGN PREVIEW / 设计试验</span><p>演示数据 · AI 氛围图，非景点实景 · 不会调用模型或写入真实行程</p></div>
    <header class="journey-preview__header"><div><p>TRAVELMIND / JOURNEY FLOW</p><h1>{{ scenario === "three-days" ? "山湖之间，留白三日。" : scenario === "busy-day" ? "八站，也能从容展开。" : "图片没到，旅程不打断。" }}</h1><span>{{ itinerary.days.length > 1 ? "11 月 06 — 08 日" : "11 月 06 日" }} / {{ itinerary.days.length }} 天 / 2 人 / 松弛一点</span></div><label>预览场景<select v-model="scenario"><option value="three-days">三天的旅程</option><option value="busy-day">单日 8 站</option><option value="missing-images">图片缺失与回退</option></select></label><div class="journey-preview__switch" role="group" aria-label="预览展示方式"><button type="button" :aria-pressed="!showList" @click="showList = false">流动旅程</button><button type="button" :aria-pressed="showList" @click="showList = true">时间清单</button></div></header>

    <TripJourneyFlow v-if="!showList" :itinerary="itinerary" start-date="2026-11-06" preview />
    <div v-else class="journey-preview__list"><section v-for="day in itinerary.days" :key="day.day_index"><h2>DAY {{ day.day_index }} / {{ day.title }}</h2><ol><li v-for="item in day.items" :key="item.id"><time>{{ item.start_time }} — {{ item.end_time }}</time><strong>{{ item.name }}</strong><p>{{ item.note }}</p></li></ol></section></div>
  </div>
</template>

<style scoped>
.journey-preview { max-width: 1280px; margin: 0 auto; padding: 28px 38px 42px; border: 1px solid #fff; border-radius: 28px; background: radial-gradient(ellipse at 100% 0, #f7eadd88, transparent 40%), linear-gradient(145deg, #f6f7ef, #edf2e7); box-shadow: 0 20px 70px #52684d08; color: #283e3b; }
.journey-preview :where(h1, h2, p) { margin: 0; }
.journey-preview__notice { display: flex; justify-content: space-between; gap: 15px; flex-wrap: wrap; padding-bottom: 10px; border-bottom: 1px solid #dce3da; color: #839178; font-size: 9px; line-height: 1.8; }
.journey-preview__notice > span { letter-spacing: .08em; }
.journey-preview__header { display: flex; align-items: center; justify-content: space-between; gap: 24px; margin: 18px 0 20px; }
.journey-preview__header p { color: #87947d; font-size: 9px; letter-spacing: .15em; }
.journey-preview__header h1 { margin: 10px 0 13px; font-size: 30px; font-weight: 400; line-height: 1.5; letter-spacing: -.05em; color: #283e3b; }
.journey-preview__header span { color: #7b8973; font-size: 11px; }
.journey-preview__header label { display: grid; gap: 8px; color: #839178; font-size: 9px; }
.journey-preview__header select { min-height: 42px; padding: 8px 35px 8px 14px; border: 1px solid #fff; border-radius: 100px; background-color: #ffffff99; color: #536e56; font-size: 11px; box-shadow: none; }
.journey-preview__switch { display: inline-flex; flex-shrink: 0; gap: 4px; padding: 4px; border: 1px solid #fff; border-radius: 100px; background: #e9eee3; }
.journey-preview__switch button { min-height: 40px; padding: 10px 22px; border: 0; border-radius: 100px; background: transparent; color: #74856e; box-shadow: none; font-size: 11px; }
.journey-preview__switch button[aria-pressed="true"] { background: #46685c; color: white; }
.journey-preview :where(button, select):focus-visible { outline: 2px solid #50755f; outline-offset: 3px; }
.journey-preview__list section { padding-block: 30px; border-bottom: 1px solid #dce3da; }
.journey-preview__list h2 { font-size: 22px; font-weight: 400; }
.journey-preview__list ol { padding-left: 24px; }
.journey-preview__list li { padding: 18px 8px; color: #6c7e68; font-size: 13px; line-height: 2; }
.journey-preview__list time { display: inline-block; min-width: 160px; font-size: 11px; }
.journey-preview__list strong { color: #46685c; font-weight: 500; }
@media (min-width: 761px) and (max-width: 1100px) { .journey-preview__header { flex-wrap: wrap; } }
@media (max-width: 760px) { .journey-preview { padding: 22px 18px 28px; border-radius: 22px; } .journey-preview__header { align-items: flex-start; flex-direction: column; gap: 20px; } .journey-preview__header h1 { font-size: 28px; } .journey-preview__header label { grid-template-columns: auto auto; align-items: center; gap: 14px; } }
</style>
