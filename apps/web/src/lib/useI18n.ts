import { computed } from "vue"
import { SUPPORTED_LOCALES, translate, type LocaleCode } from "@/lib/i18n"
import { useLocaleStore } from "@/stores/locale"

export function useI18n() {
  const localeStore = useLocaleStore()

  return {
    locale: computed(() => localeStore.locale),
    supportedLocales: SUPPORTED_LOCALES,
    setLocale: (locale: LocaleCode) => localeStore.setLocale(locale),
    t: (key: string, params?: Record<string, string | number>) => translate(localeStore.locale, key, params)
  }
}