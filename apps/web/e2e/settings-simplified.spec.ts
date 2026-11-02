import { expect, test, type Page } from "@playwright/test"
import { resolve } from "node:path"

function savedSettings(xhsAvailable = false) {
  return {
    agent: {
      provider_protocol: "newapi", base_url: "https://models.example.test/v1", api_key_masked: "sk-***abcd",
      has_api_key: true, model: "planner-model", wire_api: "responses", agent_provider: "langgraph", configured: true,
      poi_provider_protocol: "newapi", poi_base_url: "https://research.example.test/v1", poi_api_key_masked: "sk-***efgh",
      poi_has_api_key: true, poi_model: "research-model", weather_model: "weather-model", hotel_model: "hotel-model",
      transport_model: "transport-model", poi_wire_api: "responses", poi_configured: true
    },
    search: {
      provider: "groksearch", transport: "mcp", base_url: "https://search.example.test/mcp", api_key_masked: "mcp-***",
      has_api_key: true, timeout_seconds: 45, xhs_source_enabled: true, xhs_available: xhsAvailable, configured: true
    },
    image: { base_url: "https://images.example.test/v1", model: "image-model", provider: "openai_compatible", has_api_key: true, api_key_masked: "img-***", configured: true }
  }
}

async function mockSettings(page: Page, options: { xhsAvailable?: boolean; missingCapability?: boolean; loadError?: boolean } = {}) {
  let settings = savedSettings(options.xhsAvailable)
  if (options.missingCapability) delete (settings.search as Partial<typeof settings.search>).xhs_available
  const saved: any[] = []
  const tests: any[] = []
  const xhsRequests: string[] = []
  const envelope = (data: unknown, error: unknown = null) => ({ data, error, meta: { request_id: "settings-ui-test" } })
  await page.route("**/api/v1/**", async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const reply = (data: unknown, status = 200, error: unknown = null) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(envelope(data, error)) })
    if (path === "/api/v1/me") return reply({ id: "usr_settings_ui", name: "Settings test", email: "settings@example.test", is_admin: false, created_at: "2026-10-16T00:00:00Z" })
    if (path === "/api/v1/settings/llm") {
      if (request.method() === "PUT") {
        const payload = request.postDataJSON()
        saved.push(payload)
        settings = {
          agent: { ...settings.agent, ...payload.agent },
          search: { ...settings.search, ...payload.search },
          image: { ...settings.image, ...payload.image }
        }
        return reply(settings)
      }
      if (options.loadError) return reply(null, 503, { code: "unavailable", message: "Settings unavailable" })
      return reply(settings)
    }
    if (path === "/api/v1/llm/models") return reply({ base_url: "https://models.example.test/v1", models: [{ id: "available-model", name: "Available model" }] })
    if (path === "/api/v1/llm/test") {
      tests.push(request.postDataJSON())
      return reply(null, 503, { code: "pool_exhausted", message: "No eligible accounts" })
    }
    if (path.startsWith("/api/v1/account/xhs/")) {
      xhsRequests.push(path)
      return reply({ xhs_bound: false, xhs_binding_required: true, xhs_session_expired: false, xhs_message: "Bind Xiaohongshu to enable grounding.", active_binding: null })
    }
    return reply(null, 404, { code: "not_found", message: "Not mocked" })
  })
  return { saved, tests, xhsRequests }
}

for (const missingCapability of [false, true]) {
  test(`keeps optional settings collapsed and hides unavailable Xiaohongshu (legacy=${missingCapability})`, async ({ page }) => {
    const api = await mockSettings(page, { missingCapability })
    await page.goto("/settings")
    await expect(page.getByRole("heading", { name: "模型设置", exact: true })).toBeVisible()
    await expect(page.locator("#agent-model")).toHaveValue("planner-model")
    await expect(page.locator("#agent-api-key")).toHaveValue("")
    await expect(page.locator("#agent-provider-protocol")).toBeHidden()
    await expect(page.locator("#poi-base-url")).toBeHidden()
    await expect(page.locator("#search-base-url")).toBeHidden()
    await expect(page.locator("input:visible")).toHaveCount(3)
    await page.getByTestId("search-service-settings").locator("summary").first().click()
    await expect(page.getByTestId("xhs-settings")).toHaveCount(0)
    expect(api.xhsRequests).toEqual([])
    await page.getByRole("button", { name: "重新加载", exact: true }).click()
    await expect(page.locator("#agent-model")).toHaveValue("planner-model")
    expect(api.xhsRequests).toEqual([])
  })
}

