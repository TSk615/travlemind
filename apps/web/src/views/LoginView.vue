<script setup lang="ts">
import { computed, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import StatePanel from "@/components/StatePanel.vue"
import { useI18n } from "@/lib/useI18n"
import { useAuthStore } from "@/stores/auth"

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const { t } = useI18n()

const mode = ref<"login" | "register">("login")
const name = ref("Traveler")
const email = ref("demo@travelmind.ai")
const password = ref("changeme123")

const submitLabel = computed(() => {
  if (auth.pending) {
    return mode.value === "login" ? t("login.signingIn") : t("login.creatingAccount")
  }

  return mode.value === "login" ? t("login.signIn") : t("login.createAccount")
})

const helperText = computed(() => {
  return mode.value === "login" ? t("login.helperLogin") : t("login.helperRegister")
})

function setMode(nextMode: "login" | "register") {
  mode.value = nextMode
  auth.clearError()
}

async function submit() {
  auth.clearError()

  try {
    if (mode.value === "login") {
      await auth.login(email.value, password.value)
    } else {
      await auth.register(name.value, email.value, password.value)
    }

    const redirect = typeof route.query.redirect === "string" ? route.query.redirect : "/trips"
    await router.push(redirect)
  } catch {
    return
  }
}
</script>

<template>
  <section class="page-grid" style="max-width: 780px; margin: 0 auto;">
    <article class="panel panel-stack">
      <div>
        <p class="kicker">{{ t('login.kicker') }}</p>
        <h1>{{ mode === 'login' ? t('login.welcomeBack') : t('login.createTitle') }}</h1>
        <p class="muted">{{ helperText }}</p>
      </div>

      <div class="inline-actions">
        <button :class="mode === 'login' ? 'primary' : ''" type="button" @click="setMode('login')">{{ t('login.loginTab') }}</button>
        <button :class="mode === 'register' ? 'primary' : ''" type="button" @click="setMode('register')">{{ t('login.registerTab') }}</button>
      </div>

      <StatePanel
        v-if="auth.bootstrapping"
        kind="loading"
        :title="t('login.checkingTitle')"
        :message="t('login.checkingMessage')"
        compact
      />

      <template v-else>
        <StatePanel
          v-if="auth.error"
          kind="error"
          :title="mode === 'login' ? t('login.unableSignIn') : t('login.unableCreate')"
          :message="auth.error"
          compact
        />

        <form class="form-grid" @submit.prevent="submit">
          <div v-if="mode === 'register'" class="field field--full">
            <label for="name">{{ t('login.name') }}</label>
            <input id="name" v-model="name" required minlength="2" />
          </div>

          <div class="field">
            <label for="email">{{ t('login.email') }}</label>
            <input id="email" v-model="email" type="email" required />
          </div>

          <div class="field">
            <label for="password">{{ t('login.password') }}</label>
            <input id="password" v-model="password" type="password" required minlength="8" />
          </div>

          <div class="field field--full inline-actions">
            <button class="primary" :disabled="auth.pending" type="submit">{{ submitLabel }}</button>
            <p class="muted">
              {{ mode === 'login' ? t('login.cookieNote') : t('login.registerNote') }}
            </p>
          </div>
        </form>
      </template>
    </article>
  </section>
</template>