<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "@/lib/useI18n"

const { t } = useI18n()

const highlightItems = computed(() => [
  t("home.highlightItems.0"),
  t("home.highlightItems.1"),
  t("home.highlightItems.2"),
  t("home.highlightItems.3")
])

const cards = computed(() => [
  {
    kicker: t("home.cards.search.kicker"),
    title: t("home.cards.search.title"),
    description: t("home.cards.search.description")
  },
  {
    kicker: t("home.cards.planning.kicker"),
    title: t("home.cards.planning.title"),
    description: t("home.cards.planning.description")
  },
  {
    kicker: t("home.cards.export.kicker"),
    title: t("home.cards.export.title"),
    description: t("home.cards.export.description")
  }
])
</script>

<template>
  <section class="page-grid">
    <div class="hero">
      <article class="panel hero-copy">
        <div>
          <p class="kicker">{{ t('home.kicker') }}</p>
          <h1>{{ t('home.title') }}</h1>
          <p>{{ t('home.description') }}</p>
        </div>
        <div class="inline-actions">
          <RouterLink class="solid-button" to="/trips/new">{{ t('common.startNewTrip') }}</RouterLink>
          <RouterLink class="ghost-button" to="/trips">{{ t('common.openDashboard') }}</RouterLink>
        </div>
      </article>

      <aside class="panel highlight-card">
        <div>
          <p class="kicker">{{ t('home.highlightKicker') }}</p>
          <h2>{{ t('home.highlightTitle') }}</h2>
        </div>
        <ul>
          <li v-for="item in highlightItems" :key="item">{{ item }}</li>
        </ul>
      </aside>
    </div>

    <div class="card-grid">
      <article v-for="card in cards" :key="card.title" class="metric-card">
        <p class="kicker">{{ card.kicker }}</p>
        <h3>{{ card.title }}</h3>
        <p>{{ card.description }}</p>
      </article>
    </div>
  </section>
</template>