test("saving basic changes preserves hidden settings, stored secrets and Responses format", async ({ page }) => {
  const api = await mockSettings(page)
  await page.goto("/settings")
  await expect(page.locator("#agent-model")).toHaveValue("planner-model")
  await page.locator("#agent-model").fill("new-planner-model")
  await page.getByRole("button", { name: "保存设置", exact: true }).click()
  await expect.poll(() => api.saved.length).toBe(1)
  expect(api.saved[0].agent).toMatchObject({ model: "new-planner-model", wire_api: "responses", agent_provider: "langgraph", poi_base_url: "https://research.example.test/v1", poi_model: "research-model", weather_model: "weather-model", hotel_model: "hotel-model", transport_model: "transport-model", poi_wire_api: "responses" })
  expect(api.saved[0].search).toMatchObject({ base_url: "https://search.example.test/mcp", timeout_seconds: 45 })
  expect(api.saved[0].image).toMatchObject({ model: "image-model", base_url: "https://images.example.test/v1" })
  expect(api.saved[0].agent).not.toHaveProperty("api_key")
  expect(api.saved[0].agent).not.toHaveProperty("poi_api_key")
  expect(api.saved[0].search).not.toHaveProperty("api_key")
  expect(api.saved[0].search).not.toHaveProperty("xhs_source_enabled")
  expect(api.saved[0].image).not.toHaveProperty("api_key")
})

test("model fetching and actual call failure stay distinct", async ({ page }) => {
  const api = await mockSettings(page)
  await page.goto("/settings")
  await page.getByRole("button", { name: "获取模型列表", exact: true }).click()
  await expect(page.locator("#agent-model-options option")).toHaveAttribute("value", "available-model")
  await expect(page.getByText("模型列表已加载，请从模型字段中选择。", { exact: true })).toBeVisible()
  await expect(page.getByText("当前模型不在返回列表中，请选择列表中的模型再测试。", { exact: true })).toBeVisible()
  await page.locator("#agent-model").fill("available-model")
  await expect(page.getByText("当前模型不在返回列表中，请选择列表中的模型再测试。", { exact: true })).toHaveCount(0)
  await page.locator("#agent-api-key").fill("test-new-key")
  await page.getByRole("button", { name: "测试调用", exact: true }).click()
  await expect(page.getByText("No eligible accounts", { exact: true })).toBeVisible()
  expect(api.tests[0]).toMatchObject({ model: "available-model", api_key: "test-new-key", wire_api: "responses" })
  expect(api.saved).toHaveLength(0)
})

test("separate research credentials can be explicitly cleared to follow the main model", async ({ page }) => {
  const api = await mockSettings(page)
  await page.goto("/settings")
  await page.getByTestId("research-model-settings").locator("summary").first().click()
  await page.getByRole("button", { name: "清除独立模型配置", exact: true }).click()
  await expect(page.locator("#poi-base-url")).toHaveValue("")
  await expect(page.getByTestId("research-model-settings").locator("summary").first()).toContainText("跟随主模型")
  await page.getByRole("button", { name: "保存设置", exact: true }).click()
  await expect.poll(() => api.saved.length).toBe(1)
  expect(api.saved[0].agent).toMatchObject({ poi_base_url: "", poi_model: "", poi_api_key: "", weather_model: "", hotel_model: "", transport_model: "" })
})

test("enabled Xiaohongshu remains available only in optional search settings", async ({ page }) => {
  const api = await mockSettings(page, { xhsAvailable: true })
  await page.goto("/settings")
  await expect.poll(() => api.xhsRequests.length).toBe(1)
  await expect(page.getByTestId("xhs-settings")).toBeHidden()
  await page.getByTestId("search-service-settings").locator("summary").first().click()
  await expect(page.getByTestId("xhs-settings")).toBeVisible()
  await expect(page.getByRole("button", { name: "开始绑定", exact: true })).toBeVisible()
})

test("settings remain readable on desktop and mobile", async ({ page }) => {
  await mockSettings(page)
  await page.setViewportSize({ width: 1440, height: 1100 })
  await page.goto("/settings")
  await expect(page.locator("#agent-model")).toHaveValue("planner-model")
  await page.screenshot({ path: resolve("../../.tmp/settings-redesign/screenshots/desktop.png"), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole("button", { name: "保存设置", exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: resolve("../../.tmp/settings-redesign/screenshots/mobile.png"), fullPage: true })
})

test("failed settings load cannot save an empty replacement", async ({ page }) => {
  const api = await mockSettings(page, { loadError: true })
  await page.goto("/settings")
  await expect(page.getByText("Settings unavailable", { exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "保存设置", exact: true })).toBeDisabled()
  expect(api.saved).toHaveLength(0)
})
