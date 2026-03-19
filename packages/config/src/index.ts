export const appConfig = {
  appName: "TravelMind AI",
  apiBaseUrl: (import.meta as ImportMeta & { env?: Record<string, string> }).env?.VITE_API_BASE_URL ?? "http://127.0.0.1:8000"
}
