import { defineStore } from "pinia"
import { applyLocale, DEFAULT_LOCALE, normalizeLocale, readPreferredLocale, type LocaleCode } from "@/lib/i18n"

interface LocaleState {
  locale: LocaleCode
  initialized: boolean
}

export const useLocaleStore = defineStore("locale", {
  state: (): LocaleState => ({
    locale: DEFAULT_LOCALE,
    initialized: false
  }),
  actions: {
    bootstrap() {
      if (this.initialized) {
        return
      }

      this.setLocale(readPreferredLocale())
    },
    setLocale(nextLocale: string) {
      const normalized = normalizeLocale(nextLocale)
      this.locale = normalized
      this.initialized = true
      applyLocale(normalized)
    }
  }
})