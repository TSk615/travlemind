import { defineStore } from "pinia"
import { applyLocale, DEFAULT_LOCALE, type LocaleCode } from "@/lib/i18n"

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

      this.setLocale("zh-CN")
    },
    setLocale(_nextLocale: string) {
      const normalized: LocaleCode = "zh-CN"
      this.locale = normalized
      this.initialized = true
      applyLocale(normalized)
    }
  }
})
