import { expect, test, type Page } from "@playwright/test"
import { mkdir } from "node:fs/promises"
import { resolve } from "node:path"

const user = { id: "journey-user", email: "journey@example.test", name: "旅行者", is_admin: false, is_disabled: false, created_at: "2026-10-17T00:00:00Z" }
const photo = "/src/assets/portal/mist-lake.webp"
const itinerary = {
  summary: "循着湖光与山林，慢慢展开三天的旅程。", total_budget_estimate: 1800, risks: ["图片与安排为自动化测试示例。"],
  days: Array.from({ length: 3 }, (_, di) => ({ day_index: di + 1, title: ["湖光与林间", "雨落的慢时光", "带一点轻盈回家"][di], summary: "留一点时间给路上的新发现。", total_cost: 600,
    items: Array.from({ length: 3 }, (_, si) => ({ id: `stop-${di}-${si}`, type: si === 1 ? "meal" : "sight", name: `第${di + 1}天的${["湖畔", "午餐", "山林"][si]}`, start_time: ["09:00", "12:00", "15:00"][si], end_time: ["11:00", "13:00", "17:00"][si], location: "测试地点", score: .9, note: "这里保留真实接口返回的地点描述，不编造交通距离。", image_urls: si === 1 ? [] : [photo], image_source_urls: si === 1 ? [] : ["https://example.test/photo-source"], image_status: "completed", booking_info: { reservation_required: true, booking_window: "提前7日", reminder: "请带好预约凭证。" } }))
  }))
}
async function mock(page: Page, options: { empty?: "days" | "stops" } = {}) {
  const writes: string[] = []
  const plan = structuredClone(itinerary)
  if (options.empty === "days") plan.days = []
  if (options.empty === "stops") plan.days = [{ ...plan.days[0], items: [] }]
  await page.addInitScript(() => localStorage.setItem("travelmind_locale", "zh-CN"))
  await page.route("**/api/v1/**", route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (!["GET", "HEAD"].includes(request.method())) writes.push(path)
    const fulfill = (data: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify({ data, error: null, meta: { request_id: "journey-e2e" } }) })
    if (path === "/api/v1/me") return fulfill(user)
    if (path === "/api/v1/settings/llm") return fulfill({ agent: { configured: true, has_api_key: true, model: "test-model", provider_protocol: "openai", wire_api: "responses" }, search: { configured: false }, image: { configured: false } })
    if (path === "/api/v1/trips/journey-e2e") return fulfill({ id: "journey-e2e", user_id: user.id, title: "山湖之间，留白三日。", origin: "日常", destination: "山湖之间", start_date: "2026-11-06", end_date: "2026-11-08", budget: 1800, travelers: 2, interests: ["森林"], pace: "slow", accommodation_preference: "安静", transport_mode: "rail", created_at: "2026-10-17T00:00:00Z", updated_at: "2026-10-17T00:00:00Z", itinerary: plan, latest_agent_trace: null, community_post: null })
    return fulfill(null, 404)
  })
  return writes
}
async function noOverflow(page: Page) { expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true) }
async function capture(page: Page, name: string) {
  await page.evaluate(() => document.fonts.ready)
  await expect.poll(() => page.locator(".journey-flow img:visible").evaluateAll(imgs => imgs.filter(img => img.getBoundingClientRect().top < innerHeight).every(img => (img as HTMLImageElement).complete))).toBe(true)
  const folder = resolve(process.cwd(), "../../output/ui-implementation/journey")
  await mkdir(folder, { recursive: true })
  await page.screenshot({ path: resolve(folder, name), animations: "disabled" })
}

