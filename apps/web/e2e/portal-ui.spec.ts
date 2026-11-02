import { expect, test, type Page } from "@playwright/test"
import { mkdir } from "node:fs/promises"
import { resolve } from "node:path"

const user = { id: "portal-user", email: "traveler@example.test", name: "旅行者", is_admin: false, is_disabled: false, created_at: "2026-10-16T00:00:00Z" }
const trips = [
  { id: "portal-kyoto", title: "京都的咖啡与小巷", origin: "上海", destination: "京都", interests: ["咖啡", "城市漫步"], itinerary: null },
  { id: "portal-lake", title: "湖畔慢游的三天", origin: "苏州", destination: "杭州", interests: ["湖泊"], itinerary: { summary: "沿着湖岸散步，留一点时间给自己。", days: [], total_budget_estimate: 2200, risks: [] } },
  { id: "portal-forest", title: "山林里的周末", origin: "成都", destination: "川西", interests: ["森林"], itinerary: null }
].map((trip, index) => ({
  user_id: user.id, start_date: `2026-11-${String(6 + index).padStart(2, "0")}`, end_date: `2026-11-${String(9 + index).padStart(2, "0")}`,
  budget: 6800 - index * 1500, travelers: 2, accommodation_preference: "安静", pace: "slow", transport_mode: "rail",
  created_at: "2026-10-16T00:00:00Z", updated_at: "2026-10-16T00:00:00Z", community_post: null, ...trip
}))
const settings = {
  agent: { provider_protocol: "openai", base_url: null, model: null, has_api_key: false, configured: false, wire_api: "responses", agent_provider: "standard" },
  search: { configured: false, provider: "groksearch", transport: "mcp", has_api_key: false, timeout_seconds: 30, xhs_source_enabled: false },
  image: { configured: false, has_api_key: false, base_url: null, model: null, provider: "openai_compatible" }
}
const envelope = (data: unknown, error: unknown = null) => ({ data, error, meta: { request_id: "portal-ui-e2e" } })

async function mockApi(page: Page, options: { authenticated?: boolean; empty?: boolean; listFailures?: number; deleteFails?: boolean; administrator?: boolean } = {}) {
  let authenticated = options.authenticated ?? true
  let remainingFailures = options.listFailures ?? 0
  let records = options.empty ? [] : [...trips]
  const writes: string[] = []
  await page.addInitScript(() => localStorage.setItem("travelmind_locale", "zh-CN"))
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    if (method === "POST") writes.push(path)
    const fulfill = (data: unknown, status = 200, error: unknown = null) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(envelope(data, error)) })
    if (path === "/api/v1/me") return authenticated ? fulfill({ ...user, is_admin: options.administrator ?? false }) : fulfill(null, 401, { code: "unauthorized", message: "Sign in required" })
    if (path === "/api/v1/auth/refresh") return fulfill(null, 401, { code: "unauthorized", message: "No session" })
    if (path === "/api/v1/auth/login") { authenticated = true; return fulfill(user) }
    if (path === "/api/v1/auth/logout") { authenticated = false; return fulfill(null) }
    if (path === "/api/v1/settings/llm") return fulfill(settings)
    if (path === "/api/v1/trips" && method === "GET") {
      if (remainingFailures-- > 0) return fulfill(null, 503, { code: "unavailable", message: "暂时无法读取行程" })
      return fulfill(records)
    }
    if (path.startsWith("/api/v1/trips/") && method === "DELETE") {
      if (options.deleteFails) return fulfill(null, 500, { code: "delete_failed", message: "删除未完成，请稍后重试。" })
      const tripId = path.split("/").at(-1)
      records = records.filter((trip) => trip.id !== tripId)
      return fulfill({ success: true, trip_id: tripId })
    }
    return fulfill(null, 404, { code: "not_found", message: `Unhandled test route: ${path}` })
  })
  return { writes }
}

