<script setup lang="ts">
import { computed, ref } from "vue"
import { useRouter } from "vue-router"
import TmButton from "@/components/ui/TmButton.vue"
import { portalAssets } from "@/lib/portalAssets"
import { useI18n } from "@/lib/useI18n"

const { locale } = useI18n()
const router = useRouter()
const brief = ref("")
const copy = computed(() => locale.value === "zh-CN" ? {
  title: ["每一次出发，", "都有新的可能。"],
  description: ["把零散的向往，整理成值得出发的旅程。", "路线、预算与节奏，交给懂你的 AI。"],
  inspiration: "先去发现一点灵感", prompt: "下一站，从一个念头开始",
  placeholder: "想去哪里？或者，说说你想怎样度过这段时光……", start: "开始规划",
  scene: "01 / 想象的入口", disclosure: "原创 AI 灵感场景 · 非真实目的地",
  closing: ["别只收藏世界，", "去经历它。"],
  steps: [
    { title: "01  描述向往", description: "从一句话开始，不必先想好全部。" },
    { title: "02  一起打磨", description: "每日路线、预算和节奏，随时调整。" },
    { title: "03  带上出发", description: "收藏、分享，或导出你的旅行计划。" }
  ]
} : {
  title: ["Every departure,", "a new possibility."],
  description: ["Turn scattered inspiration into a journey worth taking.", "Let AI help with the route, budget, and pace."],
  inspiration: "Find a little inspiration", prompt: "Your next chapter starts with a thought",
  placeholder: "Where would you like to go? Or tell us how you want to spend your time…", start: "Start planning",
  scene: "01 / A doorway to possibility", disclosure: "Original AI concept art · Not a real destination",
  closing: ["Don't just save the world.", "Go experience it."],
  steps: [
    { title: "01  Share a thought", description: "Start with a sentence. You don't need every detail." },
    { title: "02  Make it yours", description: "Refine the route, budget, and pace together." },
    { title: "03  Take it with you", description: "Save, share, or export your journey." }
  ]
})

function startPlanning() {
  const prompt = brief.value.trim()
  // Carry the brief through the existing login redirect, without starting a paid AI request.
  void router.push({ name: "trip-new", query: prompt ? { prompt } : {} })
}
</script>

<template>
  <div class="portal-home">
    <section class="portal-hero" aria-labelledby="portal-headline">
      <img class="portal-hero__art" :src="portalAssets.portalWorld" alt="" width="1536" height="1024" fetchpriority="high" />
      <div class="portal-hero__lead">
        <p class="portal-eyebrow">A LITTLE WONDER. A NEW WAY TO GO.</p>
        <h1 id="portal-headline"><span v-for="line in copy.title" :key="line">{{ line }}</span></h1>
        <p class="portal-hero__description"><span v-for="line in copy.description" :key="line">{{ line }}</span></p>
        <RouterLink class="portal-text-link" to="/community">{{ copy.inspiration }} <span aria-hidden="true">↗</span></RouterLink>
      </div>
      <p class="portal-hero__caption"><span>{{ copy.scene }}</span><span>{{ copy.disclosure }}</span></p>
      <form class="portal-planner" @submit.prevent="startPlanning">
        <label for="journey-brief">{{ copy.prompt }}</label>
        <div class="portal-planner__row">
          <input id="journey-brief" v-model="brief" name="journey-brief" type="text" :placeholder="copy.placeholder" maxlength="1600" autocomplete="off" />
          <TmButton type="submit" class="portal-primary" size="lg">{{ copy.start }} <span aria-hidden="true">↗</span></TmButton>
        </div>
      </form>
    </section>
    <section class="portal-signature" :aria-label="locale === 'zh-CN' ? '旅行如何开始' : 'How your journey begins'">
      <h2><span v-for="line in copy.closing" :key="line">{{ line }}</span></h2>
      <div v-for="step in copy.steps" :key="step.title" class="portal-signature__step">
        <h3>{{ step.title }}</h3>
        <p>{{ step.description }}</p>
      </div>
    </section>
  </div>
</template>