test("generated itinerary opens as a connected journey, with real records and no automatic writes", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1080 })
  const writes = await mock(page), errors: string[] = []
  page.on("pageerror", error => errors.push(error.message))
  await page.goto("/trips/journey-e2e")
  await expect(page.locator(".journey-stop")).toHaveCount(9)
  await expect(page.locator(".journey-stop--compact")).toHaveCount(3)
  await expect(page.locator(".journey-timeline__base")).toHaveCount(3)
  for (const path of await page.locator(".journey-timeline__base").all()) { expect(await path.getAttribute("d")).toMatch(/^M .* C /); expect(await path.getAttribute("d")).not.toContain("NaN") }
  await expect(page.locator(".journey-flow").getByRole("heading", { level: 2 })).toHaveText(itinerary.summary)
  await expect(page.locator(".journey-stop__source a").first()).toHaveAttribute("href", "https://example.test/photo-source")
  await noOverflow(page); await capture(page, "journey-desktop.png")
  expect(writes).toEqual([]); expect(errors).toEqual([])
})

test("day navigation and reading progress follow scrolling", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" }); await mock(page); await page.goto("/trips/journey-e2e")
  const nav = page.getByRole("navigation", { name: "按天浏览行程" })
  await nav.getByRole("button", { name: "第2天：雨落的慢时光" }).click()
  await expect(nav.getByRole("button", { name: "第2天：雨落的慢时光" })).toHaveAttribute("aria-current", "step")
  await page.locator("#journey-day-2").scrollIntoViewIfNeeded()
  await expect.poll(() => nav.locator('[aria-current="step"]').innerText()).toContain("带一点轻盈回家")
  await expect.poll(() => page.locator(".journey-timeline__progress").first().evaluate(el => parseFloat(getComputedStyle(el).strokeDashoffset))).toBeLessThan(1)
})

test("native stop dialog closes with Escape, returns focus, and can locate full booking details", async ({ page }) => {
  await mock(page); await page.goto("/trips/journey-e2e")
  const card = page.getByRole("button", { name: "查看景点：第1天的湖畔", exact: true })
  await card.click()
  const dialog = page.getByRole("dialog", { name: "景点详情" })
  await expect(dialog).toBeVisible(); await expect(dialog.getByRole("heading")).toHaveText("第1天的湖畔")
  const box = await dialog.boundingBox(), viewport = page.viewportSize()
  expect(box).not.toBeNull()
  if (box && viewport) { expect(Math.abs(box.x - (viewport.width - box.width) / 2)).toBeLessThan(3); expect(Math.abs(box.y - (viewport.height - box.height) / 2)).toBeLessThan(3) }
  await expect(page.getByRole("button", { name: "关闭景点详情" })).toBeFocused()
  await page.keyboard.press("Escape"); await expect(dialog).not.toBeVisible(); await expect(card).toBeFocused()
  expect(await page.evaluate(() => document.body.style.overflow)).not.toBe("hidden")
  await card.click(); await dialog.getByRole("button", { name: "查看预订与完整信息 ↗", exact: true }).click()
  const fullStop = page.locator('#itinerary-stop-1-stop-0-0')
  await expect(fullStop).toBeVisible(); await expect(fullStop).toBeFocused(); await expect(fullStop).toContainText("提前7日")
  await page.getByRole("button", { name: "流动旅程", exact: true }).click()
  await expect(page.locator(".journey-flow")).toBeVisible()
})

test("mobile has a single readable route and a horizontally scrollable day selector", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); await page.emulateMedia({ reducedMotion: "reduce" })
  await mock(page); await page.goto("/trips/journey-e2e"); await expect(page.locator(".journey-stop")).toHaveCount(9)
  await noOverflow(page); await capture(page, "journey-mobile.png")
  const nav = page.getByRole("navigation", { name: "按天浏览行程" })
  await nav.getByRole("button", { name: "第3天：带一点轻盈回家" }).click()
  await expect(nav.getByRole("button", { name: "第3天：带一点轻盈回家" })).toHaveAttribute("aria-current", "step")
  await noOverflow(page)
  await page.setViewportSize({ width: 320, height: 844 }); await noOverflow(page)
})