async function assertNoHorizontalOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
}
async function screenshot(page: Page, filename: string) {
  await page.evaluate(() => document.fonts.ready)
  await expect.poll(() => page.locator("img:visible").evaluateAll((images) => images.every((image) => (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0))).toBe(true)
  const folder = resolve(process.cwd(), "../../output/ui-implementation")
  await mkdir(folder, { recursive: true })
  await page.screenshot({ path: resolve(folder, filename), fullPage: true })
}

test("public homepage matches the portal direction and has no runtime errors", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1080 })
  await mockApi(page, { authenticated: false })
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))
  await page.goto("/")
  await expect(page.getByRole("heading", { level: 1 })).toContainText("每一次出发")
  await expect(page.getByRole("button", { name: "开始规划" })).toBeVisible()
  await assertNoHorizontalOverflow(page)
  await screenshot(page, "home-desktop.png")
  expect(errors).toEqual([])
})

test("homepage brief survives authentication and waits for explicit AI submission", async ({ page }) => {
  const api = await mockApi(page, { authenticated: false })
  const brief = "我想去京都，喜欢咖啡和安静的小巷，慢慢玩四天。"
  await page.goto("/")
  await page.getByLabel("下一站，从一个念头开始").fill(brief)
  await page.getByRole("button", { name: "开始规划" }).click()
  await expect(page).toHaveURL(/\/login\?redirect=/)
  await page.locator("#email").fill("traveler@example.test")
  await page.locator("#password").fill("a-test-password")
  await page.locator('form button[type="submit"]').click()
  await expect(page).toHaveURL(/\/trips\/new\?prompt=/)
  await expect(page.getByLabel("回复", { exact: true })).toHaveValue(brief)
  expect(api.writes.filter((path) => path !== "/api/v1/auth/refresh")).toEqual(["/api/v1/auth/login"])
})

test("travel studio renders API records, working search and real itinerary filters", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 })
  await mockApi(page)
  await page.goto("/trips")
  await expect(page.getByRole("heading", { name: "我的旅行", exact: true })).toBeVisible()
  await expect(page.locator(".studio-trip-card")).toHaveCount(3)
  await assertNoHorizontalOverflow(page)
  await screenshot(page, "studio-desktop.png")
  await page.getByRole("searchbox", { name: "搜索行程或目的地" }).fill("京都")
  await expect(page.locator(".studio-trip-card")).toHaveCount(1)
  await expect(page.locator(".studio-trip-card")).toContainText("京都的咖啡与小巷")
  await page.getByRole("button", { name: "清空搜索", exact: true }).click()
  await page.getByRole("button", { name: "已生成", exact: true }).click()
  await expect(page.locator(".studio-trip-card")).toHaveCount(1)
  await expect(page.locator(".studio-trip-card")).toContainText("湖畔慢游的三天")
  await page.getByRole("button", { name: "规划中", exact: true }).click()
  await expect(page.locator(".studio-trip-card")).toHaveCount(2)
  await page.getByRole("searchbox").fill("不存在的目的地")
  await expect(page.getByRole("heading", { name: "暂时没有找到这段旅程" })).toBeVisible()
  await page.getByRole("button", { name: "清除搜索与筛选" }).click()
  await expect(page.locator(".studio-trip-card")).toHaveCount(3)
})

test("empty accounts show no fabricated trips and retain a working creation link", async ({ page }) => {
  await mockApi(page, { empty: true })
  await page.goto("/trips")
  await expect(page.locator(".studio-collection > .state-panel--empty")).toBeVisible()
  await expect(page.locator(".studio-trip-card")).toHaveCount(0)
  await expect(page.locator(".studio-feature")).toHaveCount(0)
  await expect(page.locator('.state-panel a[href="/trips/new"]')).toBeVisible()
})

test("failed trip loading can be retried", async ({ page }) => {
  await mockApi(page, { listFailures: 1 })
  await page.goto("/trips")
  await expect(page.locator(".state-panel--error")).toContainText("暂时无法读取行程")
  await page.getByRole("button", { name: "重试", exact: true }).click()
  await expect(page.locator(".studio-trip-card")).toHaveCount(3)
})

