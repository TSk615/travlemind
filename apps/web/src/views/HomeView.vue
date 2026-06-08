<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "@/lib/useI18n"
import TmButton from "@/components/ui/TmButton.vue"
import TmCard from "@/components/ui/TmCard.vue"

const { t, locale } = useI18n()

const cards = computed(() => [
  {
    icon: "🗺",
    title: locale.value === "zh-CN" ? "智能行程规划" : "Smart Itinerary",
    description: locale.value === "zh-CN"
      ? "AI 根据你的偏好、预算和节奏，生成可执行的每日行程。"
      : "AI generates executable daily plans based on your preferences, budget, and pace."
  },
  {
    icon: "📋",
    title: locale.value === "zh-CN" ? "结构化信息采集" : "Structured Intake",
    description: locale.value === "zh-CN"
      ? "表单或对话，两种方式整理旅行意图，AI 帮你补全缺失项。"
      : "Form or conversation — two ways to capture travel intent. AI fills in the gaps."
  },
  {
    icon: "📤",
    title: locale.value === "zh-CN" ? "一键导出分享" : "Export & Share",
    description: locale.value === "zh-CN"
      ? "生成 PDF 攻略包，发布到社区，或导出为可打印的行程单。"
      : "Generate PDF guide packs, publish to community, or export printable itineraries."
  }
])

const flowSteps = computed(() =>
  locale.value === "zh-CN"
    ? "灵感 → 采集 → 规划 → 出发"
    : "Inspiration → Intake → Planning → Go"
)

const heroTitle = computed(() =>
  locale.value === "zh-CN" ? "让每一次出发\n都有迹可循" : "Every journey\ndeserves a plan"
)

const heroSubtitle = computed(() =>
  locale.value === "zh-CN"
    ? "从灵感碎片到可执行的旅行计划，AI 帮你把「想去」变成「出发」。"
    : "From scattered inspiration to executable itineraries — AI turns \"someday\" into \"let's go.\""
)

const ctaTitle = computed(() =>
  locale.value === "zh-CN" ? "准备好了？" : "Ready to start?"
)
</script>

<template>
  <div class="tm-home">
    <!-- Hero Section -->
    <section class="tm-home__hero">
      <p class="tm-home__hero-badge">✦ TravelMind AI</p>
      <h1 class="tm-home__hero-title">{{ heroTitle }}</h1>
      <p class="tm-home__hero-subtitle">{{ heroSubtitle }}</p>
      <div class="tm-home__hero-actions">
        <RouterLink to="/trips/new">
          <TmButton variant="primary" size="lg">{{ t('common.startNewTrip') }}</TmButton>
        </RouterLink>
        <RouterLink to="/community">
          <TmButton variant="ghost" size="lg">{{ locale === 'zh-CN' ? '浏览社区灵感' : 'Browse community' }}</TmButton>
        </RouterLink>
      </div>
    </section>

    <!-- Capability Cards -->
    <section class="tm-home__capabilities">
      <TmCard
        v-for="card in cards"
        :key="card.title"
        variant="action"
        hoverable
        class="tm-home__capability-card"
      >
        <span class="tm-home__capability-icon">{{ card.icon }}</span>
        <h3 class="tm-home__capability-title">{{ card.title }}</h3>
        <p class="tm-home__capability-desc">{{ card.description }}</p>
      </TmCard>
    </section>

    <!-- Flow Strip -->
    <section class="tm-home__flow">
      <p class="tm-home__flow-text">{{ flowSteps }}</p>
    </section>

    <!-- Closing CTA -->
    <section class="tm-home__cta">
      <p class="tm-home__cta-title">{{ ctaTitle }}</p>
      <RouterLink to="/trips/new">
        <TmButton variant="ai" size="lg">
          {{ locale === 'zh-CN' ? '创建第一个行程 ✦' : 'Create your first trip ✦' }}
        </TmButton>
      </RouterLink>
    </section>

    <!-- Decorative SVG -->
    <svg class="tm-home__decoration" viewBox="0 0 200 300" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M100 280 C100 280 95 220 80 180 C65 140 40 120 50 90 C60 60 85 70 90 100 C95 130 100 160 100 160" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
      <path d="M100 280 C100 280 105 230 120 190 C135 150 155 135 145 105 C135 75 115 85 110 110 C105 135 100 170 100 170" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
      <path d="M100 280 C100 280 100 250 100 220 C100 190 90 170 95 150 C100 130 105 140 105 160 C105 180 100 200 100 200" stroke="currentColor" stroke-width="1" stroke-linecap="round"/>
    </svg>
  </div>