test("reduced motion disables entry and hover movement", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" }); await mock(page); await page.goto("/trips/journey-e2e")
  const card = page.locator(".journey-stop__card").first(); await card.hover()
  expect(await card.evaluate(el => getComputedStyle(el).animationName)).toBe("none")
  expect(await card.evaluate(el => getComputedStyle(el).transform)).toBe("none")
})

for (const empty of ["days", "stops"] as const) test(`empty ${empty} remain readable without invented places`, async ({ page }) => {
  await mock(page, { empty }); await page.goto("/trips/journey-e2e")
  await expect(page.locator(".journey-flow__empty")).toBeVisible(); await expect(page.locator(".journey-stop")).toHaveCount(0)
  await page.getByRole("button", { name: "完整清单", exact: true }).click(); await expect(page.locator("#itinerary")).toBeVisible()
})

test("isolated preview offers three days, an eight-stop day, and honest image fallbacks", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1080 }); const writes = await mock(page)
  await page.goto("/__preview/journey")
  await expect(page.getByText("演示数据 · AI 氛围图，非景点实景 · 不会调用模型或写入真实行程")).toBeVisible()
  await expect(page.locator(".journey-chapter")).toHaveCount(3); await capture(page, "journey-preview-desktop.png")
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.getByRole("navigation", { name: "按天浏览行程" }).getByRole("button").first().click()
  await capture(page, "journey-preview-focus.png")
  await page.getByLabel("预览场景").selectOption("busy-day")
  await expect(page.locator(".journey-stop")).toHaveCount(8); await expect(page.locator(".journey-timeline__base")).toHaveCount(1); await noOverflow(page)
  await page.getByLabel("预览场景").selectOption("missing-images")
  await expect(page.locator(".journey-stop")).toHaveCount(3)
  await expect(page.getByText("景点图片正在补充", { exact: true })).toBeVisible()
  await expect(page.locator(".journey-stop").nth(1).locator("img")).toHaveAttribute("src", /forest-flow/)
  await page.locator(".journey-stop").last().scrollIntoViewIfNeeded()
  await expect(page.locator(".journey-stop").last().locator(".poi-image-empty")).toBeVisible()
  expect(writes).toEqual([])
})

test("journey reconnects after leaving and returning to a cached trip", async ({ page }) => {
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message))
  await mock(page); await page.goto("/trips/journey-e2e")
  await expect(page.locator(".journey-stop")).toHaveCount(9)
  await page.getByRole("link", { name: "TravelMind AI · 返回首页", exact: true }).click()
  await expect(page).toHaveURL(/\/$/); await expect(page.getByRole("heading", { level: 1 })).toContainText("每一次出发"); await page.goBack()
  await expect(page.locator(".journey-timeline__base")).toHaveCount(3)
  await page.getByRole("navigation", { name: "按天浏览行程" }).getByRole("button").nth(1).click()
  await expect(page.getByRole("navigation", { name: "按天浏览行程" }).locator('[aria-current="step"]')).toContainText("雨落的慢时光")
  expect(errors).toEqual([])
})

for (const width of [768, 1024]) test(`tablet ${width}px keeps long-day markers aligned and controls readable`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 }); await mock(page); await page.goto("/__preview/journey")
  await page.getByLabel("预览场景").selectOption("busy-day")
  await expect(page.locator(".journey-stop")).toHaveCount(8)
  await expect(page.locator(".journey-timeline__base")).toHaveCount(1)
  await noOverflow(page)
  const y = await page.locator(".journey-stop__marker").evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().top))
  expect(y.every((value, i) => i === 0 || value > y[i - 1])).toBe(true)
  await page.getByRole("button", { name: "时间清单", exact: true }).click()
  await expect(page.locator(".journey-preview__list li")).toHaveCount(8)
  await page.getByRole("button", { name: "流动旅程", exact: true }).click()
  await expect(page.locator(".journey-timeline__base")).toHaveCount(1)
})