test("trip deletion is confirmed, supports cancellation, and updates the live collection", async ({ page }) => {
  await mockApi(page)
  await page.goto("/trips")
  const deleteButton = page.getByRole("button", { name: "删除行程：京都的咖啡与小巷", exact: true })
  await expect(deleteButton).toBeVisible()
  page.once("dialog", (dialog) => dialog.dismiss())
  await deleteButton.click()
  await expect(page.locator(".studio-trip-card")).toHaveCount(3)
  page.once("dialog", (dialog) => dialog.accept())
  await deleteButton.click()
  await expect(page.locator(".studio-trip-card")).toHaveCount(2)
  await expect(page.locator(".studio-feature")).not.toContainText("京都的咖啡与小巷")
})

test("a failed deletion preserves the records and displays a recoverable error", async ({ page }) => {
  await mockApi(page, { deleteFails: true })
  await page.goto("/trips")
  page.once("dialog", (dialog) => dialog.accept())
  await page.getByRole("button", { name: "删除行程：京都的咖啡与小巷", exact: true }).click()
  await expect(page.getByRole("heading", { name: "删除行程失败" })).toBeVisible()
  await expect(page.locator(".studio-trip-card")).toHaveCount(3)
})

test("mobile landing and studio remain usable without horizontal scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockApi(page)
  await page.goto("/")
  await expect(page.getByRole("button", { name: "开始规划" })).toBeVisible()
  await assertNoHorizontalOverflow(page)
  await screenshot(page, "home-mobile.png")
  const menu = page.locator(".tm-menu-toggle")
  await menu.click()
  await expect(menu).toHaveAttribute("aria-expanded", "true")
  await page.keyboard.press("Escape")
  await expect(menu).toHaveAttribute("aria-expanded", "false")
  await menu.click()
  await page.locator("#tm-mobile-navigation").getByRole("link", { name: "我的行程", exact: true }).click()
  await expect(page).toHaveURL(/\/trips$/)
  await expect(page.locator("#tm-mobile-navigation")).toHaveCount(0)
  await expect(page.locator(".studio-trip-card")).toHaveCount(3)
  await page.locator(".studio-trip-card").last().scrollIntoViewIfNeeded()
  await page.evaluate(() => window.scrollTo(0, 0))
  await assertNoHorizontalOverflow(page)
  await screenshot(page, "studio-mobile.png")
  await page.getByRole("searchbox").fill("杭州")
  await expect(page.locator(".studio-trip-card")).toHaveCount(1)
})

test("reduced-motion users do not get card zoom or moving transitions", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  await mockApi(page)
  await page.goto("/trips")
  const card = page.locator(".studio-trip-card").first()
  await card.hover()
  expect(await card.evaluate((element) => getComputedStyle(element).transform)).toBe("none")
})


test("narrow and tablet layouts keep planning and collection controls within the viewport", async ({ page }) => {
  await mockApi(page)
  for (const width of [320, 768, 1024]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto("/")
    await expect(page.getByLabel("下一站，从一个念头开始")).toBeVisible()
    await assertNoHorizontalOverflow(page)
    await page.goto("/trips")
    await expect(page.locator(".studio-trip-card")).toHaveCount(3)
    await assertNoHorizontalOverflow(page)
  }
})

test("standard pages keep administrator navigation usable on tablet", async ({ page }) => {
  await page.setViewportSize({ width: 960, height: 900 })
  await mockApi(page, { administrator: true })
  await page.goto("/trips/new")
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible()
  await assertNoHorizontalOverflow(page)
  const menu = page.locator(".tm-menu-toggle")
  if (await menu.isVisible()) {
    await menu.click()
    await expect(page.locator("#tm-mobile-navigation").getByRole("link", { name: "后台管理" })).toBeVisible()
  } else {
    await expect(page.locator(".tm-topbar__nav").getByRole("link", { name: "后台管理" })).toBeVisible()
  }
})