</template>

<style scoped>
.tm-home {
  position: relative;
  max-width: var(--tm-content-max-width);
  margin: 0 auto;
  overflow: hidden;
}

/* === Hero === */
.tm-home__hero {
  text-align: center;
  padding: var(--tm-space-16) var(--tm-space-6) var(--tm-space-12);
}

.tm-home__hero-badge {
  font-size: var(--tm-text-sm);
  font-weight: 700;
  color: var(--tm-moss);
  letter-spacing: 0.05em;
  margin-bottom: var(--tm-space-6);
}

.tm-home__hero-title {
  font-family: var(--tm-font-display);
  font-size: var(--tm-text-4xl);
  line-height: var(--tm-leading-tight);
  color: var(--tm-moss);
  white-space: pre-line;
  margin-bottom: var(--tm-space-6);
}

.tm-home__hero-subtitle {
  font-size: var(--tm-text-lg);
  color: var(--tm-stone);
  max-width: 48ch;
  margin: 0 auto var(--tm-space-8);
  line-height: var(--tm-leading-relaxed);
}

.tm-home__hero-actions {
  display: flex;
  gap: var(--tm-space-4);
  justify-content: center;
  flex-wrap: wrap;
}

.tm-home__hero-actions a {
  text-decoration: none;
}

/* === Capabilities === */
.tm-home__capabilities {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--tm-space-6);
  padding: 0 var(--tm-space-6) var(--tm-space-12);
}

.tm-home__capability-card {
  text-align: center;
  padding: var(--tm-space-8) var(--tm-space-6);
}

.tm-home__capability-icon {
  font-size: var(--tm-text-2xl);
  display: block;
  margin-bottom: var(--tm-space-4);
}

.tm-home__capability-title {
  font-size: var(--tm-text-lg);
  font-weight: 700;
  color: var(--tm-tea);
  margin-bottom: var(--tm-space-2);
}

.tm-home__capability-desc {
  font-size: var(--tm-text-sm);
  color: var(--tm-stone);
  line-height: var(--tm-leading-normal);
  margin: 0;
}

/* === Flow Strip === */
.tm-home__flow {
  text-align: center;
  padding: var(--tm-space-8) var(--tm-space-6);
  border-top: var(--tm-border-hairline);
  border-bottom: var(--tm-border-hairline);
  margin: 0 var(--tm-space-6);
}

.tm-home__flow-text {
  font-size: var(--tm-text-sm);
  font-weight: 600;
  color: var(--tm-stone);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  margin: 0;
}

/* === Closing CTA === */
.tm-home__cta {
  text-align: center;
  padding: var(--tm-space-12) var(--tm-space-6) var(--tm-space-16);
}

.tm-home__cta-title {
  font-size: var(--tm-text-xl);
  font-weight: 700;
  color: var(--tm-tea);
  margin-bottom: var(--tm-space-6);
}

.tm-home__cta a {
  text-decoration: none;
}

/* === Decoration === */
.tm-home__decoration {
  position: absolute;
  bottom: 0;
  right: -20px;
  width: 160px;
  height: 240px;
  color: var(--tm-moss);
  opacity: 0.06;
  pointer-events: none;
}

/* === Responsive === */
@media (max-width: 768px) {
  .tm-home__hero {
    padding: var(--tm-space-12) var(--tm-space-4) var(--tm-space-8);
  }

  .tm-home__hero-title {
    font-size: var(--tm-text-2xl);
  }

  .tm-home__capabilities {
    grid-template-columns: 1fr;
    padding: 0 var(--tm-space-4) var(--tm-space-8);
  }

  .tm-home__capability-card {
    padding: var(--tm-space-6) var(--tm-space-4);
  }

  .tm-home__decoration {
    width: 100px;
    height: 150px;
  }
}

@media (max-width: 640px) {
  .tm-home__hero-title {
    font-size: var(--tm-text-2xl);
  }

  .tm-home__hero-subtitle {
    font-size: var(--tm-text-base);
  }
}
</style>
